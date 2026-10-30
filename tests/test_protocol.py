"""Tests purs du protocole BLE ACOVA (aucune dépendance HA/BLE)."""
import os
import sys

import pytest

# Rend le paquet importable sans installer Home Assistant.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from acova_ble import const, protocol  # noqa: E402


# --- Trames de transport ---------------------------------------------------

def test_build_read_request():
    assert protocol.build_read_request(116, 3) == bytes([0x00, 116, 3])


def test_build_write_commit():
    assert protocol.build_write_commit(116, 5) == bytes([0x01, 116, 5])


def test_build_write_payload_layout():
    frame = protocol.build_write_payload(116, 5, bytes([40]))
    assert len(frame) == 30
    assert frame[0] == 116          # objectId
    assert frame[1] == 5            # dataId
    assert frame[2] == 1            # longueur des données
    assert frame[3] == 40           # donnée
    assert frame[4:] == bytes(26)   # padding à zéro


def test_build_write_payload_rejects_oversize():
    with pytest.raises(ValueError):
        protocol.build_write_payload(116, 5, bytes(28))  # 28 > 30-3


# --- Parsing des notifications ---------------------------------------------

def test_parse_notification():
    raw = bytes([116, 5, 1, 40])
    assert protocol.parse_notification(raw) == (116, 5, bytes([40]))


def test_parse_notification_multibyte():
    raw = bytes([117, 3, 3, 4, 8, 28, 99, 99])  # octets au-delà de len ignorés
    assert protocol.parse_notification(raw) == (117, 3, bytes([4, 8, 28]))


def test_parse_notification_too_short():
    with pytest.raises(ValueError):
        protocol.parse_notification(bytes([116, 5]))


def test_needs_followup_read():
    assert protocol.needs_followup_read(bytes([1, 1, 18])) is True
    assert protocol.needs_followup_read(bytes([1, 1, 17])) is False


# --- Conversions température ------------------------------------------------

@pytest.mark.parametrize("celsius,byte", [(20.0, 40), (21.5, 43), (7.0, 14), (30.0, 60)])
def test_temp_to_byte(celsius, byte):
    assert protocol.temp_to_byte(celsius) == byte


@pytest.mark.parametrize("byte,celsius", [(40, 20.0), (43, 21.5), (14, 7.0)])
def test_byte_to_temp(byte, celsius):
    assert protocol.byte_to_temp(byte) == celsius


def test_temp_to_byte_roundtrip():
    for c in [7.0, 10.5, 19.0, 20.5, 25.0, 30.0]:
        assert protocol.byte_to_temp(protocol.temp_to_byte(c)) == c


def test_temp_to_byte_clamped_to_bounds():
    assert protocol.temp_to_byte(2.0) == int(const.TEMP_MIN * 2)
    assert protocol.temp_to_byte(99.0) == int(const.TEMP_MAX * 2)


# --- Mapping modes ---------------------------------------------------------

def test_preset_mode_mapping_is_bijective():
    for preset, mode in const.PRESET_TO_MODE.items():
        assert const.MODE_TO_PRESET[mode] == preset


# --- Correspondance climate HA <-> mode radiateur ---------------------------

@pytest.mark.parametrize("mode,hvac", [
    (const.MODE_STANDBY, "off"),
    (const.MODE_FROST, "off"),
    (const.MODE_NIGHT, "heat"),
    (const.MODE_DAY, "heat"),
    (const.MODE_USER, "heat"),
    (const.MODE_AUTO, "auto"),
])
def test_hvac_for_mode(mode, hvac):
    assert protocol.hvac_for_mode(mode) == hvac


def test_off_never_sends_standby():
    # La veille coupe le Bluetooth du radiateur : « off » doit donner le hors-gel.
    assert protocol.mode_for_hvac("off", None) == const.MODE_FROST
    assert protocol.mode_for_hvac("off", const.PRESET_COMFORT) == const.MODE_FROST


def test_auto_maps_to_auto():
    assert protocol.mode_for_hvac("auto", None) == const.MODE_AUTO


@pytest.mark.parametrize("preset,mode", [
    (const.PRESET_COMFORT, const.MODE_DAY),
    (const.PRESET_ECO, const.MODE_NIGHT),
    (None, const.MODE_DAY),
    # Depuis le hors-gel (affiché off + away), repasser en chauffe donne le Confort.
    (const.PRESET_AWAY, const.MODE_DAY),
])
def test_heat_uses_preset(preset, mode):
    assert protocol.mode_for_hvac("heat", preset) == mode


def test_no_mapping_ever_produces_standby():
    for hvac in ("off", "heat", "auto"):
        for preset in (None, *const.PRESET_TO_MODE):
            assert protocol.mode_for_hvac(hvac, preset) != const.MODE_STANDBY
