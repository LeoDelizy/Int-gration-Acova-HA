"""Couche protocole BLE ACOVA — pure, sans dépendance HA ni Bluetooth.

Modèle d'adressage (objectId, dataId) sur deux caractéristiques :
- Commande : trames 3 octets [op, objectId, dataId] (op 0=lecture, 1=écriture/commit)
- Données  : payload 30 octets [objectId, dataId, len, ...valeur, padding] + notifications
"""
from __future__ import annotations

from . import const


# --- Construction des trames -----------------------------------------------

def build_read_request(object_id: int, data_id: int) -> bytes:
    """Requête de lecture à écrire sur la caractéristique Commande."""
    return bytes([const.OP_READ, object_id, data_id])


def build_write_commit(object_id: int, data_id: int) -> bytes:
    """Commit d'écriture à écrire sur la caractéristique Commande."""
    return bytes([const.OP_WRITE, object_id, data_id])


def build_write_payload(object_id: int, data_id: int, value: bytes) -> bytes:
    """Payload 30 octets à écrire sur la caractéristique Données."""
    max_value = const.PAYLOAD_SIZE - 3
    if len(value) > max_value:
        raise ValueError(f"valeur trop longue: {len(value)} > {max_value}")
    frame = bytearray(const.PAYLOAD_SIZE)
    frame[0] = object_id
    frame[1] = data_id
    frame[2] = len(value)
    frame[3 : 3 + len(value)] = value
    return bytes(frame)


# --- Parsing des notifications ---------------------------------------------

def parse_notification(raw: bytes) -> tuple[int, int, bytes]:
    """Décode une notification [objectId, dataId, len, ...valeur]."""
    if len(raw) < 3:
        raise ValueError(f"notification trop courte: {len(raw)} octets")
    object_id, data_id, length = raw[0], raw[1], raw[2]
    value = bytes(raw[3 : 3 + length])
    return object_id, data_id, value


def needs_followup_read(raw: bytes) -> bool:
    """True si la valeur dépasse le MTU de notification (relecture requise)."""
    return len(raw) >= 3 and raw[2] > const.INLINE_VALUE_MAX


# --- Conversions température ------------------------------------------------

def temp_to_byte(celsius: float) -> int:
    """°C -> octet de consigne (résolution 0,5 °C), borné."""
    clamped = min(max(celsius, const.TEMP_MIN), const.TEMP_MAX)
    return round(clamped * 2)


def byte_to_temp(byte: int) -> float:
    """Octet de consigne -> °C."""
    return byte * 0.5


# --- Correspondance climate HA <-> mode radiateur ---------------------------
# La veille (MODE_STANDBY) coupe le Bluetooth du radiateur jusqu'à un réveil
# manuel : elle n'est jamais envoyée. « off » correspond au hors-gel.

def hvac_for_mode(mode: int) -> str:
    """Mode radiateur -> hvac_mode HA ("off", "heat", "auto")."""
    if mode in (const.MODE_STANDBY, const.MODE_FROST):
        return "off"
    if mode == const.MODE_AUTO:
        return "auto"
    return "heat"


def mode_for_hvac(hvac: str, preset: str | None) -> int:
    """hvac_mode HA (+ preset courant) -> mode radiateur à écrire."""
    if hvac == "off":
        return const.MODE_FROST
    if hvac == "auto":
        return const.MODE_AUTO
    mode = const.PRESET_TO_MODE.get(preset, const.MODE_DAY)
    # Repasser en chauffe depuis le hors-gel (off + away) donne le Confort.
    return const.MODE_DAY if mode == const.MODE_FROST else mode
