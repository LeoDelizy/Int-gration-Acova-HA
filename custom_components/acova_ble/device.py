"""Orchestration BLE d'un radiateur ACOVA (au-dessus de `protocol`).

Connexion à la demande : établir la connexion, activer les notifications, exécuter
la séquence lecture/écriture, puis se déconnecter.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from . import const, protocol

_LOGGER = logging.getLogger(__name__)


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

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Met à jour le BLEDevice (adresse résolue par HA à chaque poll)."""
        self._ble_device = ble_device

    # --- Session de connexion ---------------------------------------------

    @asynccontextmanager
    async def _session(self):
        def _on_notify(_sender, data: bytearray) -> None:
            self._notifications.put_nowait(bytes(data))

        client = await establish_connection(
            BleakClient, self._ble_device, self._name
        )
        try:
            _LOGGER.debug("[%s] Connected; dumping GATT table", self._name)
            for service in client.services:
                for char in service.characteristics:
                    _LOGGER.debug(
                        "  svc=%s char=%s props=%s",
                        service.uuid, char.uuid, char.properties,
                    )
            # Certains modules ACOVA n'envoient de notifications qu'une fois appairés.
            try:
                if await client.pair():
                    _LOGGER.debug("[%s] Paired", self._name)
            except Exception as err:  # noqa: BLE001 - pairing best effort
                _LOGGER.debug("[%s] Pairing skipped/failed: %s", self._name, err)
            while not self._notifications.empty():
                self._notifications.get_nowait()
            await client.start_notify(const.UUID_CHAR_DATA, _on_notify)
            yield client
        finally:
            try:
                await client.stop_notify(const.UUID_CHAR_DATA)
            except Exception:  # noqa: BLE001 - best effort au nettoyage
                pass
            await client.disconnect()

    async def _next_notification(self) -> bytes:
        try:
            return await asyncio.wait_for(
                self._notifications.get(), const.NOTIFY_TIMEOUT
            )
        except asyncio.TimeoutError as err:
            raise AcovaError("timeout notification") from err

    # --- Primitives lecture/écriture --------------------------------------

    async def _read_dp(self, client, dp: tuple[int, int]) -> bytes:
        object_id, data_id = dp
        _LOGGER.debug("[%s] read dp (%s,%s): write cmd", self._name, object_id, data_id)
        await client.write_gatt_char(
            const.UUID_CHAR_CMD, protocol.build_read_request(object_id, data_id), response=True
        )
        raw = await self._next_notification()
        _LOGGER.debug("[%s] read dp (%s,%s): notif=%s", self._name, object_id, data_id, raw.hex())
        got = protocol.parse_notification(raw)
        if got[0] != object_id or got[1] != data_id:
            raise AcovaError(
                f"écho inattendu: attendu ({object_id},{data_id}), reçu ({got[0]},{got[1]})"
            )
        if protocol.needs_followup_read(raw):
            raw = await client.read_gatt_char(const.UUID_CHAR_DATA)
            got = protocol.parse_notification(raw)
        return got[2]

    async def _write_dp(self, client, dp: tuple[int, int], value: bytes) -> None:
        object_id, data_id = dp
        await client.write_gatt_char(
            const.UUID_CHAR_DATA,
            protocol.build_write_payload(object_id, data_id, value),
            response=True,
        )
        ack = protocol.parse_notification(await client.read_gatt_char(const.UUID_CHAR_DATA))
        if ack[0] != object_id or ack[1] != data_id:
            raise AcovaError("ack payload invalide")
        await client.write_gatt_char(
            const.UUID_CHAR_CMD, protocol.build_write_commit(object_id, data_id), response=True
        )
        final = protocol.parse_notification(await client.read_gatt_char(const.UUID_CHAR_DATA))
        if final[0] != 0 or final[1] != 0:
            raise AcovaError("ack commit invalide")

    # --- API métier --------------------------------------------------------

    async def async_read_state(self) -> AcovaState:
        async with self._lock, self._session() as client:
            mode = (await self._read_dp(client, const.DP_THERMOSTAT_MODE))[0]
            comfo = (await self._read_dp(client, const.DP_COMFO_SETPOINT))[0]
            try:
                eco = (await self._read_dp(client, const.DP_ECO_SETPOINT))[0]
                eco_temp = protocol.byte_to_temp(eco)
            except AcovaError:
                eco_temp = None
            return AcovaState(
                mode=mode,
                comfort_temp=protocol.byte_to_temp(comfo),
                eco_temp=eco_temp,
            )

    async def async_set_mode(self, mode: int) -> None:
        async with self._lock, self._session() as client:
            await self._write_dp(client, const.DP_THERMOSTAT_MODE, bytes([mode]))

    async def async_set_comfort_temp(self, celsius: float) -> None:
        async with self._lock, self._session() as client:
            await self._write_dp(
                client, const.DP_COMFO_SETPOINT, bytes([protocol.temp_to_byte(celsius)])
            )
