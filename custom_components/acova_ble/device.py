"""Orchestration BLE d'un radiateur ACOVA (au-dessus de `protocol`).

Connexion à la demande, fidèle à l'app ACOVA Control :
- délai d'1 s après connexion avant toute opération ;
- lecture : commande [0, obj, data] puis réponse par notification, avec repli en
  lecture directe de la caractéristique Données (qui est aussi `read`) ;
- accusés d'écriture relus jusqu'à ACK_RETRIES fois (retry(10) de l'app).

Le radiateur ignore les commandes d'un client non appairé (réponses à zéro).
L'appairage BLE se valide en appuyant sur le bouton 2H du thermostat quand sa LED
clignote rapidement ; BlueZ conserve ensuite le lien.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypeVar

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from . import const, protocol
from .agent import PairingAgentError, pairing_agent

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class AcovaError(Exception):
    """Erreur de communication avec le radiateur."""


@dataclass
class AcovaState:
    """État lu du radiateur."""

    mode: int
    comfort_temp: float
    eco_temp: float | None = None


class AcovaDevice:
    """Client BLE haut niveau pour un radiateur ACOVA."""

    def __init__(self, ble_device: BLEDevice, name: str) -> None:
        self._ble_device = ble_device
        self._name = name
        self._lock = asyncio.Lock()
        self._notifications: asyncio.Queue[bytes] = asyncio.Queue()
        self._notify_ok = False

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Met à jour le BLEDevice (adresse résolue par HA à chaque poll)."""
        self._ble_device = ble_device

    # --- Session de connexion ---------------------------------------------

    @asynccontextmanager
    async def _session(self, pair: bool = False):
        def _on_notify(_sender, data: bytearray) -> None:
            self._notifications.put_nowait(bytes(data))

        client = await establish_connection(BleakClient, self._ble_device, self._name)
        try:
            await asyncio.sleep(const.POST_CONNECT_DELAY)
            if pair:
                _LOGGER.debug("[%s] appairage : appuyer sur 2H quand la LED clignote", self._name)
                async with pairing_agent(getattr(self._ble_device, "address", "")):
                    await client.pair()
            for service in client.services:
                for char in service.characteristics:
                    _LOGGER.debug(
                        "[%s] svc=%s char=%s props=%s",
                        self._name, service.uuid, char.uuid, char.properties,
                    )
            while not self._notifications.empty():
                self._notifications.get_nowait()
            try:
                await client.start_notify(const.UUID_CHAR_DATA, _on_notify)
                self._notify_ok = True
            except BleakError as err:
                self._notify_ok = False
                _LOGGER.debug("[%s] start_notify impossible (%s) : lectures directes", self._name, err)
            yield client
        finally:
            if self._notify_ok:
                try:
                    await client.stop_notify(const.UUID_CHAR_DATA)
                except BleakError:
                    pass
            try:
                await client.disconnect()
            except BleakError:
                pass

    async def _run(
        self, operation: Callable[[BleakClient], Awaitable[_T]], pair: bool = False
    ) -> _T:
        """Exécute une opération dans une session en traduisant les erreurs BLE."""
        async with self._lock:
            try:
                async with self._session(pair) as client:
                    return await operation(client)
            except (BleakError, TimeoutError, PairingAgentError) as err:
                raise AcovaError(f"BLE : {err}") from err

    # --- Réception des réponses -------------------------------------------

    async def _wait_notification(self, object_id: int, data_id: int) -> bytes | None:
        """Attend la notification correspondant au datapoint, None si absente."""
        if not self._notify_ok:
            return None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + const.NOTIFY_WAIT
        while (remaining := deadline - loop.time()) > 0:
            try:
                raw = await asyncio.wait_for(self._notifications.get(), remaining)
            except TimeoutError:
                return None
            if len(raw) >= 3 and raw[0] == object_id and raw[1] == data_id:
                return raw
            _LOGGER.debug("[%s] notification ignorée : %s", self._name, raw.hex())
        return None

    async def _read_until(self, client: BleakClient, object_id: int, data_id: int) -> bytes:
        """Relit la caractéristique Données jusqu'à obtenir l'écho attendu."""
        raw = b""
        for attempt in range(1, const.ACK_RETRIES + 1):
            raw = bytes(await client.read_gatt_char(const.UUID_CHAR_DATA))
            if len(raw) >= 3 and raw[0] == object_id and raw[1] == data_id:
                return raw
            _LOGGER.debug(
                "[%s] attente écho (%s,%s), lecture %s : %s",
                self._name, object_id, data_id, attempt, raw.hex(),
            )
            await asyncio.sleep(const.ACK_RETRY_DELAY)
        hint = " ; réponse vide : radiateur non appairé (bouton 2H) ?" if not any(raw) else ""
        raise AcovaError(
            f"pas d'écho ({object_id},{data_id}) après {const.ACK_RETRIES} lectures{hint}"
        )

    # --- Primitives lecture/écriture --------------------------------------

    async def _read_dp(self, client: BleakClient, dp: tuple[int, int]) -> bytes:
        object_id, data_id = dp
        await client.write_gatt_char(
            const.UUID_CHAR_CMD, protocol.build_read_request(object_id, data_id), response=True
        )
        raw = await self._wait_notification(object_id, data_id)
        if raw is None:
            _LOGGER.debug("[%s] (%s,%s) sans notification : lecture directe", self._name, object_id, data_id)
            raw = await self._read_until(client, object_id, data_id)
        elif protocol.needs_followup_read(raw):
            raw = await self._read_until(client, object_id, data_id)
        _LOGGER.debug("[%s] (%s,%s) = %s", self._name, object_id, data_id, raw.hex())
        return protocol.parse_notification(raw)[2]

    async def _write_dp(self, client: BleakClient, dp: tuple[int, int], value: bytes) -> None:
        object_id, data_id = dp
        await client.write_gatt_char(
            const.UUID_CHAR_DATA,
            protocol.build_write_payload(object_id, data_id, value),
            response=True,
        )
        await self._read_until(client, object_id, data_id)
        await client.write_gatt_char(
            const.UUID_CHAR_CMD, protocol.build_write_commit(object_id, data_id), response=True
        )
        await self._read_until(client, 0, 0)

    # --- API métier --------------------------------------------------------

    async def _read_state(self, client: BleakClient) -> AcovaState:
        mode = (await self._read_dp(client, const.DP_THERMOSTAT_MODE))[0]
        comfo = (await self._read_dp(client, const.DP_COMFO_SETPOINT))[0]
        try:
            eco_temp = protocol.byte_to_temp(
                (await self._read_dp(client, const.DP_ECO_SETPOINT))[0]
            )
        except AcovaError:
            eco_temp = None
        return AcovaState(
            mode=mode, comfort_temp=protocol.byte_to_temp(comfo), eco_temp=eco_temp
        )

    async def async_read_state(self) -> AcovaState:
        return await self._run(self._read_state)

    async def async_pair(self) -> AcovaState:
        """Appaire le radiateur (validation par le bouton 2H) puis vérifie par une lecture."""
        return await self._run(self._read_state, pair=True)

    async def async_set_mode(self, mode: int) -> None:
        await self._run(
            lambda client: self._write_dp(client, const.DP_THERMOSTAT_MODE, bytes([mode]))
        )

    async def async_set_comfort_temp(self, celsius: float) -> None:
        value = bytes([protocol.temp_to_byte(celsius)])
        await self._run(
            lambda client: self._write_dp(client, const.DP_COMFO_SETPOINT, value)
        )
