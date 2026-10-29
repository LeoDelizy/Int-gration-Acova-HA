"""Intégration Home Assistant ACOVA BLE (pilotage local des radiateurs).

Les imports Home Assistant/Bluetooth sont faits à l'intérieur des fonctions afin que
les modules purs (`const`, `protocol`) restent importables sans HA (tests).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS = ["climate"]


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Configure une entrée (un radiateur)."""
    from homeassistant.components import bluetooth
    from homeassistant.exceptions import ConfigEntryNotReady

    from .coordinator import AcovaCoordinator

    address: str = entry.data["address"]
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(f"Radiateur ACOVA {address} introuvable")

    coordinator = AcovaCoordinator(hass, entry, address)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Décharge une entrée."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
