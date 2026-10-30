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

PLATFORMS = ["switch"]


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Configure une entrée (un radiateur)."""
    from homeassistant.components import bluetooth
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from homeassistant.core import Event
    from homeassistant.exceptions import ConfigEntryNotReady

    from .coordinator import AcovaCoordinator

    address: str = entry.data["address"]
    if bluetooth.async_ble_device_from_address(hass, address, connectable=True) is None:
        # Le premier refresh échouerait de toute façon, avec un message moins clair.
        raise ConfigEntryNotReady(f"Radiateur ACOVA {address} hors de portée Bluetooth")

    coordinator = AcovaCoordinator(hass, entry, address)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    async def _async_stop(_event: "Event") -> None:
        # Les entrées ne sont pas déchargées à l'arrêt de HA : libérer le lien
        # pour que le radiateur reste joignable (app ACOVA Control, redémarrage).
        await coordinator.device.async_stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Décharge une entrée et libère la connexion BLE du radiateur."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.device.async_stop()
    return unload_ok
