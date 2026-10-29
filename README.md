# Intégration Home Assistant — ACOVA BLE

Pilotage **local Bluetooth (BLE)** des radiateurs ACOVA depuis Home Assistant, sans cloud.
Issu du reverse engineering de l'app *ACOVA Control* (voir `docs/acova-ble-protocol.md`).

> ⚠️ Protocole reconstruit par **analyse statique** — à valider sur matériel réel.
> Projet non affilié à ACOVA.

## Fonctionnalités (v1)
- Entité `climate` par radiateur :
  - Modes : Arrêt (Veille), Auto (programme), Chauffe (Confort / Éco / Hors-gel via *preset*).
  - Consigne de température (Confort), pas de 0,5 °C.
- Découverte automatique par Bluetooth (aucune adresse à saisir).

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
Paramètres → Appareils et services → le radiateur détecté apparaît automatiquement
(*Découvert*). Sinon : *Ajouter une intégration* → **ACOVA BLE**.

## Développement
```bash
pip install pytest
python -m pytest tests/        # tests du protocole (purs, sans matériel)
```
Architecture : `const.py` (constantes) · `protocol.py` (trames, **pur/testé**) ·
`device.py` (BLE) · `coordinator.py` (poll) · `config_flow.py` (découverte) ·
`climate.py` (entité). Design : `docs/superpowers/specs/`.
