"""Config flow : découverte Bluetooth des radiateurs ACOVA + ajout manuel.

Les radiateurs ACOVA (module Toumi) n'annoncent PAS leur UUID de service 128 bits
dans l'advertising : ils ne sont donc pas auto-découvrables par service_uuid. Le pas
« user » liste par conséquent tous les appareils BLE connectables pour sélection.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class AcovaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gère l'ajout d'un radiateur ACOVA."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}  # address -> "name (address)"
        self._address: str | None = None
        self._name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Appareil détecté via annonce BLE contenant le service ACOVA (si annoncé)."""
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
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm", description_placeholders={"name": self._name}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sélection parmi les appareils BLE connectables détectés."""
        if user_input is not None:
            address = user_input["address"]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered.get(address, address),
                data={"address": address},
            )

        current = self._async_current_ids()
        self._discovered = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in current:
                continue
            label = f"{info.name} ({info.address})" if info.name else info.address
            self._discovered[info.address] = label

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("address"): vol.In(self._discovered)}
            ),
        )
