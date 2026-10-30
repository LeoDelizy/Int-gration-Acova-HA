"""Entité switch « Chauffe » : consigne haute (on) ou basse (off), en mode Jour.

Pensée pour un VTherm de type over_switch : il régule la pièce par cycles marche/arrêt
avec sa propre sonde, l'inertie du radiateur lisse les cycles. ON = consigne Confort
HEAT_ON_TEMP, OFF = HEAT_OFF_TEMP : le thermostat interne borne toujours la chauffe,
même si le lien BLE est perdu. Jamais la veille, qui coupe le Bluetooth du radiateur.
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
        if data is None:
            return None
        # Tout autre état (réglage manuel au thermostat…) est vu comme OFF : le
        # prochain ON du VTherm réécrit la consigne et le mode attendus.
        return data.mode == const.MODE_DAY and data.comfort_temp == const.HEAT_ON_TEMP

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        await self.coordinator.async_send(
            self.coordinator.device.async_set_heating(on, self.coordinator.data)
        )
