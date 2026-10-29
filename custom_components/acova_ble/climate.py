"""Entité climate pour un radiateur ACOVA."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
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
    async_add_entities([AcovaClimate(coordinator, entry)])


class AcovaClimate(CoordinatorEntity[AcovaCoordinator], ClimateEntity):
    """Radiateur ACOVA exposé en climate."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_preset_modes = [const.PRESET_COMFORT, const.PRESET_ECO, const.PRESET_AWAY]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_min_temp = const.TEMP_MIN
    _attr_max_temp = const.TEMP_MAX
    _attr_target_temperature_step = const.TEMP_STEP

    def __init__(self, coordinator: AcovaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entry.unique_id or entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(const.DOMAIN, self._attr_unique_id)},
            name=entry.title,
            manufacturer="ACOVA",
        )

    @property
    def _mode(self) -> int | None:
        return self.coordinator.data.mode if self.coordinator.data else None

    @property
    def hvac_mode(self) -> HVACMode | None:
        mode = self._mode
        if mode is None:
            return None
        if mode == const.MODE_STANDBY:
            return HVACMode.OFF
        if mode == const.MODE_AUTO:
            return HVACMode.AUTO
        return HVACMode.HEAT

    @property
    def preset_mode(self) -> str | None:
        mode = self._mode
        if mode is None:
            return None
        return const.MODE_TO_PRESET.get(mode, const.PRESET_COMFORT)

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.comfort_temp if self.coordinator.data else None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            mode = const.MODE_STANDBY
        elif hvac_mode == HVACMode.AUTO:
            mode = const.MODE_AUTO
        else:  # HEAT : reprend le preset courant, défaut Confort
            mode = const.PRESET_TO_MODE.get(self.preset_mode, const.MODE_DAY)
        await self.coordinator.device.async_set_mode(mode)
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.coordinator.device.async_set_mode(const.PRESET_TO_MODE[preset_mode])
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.device.async_set_comfort_temp(temperature)
        await self.coordinator.async_request_refresh()
