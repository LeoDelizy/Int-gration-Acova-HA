"""Coordinator : rafraîchit l'état du radiateur par poll (connexion à la demande)."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import const
from .device import AcovaDevice, AcovaError, AcovaState

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
        ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
        self.device = AcovaDevice(ble_device, entry.title or address)

    def _refresh_ble_device(self) -> None:
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is not None:
            self.device.set_ble_device(ble_device)

    async def _async_update_data(self) -> AcovaState:
        self._refresh_ble_device()
        try:
            return await self.device.async_read_state()
        except AcovaError as err:
            raise UpdateFailed(str(err)) from err
