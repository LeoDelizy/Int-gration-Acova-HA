"""Constantes de l'intégration ACOVA BLE (module pur, sans dépendance HA)."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "acova_ble"

# --- UUIDs GATT (reverse engineering ACOVA Control 3.4.1) ------------------
UUID_SERVICE_CMD: Final = "03366e80-cf3a-11e1-9ab4-0002a5d5c51b"
UUID_CHAR_CMD: Final = "350a1b80-cf4b-11e1-ac36-0002a5d5c51b"
UUID_SERVICE_DATA: Final = "03366e80-cf3a-11e1-9ab5-0002a5d5c51b"
UUID_CHAR_DATA: Final = "350a1b80-cf4b-11e1-ac37-0002a5d5c51b"

# --- Datapoints (objectId, dataId) -----------------------------------------
DP_THERMOSTAT_MODE: Final = (116, 3)
DP_ECO_SETPOINT: Final = (116, 4)
DP_COMFO_SETPOINT: Final = (116, 5)
DP_OFFSET: Final = (116, 6)

# --- Modes (valeur de l'octet ThermostatMode) ------------------------------
MODE_STANDBY: Final = 1
MODE_FROST: Final = 2
MODE_NIGHT: Final = 3
MODE_DAY: Final = 4
MODE_USER: Final = 8
MODE_AUTO: Final = 9

# --- Mapping preset HA <-> mode (chauffe manuelle) -------------------------
PRESET_COMFORT: Final = "comfort"
PRESET_ECO: Final = "eco"
PRESET_AWAY: Final = "away"

PRESET_TO_MODE: Final = {
    PRESET_COMFORT: MODE_DAY,
    PRESET_ECO: MODE_NIGHT,
    PRESET_AWAY: MODE_FROST,
}
MODE_TO_PRESET: Final = {mode: preset for preset, mode in PRESET_TO_MODE.items()}

# --- Bornes de consigne -----------------------------------------------------
TEMP_MIN: Final = 7.0
TEMP_MAX: Final = 28.0               # relevé sur TEMPO 3 : 30 °C est plafonné à 28 °C
TEMP_STEP: Final = 0.5

# --- Liaison BLE ------------------------------------------------------------
POST_CONNECT_DELAY: Final = 1.0      # s, l'app attend 1 s après connexion
CONNECT_MAX_ATTEMPTS: Final = 4       # essais de connexion par establish_connection
OPERATION_ATTEMPTS: Final = 2        # exécutions d'une opération (reconnexion comprise)
OP_TIMEOUT: Final = 25.0              # s, borne globale d'une opération GATT
DISCONNECT_TIMEOUT: Final = 5.0      # s, borne de la déconnexion propre

# --- Protocole ---------------------------------------------------------------
NOTIFY_WAIT: Final = 3.0             # s, attente notification avant repli en lecture directe
ACK_RETRIES: Final = 10              # relectures de la caract. Données (retry(10) de l'app)
ACK_RETRY_DELAY: Final = 0.2         # s entre deux relectures
PAYLOAD_SIZE: Final = 30
INLINE_VALUE_MAX: Final = 17         # au-delà : relecture explicite requise

# --- Divers -------------------------------------------------------------------
POLL_INTERVAL: Final = 60            # s, rafraîchissement d'état (lien permanent : peu coûteux)
OP_READ: Final = 0x00
OP_WRITE: Final = 0x01
