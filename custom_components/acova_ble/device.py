"""Orchestration BLE d'un radiateur ACOVA (au-dessus de `protocol`).

Connexion permanente avec reconnexion automatique :
- le lien BLE est maintenu entre les opérations (le radiateur n'accepte qu'un
  seul client : l'app ACOVA Control doit donc rester fermée) ;
- chaque opération vérifie le lien et se reconnecte au besoin (le chemin BlueZ
  est rafraîchi auprès de Home Assistant à chaque reconnexion) ;
- une erreur de liaison entraîne une reconnexion puis une nouvelle tentative
  complète ; une erreur de protocole, non : le radiateur répond, mais mal ;
- chaque opération est bornée dans le temps (`OP_TIMEOUT`).

Erreurs distinguées :
- `AcovaConnectionError` : liaison BLE (transitoire) — on peut réessayer ;
- `AcovaProtocolError`   : réponses vides ou hors protocole — radiateur en
  veille ou non appairé (validation par le bouton 2H du thermostat).

Fidèle à l'app ACOVA Control : délai d'1 s après connexion avant toute
opération ; lecture = commande [0, obj, data] puis réponse par notification,
avec repli en lecture directe de la caractéristique Données ; accusés
d'écriture relus jusqu'à ACK_RETRIES fois.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
)

from . import const, protocol
from .agent import PairingAgentError, pairing_agent

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

# Erreurs de liaison : transitoires, une reconnexion peut suffire à les lever.
_CONNECTION_ERRORS = (BleakError, TimeoutError, OSError)


class AcovaError(Exception):
    """Erreur de communication avec le radiateur."""


class AcovaConnectionError(AcovaError):
    """Erreur de liaison BLE (transitoire) : une reconnexion peut suffire."""


class AcovaProtocolError(AcovaError):
    """Réponse hors protocole : radiateur en veille ou non appairé (bouton 2H)."""


@dataclass
class AcovaState:
    """État lu du radiateur."""

    mode: int
    comfort_temp: float
    eco_temp: float | None = None


class AcovaDevice:
    """Client BLE haut niveau pour un radiateur ACOVA."""

    def __init__(
        self,
        ble_device: BLEDevice | None,
        name: str,
        ble_device_provider: Callable[[], BLEDevice | None] | None = None,
    ) -> None:
        self._ble_device = ble_device
        self._ble_device_provider = ble_device_provider
        self._name = name
        self._lock = asyncio.Lock()
        self._client: BleakClient | None = None
        self._expected_disconnect = False
        self._notifications: asyncio.Queue[bytes] = asyncio.Queue()
        self._notify_ok = False

    # --- Gestion du lien ------------------------------------------------------

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Met à jour le BLEDevice (résolu par HA à chaque poll)."""
        self._ble_device = ble_device

    def _current_ble_device(self) -> BLEDevice:
        """Retourne le BLEDevice le plus frais (le chemin BlueZ peut changer)."""
        if self._ble_device_provider is not None:
            fresh = self._ble_device_provider()
            if fresh is not None:
                self._ble_device = fresh
        if self._ble_device is None:
            raise AcovaConnectionError(
                f"{self._name} : appareil inconnu du Bluetooth local"
            )
        return self._ble_device

    def _on_disconnect(self, _client: BleakClient) -> None:
        """Le lien est tombé de lui-même : il sera rétabli à la prochaine opération."""
        if self._expected_disconnect:
            return
        _LOGGER.info(
            "[%s] connexion BLE interrompue, reconnexion à la prochaine opération",
            self._name,
        )
        self._client = None
        self._notify_ok = False

    def _on_notify(self, _sender, data: bytearray) -> None:
        self._notifications.put_nowait(bytes(data))

    async def _connect(self) -> BleakClient:
        """Ouvre la connexion (cache de services BlueZ) et prépare les notifications."""
        ble_device = self._current_ble_device()
        self._expected_disconnect = False
        self._notifications = asyncio.Queue()
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._name,
                disconnected_callback=self._on_disconnect,
                max_attempts=const.CONNECT_MAX_ATTEMPTS,
            )
        except BleakNotFoundError as err:
            raise AcovaConnectionError(
                "radiateur introuvable (hors de portée ou Bluetooth absent)"
            ) from err
        except _CONNECTION_ERRORS as err:
            raise AcovaConnectionError(f"connexion impossible : {err}") from err
        self._client = client
        try:
            await asyncio.sleep(const.POST_CONNECT_DELAY)
            await self._start_notifications(client)
        except _CONNECTION_ERRORS as err:
            _LOGGER.debug("[%s] lien instable après connexion : %s", self._name, err)
            await self._disconnect()
            raise AcovaConnectionError(f"lien instable après connexion : {err}") from err
        return client

    async def _start_notifications(self, client: BleakClient) -> None:
        try:
            await client.start_notify(const.UUID_CHAR_DATA, self._on_notify)
        except BleakError as err:
            self._notify_ok = False
            _LOGGER.debug(
                "[%s] start_notify impossible (%s) : lectures directes",
                self._name,
                err,
            )
        else:
            self._notify_ok = True

    async def _disconnect(self) -> None:
        """Coupe proprement le lien courant (s'il est encore là)."""
        client = self._client
        self._client = None
        notify_was_ok = self._notify_ok
        self._notify_ok = False
        if client is None:
            return
        self._expected_disconnect = True
        try:
            async with asyncio.timeout(const.DISCONNECT_TIMEOUT):
                if notify_was_ok:
                    await client.stop_notify(const.UUID_CHAR_DATA)
                await client.disconnect()
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.debug("[%s] déconnexion partielle : %s", self._name, err)

    async def _ensure_connected(self) -> BleakClient:
        client = self._client
        if client is not None and client.is_connected:
            return client
        if client is not None:
            await self._disconnect()
        return await self._connect()

    # --- Exécution des opérations ----------------------------------------------

    async def _run(
        self, operation: Callable[[BleakClient], Awaitable[_T]], *, pair: bool = False
    ) -> _T:
        """Exécute une opération, avec reconnexion et reprise sur erreur de liaison.

        Une erreur de liaison déclenche une reconnexion suivie d'une nouvelle
        tentative complète. Une erreur de protocole n'est pas retentée : le
        radiateur répond, mais hors protocole (appairage/état à corriger).
        """
        async with self._lock:
            last_error: AcovaConnectionError | None = None
            for attempt in range(1, const.OPERATION_ATTEMPTS + 1):
                try:
                    return await self._attempt(operation, pair=pair)
                except AcovaConnectionError as err:
                    last_error = err
                    await self._disconnect()
                    _LOGGER.debug(
                        "[%s] tentative %s/%s échouée : %s",
                        self._name,
                        attempt,
                        const.OPERATION_ATTEMPTS,
                        err,
                    )
            raise AcovaConnectionError(
                f"{self._name} injoignable après "
                f"{const.OPERATION_ATTEMPTS} tentatives : {last_error}"
            )

    async def _attempt(
        self, operation: Callable[[BleakClient], Awaitable[_T]], *, pair: bool
    ) -> _T:
        try:
            if pair and self._client is not None:
                # L'appairage se valide sur une connexion fraîche (LED 2H).
                await self._disconnect()
            client = await self._ensure_connected()
            if pair:
                await self._pair(client)
            async with asyncio.timeout(const.OP_TIMEOUT):
                return await operation(client)
        except AcovaError:
            raise  # déjà classée : protocole ou connexion
        except PairingAgentError as err:
            raise AcovaConnectionError(f"appairage BlueZ : {err}") from err
        except BleakNotFoundError as err:
            raise AcovaConnectionError(
                "radiateur introuvable (hors de portée ou Bluetooth absent)"
            ) from err
        except _CONNECTION_ERRORS as err:
            raise AcovaConnectionError(f"BLE : {err}") from err

    async def _pair(self, client: BleakClient) -> None:
        _LOGGER.info(
            "[%s] appairage : appuyer sur le bouton 2H pendant que la LED clignote",
            self._name,
        )
        async with pairing_agent(self._current_ble_device().address):
            await client.pair()

    # --- Réception des réponses -----------------------------------------------

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

    async def _read_until(
        self, client: BleakClient, object_id: int, data_id: int
    ) -> bytes:
        """Relit la caractéristique Données jusqu'à obtenir l'écho attendu."""
        raw = b""
        for attempt in range(1, const.ACK_RETRIES + 1):
            raw = bytes(await client.read_gatt_char(const.UUID_CHAR_DATA))
            if len(raw) >= 3 and raw[0] == object_id and raw[1] == data_id:
                return raw
            _LOGGER.debug(
                "[%s] attente écho (%s,%s), lecture %s : %s",
                self._name,
                object_id,
                data_id,
                attempt,
                raw.hex(),
            )
            await asyncio.sleep(const.ACK_RETRY_DELAY)
        if not any(raw):
            raise AcovaProtocolError(
                f"réponse vide ({object_id},{data_id}) : radiateur en veille "
                "ou non appairé (bouton 2H) ?"
            )
        raise AcovaProtocolError(
            f"pas d'écho ({object_id},{data_id}) après {const.ACK_RETRIES} lectures"
        )

    # --- Primitives lecture/écriture ------------------------------------------

    async def _read_dp(self, client: BleakClient, dp: tuple[int, int]) -> bytes:
        object_id, data_id = dp
        await client.write_gatt_char(
            const.UUID_CHAR_CMD,
            protocol.build_read_request(object_id, data_id),
            response=True,
        )
        raw = await self._wait_notification(object_id, data_id)
        if raw is None:
            _LOGGER.debug(
                "[%s] (%s,%s) sans notification : lecture directe",
                self._name,
                object_id,
                data_id,
            )
            raw = await self._read_until(client, object_id, data_id)
        elif protocol.needs_followup_read(raw):
            raw = await self._read_until(client, object_id, data_id)
        _LOGGER.debug("[%s] (%s,%s) = %s", self._name, object_id, data_id, raw.hex())
        return protocol.parse_notification(raw)[2]

    async def _write_dp(
        self, client: BleakClient, dp: tuple[int, int], value: bytes
    ) -> None:
        object_id, data_id = dp
        await client.write_gatt_char(
            const.UUID_CHAR_DATA,
            protocol.build_write_payload(object_id, data_id, value),
            response=True,
        )
        await self._read_until(client, object_id, data_id)
        await client.write_gatt_char(
            const.UUID_CHAR_CMD,
            protocol.build_write_commit(object_id, data_id),
            response=True,
        )
        await self._read_until(client, 0, 0)

    @staticmethod
    def _first_byte(value: bytes, dp: tuple[int, int]) -> int:
        if not value:
            raise AcovaProtocolError(f"valeur vide pour ({dp[0]},{dp[1]})")
        return value[0]

    # --- API métier ------------------------------------------------------------

    async def _read_state(self, client: BleakClient) -> AcovaState:
        mode = self._first_byte(
            await self._read_dp(client, const.DP_THERMOSTAT_MODE),
            const.DP_THERMOSTAT_MODE,
        )
        comfo = self._first_byte(
            await self._read_dp(client, const.DP_COMFO_SETPOINT),
            const.DP_COMFO_SETPOINT,
        )
        try:
            eco_temp = protocol.byte_to_temp(
                self._first_byte(
                    await self._read_dp(client, const.DP_ECO_SETPOINT),
                    const.DP_ECO_SETPOINT,
                )
            )
        except AcovaProtocolError:
            _LOGGER.debug("[%s] consigne éco illisible", self._name)
            eco_temp = None
        return AcovaState(
            mode=mode, comfort_temp=protocol.byte_to_temp(comfo), eco_temp=eco_temp
        )

    async def async_read_state(self) -> AcovaState:
        return await self._run(self._read_state)

    async def async_pair(self) -> AcovaState:
        """Appaire le radiateur (validation bouton 2H) puis vérifie par une lecture."""
        return await self._run(self._read_state, pair=True)

    async def async_set_mode(self, mode: int) -> None:
        await self._run(
            lambda client: self._write_dp(client, const.DP_THERMOSTAT_MODE, bytes([mode]))
        )

    async def async_set_heating(self, on: bool, write_setpoint: bool = True) -> None:
        """Chauffe à fond (mode Jour, consigne max) ou hors-gel.

        La consigne max n'est réécrite que si nécessaire (`write_setpoint`) afin de
        limiter les écritures dans la mémoire du radiateur. Jamais la veille : elle
        coupe le Bluetooth du radiateur.
        """

        async def _apply(client: BleakClient) -> None:
            if not on:
                await self._write_dp(
                    client, const.DP_THERMOSTAT_MODE, bytes([const.MODE_FROST])
                )
                return
            if write_setpoint:
                await self._write_dp(
                    client,
                    const.DP_COMFO_SETPOINT,
                    bytes([protocol.temp_to_byte(const.TEMP_MAX)]),
                )
            await self._write_dp(
                client, const.DP_THERMOSTAT_MODE, bytes([const.MODE_DAY])
            )

        await self._run(_apply)

    async def async_set_comfort_temp(self, celsius: float) -> None:
        value = bytes([protocol.temp_to_byte(celsius)])
        await self._run(
            lambda client: self._write_dp(client, const.DP_COMFO_SETPOINT, value)
        )

    async def async_stop(self) -> None:
        """Déconnexion propre (déchargement de l'entrée HA, fin d'appairage…)."""
        async with self._lock:
            await self._disconnect()
