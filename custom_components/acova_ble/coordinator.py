"""Coordinator : rafraîchit l'état du radiateur sur la connexion permanente."""
from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import const
from .device import (
    AcovaConnectionError,
    AcovaDevice,
    AcovaError,
    AcovaProtocolError,
    AcovaState,
)

_LOGGER = logging.getLogger(__name__)


class AcovaCoordinator(DataUpdateCoordinator[AcovaState]):
    """Coordonne les lectures d'état et donne accès au device pour les commandes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{const.DOMAIN}_{address}",
            update_interval=timedelta(seconds=const.POLL_INTERVAL),
        )
        self.address = address
        self.entry = entry
        # Le BLEDevice est résolu auprès de HA à chaque (re)connexion : le chemin
        # BlueZ peut changer (redémarrage de l'adaptateur, bascule de proxy…).
        self.device = AcovaDevice(
            None,
            entry.title or address,
            ble_device_provider=lambda: bluetooth.async_ble_device_from_address(
                hass, address, connectable=True
            ),
        )

    async def _async_update_data(self) -> AcovaState:
        try:
            return await self.device.async_read_state()
        except AcovaConnectionError as err:
            raise UpdateFailed(f"connexion BLE perdue : {err}") from err
        except AcovaProtocolError as err:
            raise UpdateFailed(str(err)) from err

    async def async_send(self, command: Awaitable[None]) -> None:
        """Envoie une commande au radiateur puis rafraîchit l'état."""
        try:
            await command
        except AcovaError as err:
            raise HomeAssistantError(f"Échec de la commande ACOVA : {err}") from err
        await self.async_request_refresh()
