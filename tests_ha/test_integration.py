"""Chargement de l'intégration dans un vrai Home Assistant, radiateur simulé."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.acova_ble import const
from custom_components.acova_ble.device import AcovaState

ADDRESS = "D2:C9:8E:95:2D:22"


@pytest.fixture
def mock_device():
    with (
        patch("custom_components.acova_ble.coordinator.AcovaDevice") as cls,
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch("homeassistant.components.bluetooth.async_setup", return_value=True),
    ):
        device = cls.return_value
        device.async_read_state = AsyncMock(
            return_value=AcovaState(mode=const.MODE_DAY, comfort_temp=const.HEAT_OFF_TEMP)
        )
        device.async_set_heating = AsyncMock()
        device.async_stop = AsyncMock()
        yield device


async def test_setup_switch_stop_and_unload(hass, mock_device):
    entry = MockConfigEntry(
        domain=const.DOMAIN, unique_id=ADDRESS, data={"address": ADDRESS}, title="TEMPO 3"
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get("climate.tempo_3") is None
    assert hass.states.get("switch.tempo_3_chauffe").state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.tempo_3_chauffe"}, blocking=True
    )
    mock_device.async_set_heating.assert_awaited_with(
        True, AcovaState(mode=const.MODE_DAY, comfort_temp=const.HEAT_OFF_TEMP)
    )

    # Arrêt de HA : le lien BLE est libéré (les entrées ne sont pas déchargées).
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert mock_device.async_stop.await_count == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert mock_device.async_stop.await_count == 2


async def test_user_flow_pairs_then_creates_entry(hass):
    info = MagicMock(address=ADDRESS)
    info.name = "TEMPO 3"
    with (
        patch(
            "custom_components.acova_ble.config_flow.async_discovered_service_info",
            return_value=[info],
        ),
        patch(
            "custom_components.acova_ble.config_flow.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch("custom_components.acova_ble.config_flow.AcovaDevice") as cls,
        patch("homeassistant.components.bluetooth.async_setup", return_value=True),
        patch("custom_components.acova_ble.async_setup_entry", return_value=True),
    ):
        cls.return_value.async_pair = AsyncMock()
        cls.return_value.async_stop = AsyncMock()
        result = await hass.config_entries.flow.async_init(
            const.DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"address": ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"TEMPO 3 ({ADDRESS})"
    assert result["data"] == {"address": ADDRESS}
    cls.return_value.async_stop.assert_awaited_once()
