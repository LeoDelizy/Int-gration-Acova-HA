# Intégration Home Assistant ACOVA BLE — design v1

Composant personnalisé `acova_ble` : pilotage **local BLE** des radiateurs ACOVA depuis
Home Assistant (cible HA OS). Protocole : voir `docs/acova-ble-protocol.md`.

## Portée v1
Entité `climate` : modes (Veille/Hors-gel/Éco/Confort/Auto) + consigne Confort.
Hors périmètre v1 : programme hebdomadaire, détection fenêtre, offset, horloge.

## Modules
```
custom_components/acova_ble/
  const.py         # DOMAIN, UUIDs, datapoints, modes, bornes
  protocol.py      # PUR : trames + conversions (ni BLE ni HA) — testé en TDD
  device.py        # orchestration BLE (BleakClient) au-dessus de protocol
  coordinator.py   # DataUpdateCoordinator : connexion à la demande + poll
  config_flow.py   # découverte bluetooth + confirmation
  climate.py       # entité AcovaClimate
  __init__.py      # setup/unload de l'entrée
  manifest.json, strings.json, translations/{en,fr}.json
tests/test_protocol.py  # tests purs, sans matériel
```

## GATT
- Service Commande `03366e80-cf3a-11e1-9ab4-0002a5d5c51b`, caract. `350a1b80-cf4b-11e1-ac36-0002a5d5c51b`
- Service Données  `03366e80-cf3a-11e1-9ab5-0002a5d5c51b`, caract. `350a1b80-cf4b-11e1-ac37-0002a5d5c51b`

## Datapoints utilisés (objectId, dataId)
- ThermostatMode (116, 3) — 1 octet
- ThermostatComfoSetPoint (116, 5) — 1 octet ; `°C = octet/2`, `octet = round(2·°C)`
- ThermostatEcoSetPoint (116, 4) — lu pour info

## Modes (octet ThermostatMode)
1=Standby, 2=FrostProtection, 3=Night, 4=Day, 8=User, 9=Auto.

## Mapping climate
- `hvac_mode` : `off`→1 ; `auto`→9 ; `heat`→selon preset (4/3/2)
- `preset_mode` : `comfort`→4, `eco`→3, `away`→2
- `target_temperature` → consigne Confort, step 0.5, min 7 / max 30 (à confirmer matériel)
- `current_temperature` : non exposé en v1 (aucun datapoint de température ambiante trouvé) — point ouvert

## Protocole de transport (rappel)
- **Lecture** : write `[0x00, obj, data]` sur caract. Commande → notification `[obj, data, len, …val]`
  sur caract. Données ; si `len > 17`, relire la caract. Données explicitement.
- **Écriture** : write payload 30 o `[obj, data, len, …val, 0…]` sur caract. Données (avec réponse)
  → relecture ack → write `[0x01, obj, data]` sur caract. Commande → ack `[0x00, 0x00]`.
  On écrit uniquement le datapoint visé (pas de synchro horloge).

## Flux
- Découverte via annonce BLE contenant l'UUID de service → config_flow → confirmation.
- Coordinator : poll ~5 min, connexion à la demande (connect → read → disconnect).
- Commande : entité → `device.set_*` → `coordinator.async_request_refresh()`.

## Robustesse
- `bleak-retry-connector.establish_connection` ; timeout notification 8 s ; vérif écho obj/data.
- Entité `unavailable` si injoignable ; reprise au poll/annonce suivant.

## Tests
- TDD `protocol.py` : round-trip °C↔octet, bornes/clamp, mapping modes, layout payload 30 o,
  parsing notification (dont cas `len > 17`), requêtes lecture/commit.
- Pas de dépendance HA/BLE dans ces tests.

## Points ouverts (validation matériel)
Température ambiante, bornes min/max réelles, effet de l'écriture de mode, nécessité relecture
après notification. Valeurs issues d'analyse statique — à confirmer par essais/sniff BLE.
