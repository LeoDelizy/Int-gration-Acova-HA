"""Tests de l'agent d'appairage BlueZ (logique d'acceptation, sans bus D-Bus)."""
import os
import sys

import pytest
from dbus_fast.errors import DBusError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from acova_ble import agent  # noqa: E402

TARGET = "D2:C9:8E:95:2D:22"
TARGET_PATH = "/org/bluez/hci0/dev_D2_C9_8E_95_2D_22"
OTHER_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"


@pytest.fixture
def pairing_agent():
    return agent.PairingAgent(TARGET)


def test_accepts_confirmation_for_target(pairing_agent):
    pairing_agent.RequestConfirmation(TARGET_PATH, 123456)
    pairing_agent.RequestAuthorization(TARGET_PATH)


def test_target_match_ignores_case(pairing_agent):
    pairing_agent.RequestConfirmation(TARGET_PATH.lower(), 1)


def test_rejects_other_devices(pairing_agent):
    with pytest.raises(DBusError):
        pairing_agent.RequestConfirmation(OTHER_PATH, 123456)
    with pytest.raises(DBusError):
        pairing_agent.RequestAuthorization(OTHER_PATH)


def test_rejects_pin_and_passkey_requests(pairing_agent):
    with pytest.raises(DBusError):
        pairing_agent.RequestPinCode(TARGET_PATH)
    with pytest.raises(DBusError):
        pairing_agent.RequestPasskey(TARGET_PATH)


def test_device_path_conversion():
    assert agent.device_path_suffix(TARGET) == "dev_D2_C9_8E_95_2D_22"
