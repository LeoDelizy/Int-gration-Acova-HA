# Intégration Home Assistant — ACOVA BLE

Pilotage **local Bluetooth (BLE)** des radiateurs ACOVA depuis Home Assistant, sans cloud.
Issu du reverse engineering de l'app *ACOVA Control* (voir `docs/acova-ble-protocol.md`).

> ⚠️ Protocole reconstruit par **analyse statique** — à valider sur matériel réel.
> Projet non affilié à ACOVA.

## Fonctionnalités
- Une entité `switch` **Chauffe** par radiateur, rien d'autre :
  - ON = consigne Confort **21 °C**, OFF = consigne Confort **15 °C**, radiateur en mode Jour.
  - Pensée pour un VTherm *over_switch* (ex. SmartPI) qui régule avec sa propre sonde ;
    l'inertie du radiateur lisse les cycles. Prévoir des cycles longs (15–20 min) :
    chaque basculement est une écriture dans le radiateur.
  - Le thermostat interne borne toujours la chauffe à 21 °C, même si HA perd le lien.
  - Un réglage manuel au thermostat est vu comme OFF ; le prochain ON le réécrit.
  - La veille du radiateur n'est jamais commandée : elle coupe son Bluetooth jusqu'à un
    réveil manuel au thermostat.
- Connexion BLE **par sessions courtes, comme l'app ACOVA Control** : connexion, opération,
  puis déconnexion. Une coupure de lien en cours d'opération relance une session complète.
- Ajout par sélection de l'appareil Bluetooth (ex. « TEMPO 3 (D2:C9:…) »).
  Les radiateurs ACOVA n'annoncent pas leur UUID de service : l'auto-découverte se fait
  sur le nom annoncé (`TEMPO*`, seul modèle vérifié) ; les autres modèles s'ajoutent à la main.

Hors périmètre : entité climate, programme hebdomadaire, détection fenêtre, offset, température ambiante.

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
Le radiateur n'accepte qu'une connexion à la fois : si l'app ACOVA Control est connectée,
les commandes de Home Assistant échouent jusqu'à sa fermeture (HA libère le lien après
chaque opération).

**Appairage** : après validation, la LED du thermostat clignote rapidement ; appuyer sur le
bouton **2H** dans les 30 s. Sans appairage, le radiateur ignore les commandes.

## Développement
```bash
pip install pytest bleak bleak-retry-connector dbus-fast
python -m pytest tests/        # tests du protocole (purs, sans matériel)

pip install pytest-homeassistant-custom-component
python -m pytest tests_ha -o asyncio_mode=auto   # chargement dans un vrai HA (radiateur simulé)
```
Architecture : `const.py` (constantes) · `protocol.py` (trames, **pur/testé**) ·
`device.py` (BLE, sessions courtes comme l'app) ·
`coordinator.py` (poll) · `config_flow.py` (découverte) · `switch.py` (entité). Design : `docs/superpowers/specs/`.
