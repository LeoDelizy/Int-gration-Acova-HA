"""Config flow : découverte Bluetooth des radiateurs ACOVA + confirmation."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, UUID_SERVICE_CMD


class AcovaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gère l'ajout d'un radiateur ACOVA."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}  # address -> name
        self._address: str | None = None
        self._name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Appareil détecté via annonce BLE contenant le service ACOVA."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirmation d'ajout d'un appareil découvert."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name, data={"address": self._address}
            )
        return self.async_show_form(
            step_id="confirm", description_placeholders={"name": self._name}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sélection manuelle parmi les appareils ACOVA détectés."""
        if user_input is not None:
            address = user_input["address"]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered[address], data={"address": address}
            )

        current = self._async_current_ids()
        for info in async_discovered_service_info(self.hass):
            if info.address in current:
                continue
            if UUID_SERVICE_CMD in info.service_uuids:
                self._discovered[info.address] = info.name or info.address

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("address"): vol.In(self._discovered)}
            ),
        )
