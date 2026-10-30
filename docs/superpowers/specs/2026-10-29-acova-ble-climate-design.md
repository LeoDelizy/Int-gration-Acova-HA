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
- `hvac_mode` : `off`→2 (hors-gel, jamais la veille 1 qui coupe le Bluetooth) ; `auto`→9 ;
  `heat`→selon preset (4/3, Confort par défaut). Lecture : 1 et 2 → `off`.
- `preset_mode` : `comfort`→4, `eco`→3, `away`→2
- `target_temperature` → consigne Confort, step 0.5, min 7 / max 28 (relevé : 30 plafonné à 28)
- `switch` Chauffe : ON = consigne 28 (si différente) puis mode Jour, OFF = hors-gel ; une session BLE
- `current_temperature` : non exposé en v1 (aucun datapoint de température ambiante trouvé) — point ouvert

## Protocole de transport (rappel)
- **Lecture** : write `[0x00, obj, data]` sur caract. Commande → notification `[obj, data, len, …val]`
  sur caract. Données (repli : lecture directe) ; si `len > 17`, relire la caract. Données.
- **Écriture** : write payload 30 o `[obj, data, len, …val, 0…]` sur caract. Données (avec réponse)
  → relecture ack → write `[0x01, obj, data]` sur caract. Commande → ack `[0x00, 0x00]`.
  On écrit uniquement le datapoint visé (pas de synchro horloge).

## Flux
- Ajout manuel : config_flow liste les appareils BLE connectables (l'advertising ACOVA
  ne contient pas l'UUID de service — vérifié sur TEMPO 3).
- À la validation, le flow appaire le radiateur (`client.pair()`, confirmé par le bouton 2H)
  puis vérifie par une lecture d'état ; erreur `pairing_failed` sinon.
- Appairage encadré par un agent BlueZ temporaire (`agent.py`) : sans agent, BlueZ refuse la
  confirmation demandée par le radiateur.
- Coordinator : poll ~5 min, connexion à la demande (connect → read → disconnect).
- Commande : entité → `device.set_*` → `coordinator.async_request_refresh()`.

## Robustesse
- `bleak-retry-connector.establish_connection` ; délai 1 s après connexion (comme l'app).
- Lecture : notification attendue 3 s, sinon lecture directe de la caract. Données.
- Accusés : relecture de la caract. Données jusqu'à 10 fois (retry(10) de l'app).
- Erreurs Bleak traduites en `AcovaError` → `UpdateFailed` / `HomeAssistantError`.
- Entité `unavailable` si injoignable ; reprise au poll/annonce suivant.

## Tests
- TDD `protocol.py` : round-trip °C↔octet, bornes/clamp, mapping modes, layout payload 30 o,
  parsing notification (dont cas `len > 17`), requêtes lecture/commit.
- `device.py` avec un faux client GATT : notification, repli lecture directe, échec de
  `start_notify`, relecture des accusés, erreurs Bleak traduites (requiert `bleak`, pas HA).

## Points ouverts (validation matériel)
Température ambiante, bornes min/max réelles, effet de l'écriture de mode, nécessité relecture
après notification. Valeurs issues d'analyse statique — à confirmer par essais/sniff BLE.
