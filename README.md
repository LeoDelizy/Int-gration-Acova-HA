# Intégration Home Assistant — ACOVA BLE

Pilotage **local Bluetooth (BLE)** des radiateurs ACOVA depuis Home Assistant, sans cloud.
Issu du reverse engineering de l'app *ACOVA Control* (voir `docs/acova-ble-protocol.md`).

> ⚠️ Protocole reconstruit par **analyse statique** — à valider sur matériel réel.
> Projet non affilié à ACOVA.

## Fonctionnalités (v1)
- Entité `climate` par radiateur :
  - Modes : Arrêt (= hors-gel), Auto (programme), Chauffe (Confort / Éco via *preset*).
  - La veille du radiateur n'est jamais commandée : elle coupe son Bluetooth jusqu'à un
    réveil manuel au thermostat.
  - Consigne de température (Confort), pas de 0,5 °C.
- Ajout par sélection de l'appareil Bluetooth (ex. « TEMPO 3 (D2:C9:…) »).
  Les radiateurs ACOVA n'annoncent pas leur UUID de service : pas d'auto-découverte.

Hors v1 : programme hebdomadaire, détection fenêtre, offset de calibration, température ambiante.

## Prérequis
- Home Assistant avec le Bluetooth fonctionnel (HA OS recommandé).
- Le radiateur à portée BLE de l'hôte (ou d'un *Bluetooth proxy* ESPHome).

## Installation
### Manuelle
Copier `custom_components/acova_ble/` dans le dossier `config/custom_components/` de HA,
puis redémarrer Home Assistant.

### HACS (dépôt personnalisé)
HACS → dépôts personnalisés → ajouter l'URL de ce dépôt (catégorie *Integration*),
installer **ACOVA BLE**, puis redémarrer.

## Configuration
Paramètres → Appareils et services → *Ajouter une intégration* → **ACOVA BLE**,
puis choisir le radiateur dans la liste des appareils Bluetooth détectés.
Fermer l'app ACOVA Control sur le téléphone : le radiateur n'accepte qu'une connexion.

**Appairage** : après validation, la LED du thermostat clignote rapidement ; appuyer sur le
bouton **2H** dans les 30 s. Sans appairage, le radiateur ignore les commandes.

## Développement
```bash
pip install pytest bleak bleak-retry-connector
python -m pytest tests/        # tests du protocole (purs, sans matériel)
```
Architecture : `const.py` (constantes) · `protocol.py` (trames, **pur/testé**) ·
`device.py` (BLE) · `coordinator.py` (poll) · `config_flow.py` (découverte) ·
`climate.py` (entité). Design : `docs/superpowers/specs/`.
