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

@pytest.mark.parametrize("celsius,byte", [(20.0, 40), (21.5, 43), (7.0, 14), (28.0, 56)])
def test_temp_to_byte(celsius, byte):
    assert protocol.temp_to_byte(celsius) == byte


@pytest.mark.parametrize("byte,celsius", [(40, 20.0), (43, 21.5), (14, 7.0)])
def test_byte_to_temp(byte, celsius):
    assert protocol.byte_to_temp(byte) == celsius


def test_temp_to_byte_roundtrip():
    for c in [7.0, 10.5, 19.0, 20.5, 25.0, 28.0]:
        assert protocol.byte_to_temp(protocol.temp_to_byte(c)) == c


def test_temp_to_byte_clamped_to_bounds():
    assert protocol.temp_to_byte(2.0) == int(const.TEMP_MIN * 2)
    assert protocol.temp_to_byte(99.0) == int(const.TEMP_MAX * 2)


# --- Consignes du switch ----------------------------------------------------

def test_heat_temps_are_encodable_and_ordered():
    assert const.TEMP_MIN <= const.HEAT_OFF_TEMP < const.HEAT_ON_TEMP <= const.TEMP_MAX
    assert protocol.temp_to_byte(const.HEAT_ON_TEMP) == 42
    assert protocol.temp_to_byte(const.HEAT_OFF_TEMP) == 30


def test_temp_max_matches_hardware():
    # Relevé sur TEMPO 3 : une consigne de 30 °C est plafonnée à 28 °C par le radiateur.
    assert const.TEMP_MAX == 28.0
