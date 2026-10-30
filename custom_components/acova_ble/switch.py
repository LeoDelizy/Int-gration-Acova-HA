"""Entité switch « Chauffe » : chauffe à fond (on) ou hors-gel (off).

Pensée pour un VTherm de type over_switch : il régule la pièce par cycles marche/arrêt
avec sa propre sonde. ON = mode Jour à la consigne max (le thermostat interne ne coupe
jamais) ; OFF = hors-gel (jamais la veille, qui coupe le Bluetooth du radiateur).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import const
from .coordinator import AcovaCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AcovaCoordinator = hass.data[const.DOMAIN][entry.entry_id]
    async_add_entities([AcovaHeatingSwitch(coordinator, entry)])


class AcovaHeatingSwitch(CoordinatorEntity[AcovaCoordinator], SwitchEntity):
    """Chauffe à fond / hors-gel."""

    _attr_has_entity_name = True
    _attr_name = "Chauffe"
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: AcovaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        base_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base_id}_heating"
        self._attr_device_info = DeviceInfo(
            identifiers={(const.DOMAIN, base_id)},
            name=entry.title,
            manufacturer="ACOVA",
        )

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return data.mode == const.MODE_DAY if data else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        data = self.coordinator.data
        write_setpoint = data is None or data.comfort_temp != const.TEMP_MAX
        await self.coordinator.async_send(
            self.coordinator.device.async_set_heating(True, write_setpoint=write_setpoint)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send(self.coordinator.device.async_set_heating(False))
