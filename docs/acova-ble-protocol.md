# Protocole BLE ACOVA Control — reverse engineering

Reverse engineering de l'application **ACOVA Control v3.4.1** (`fr.acova.toumiprogram`,
fichier `ACOVA+Control_3.4.1_APKPure.xapk`) en vue d'une intégration Home Assistant
**100 % locale**. Objectif : interopérabilité avec du matériel acquis légitimement.

## 1. Architecture de l'application

| Élément | Valeur |
|---|---|
| Package | `fr.acova.toumiprogram` |
| Version | 3.4.1 (versionCode 3040107) |
| Type | Application **hybride Ionic/Angular + Cordova** (logique métier en JavaScript, `assets/www/*.js`) |
| Pilotage radiateurs | **BLE / GATT local** via `cordova-plugin-ble-central` |
| Cloud | **Aucun backend de pilotage.** Seuls Firebase (push/analytics) et Crashlytics sont présents |
| Permissions clés | `BLUETOOTH*`, `ACCESS_FINE/COARSE_LOCATION`, `INTERNET` |

**Conséquence** : le contrôle se fait entièrement en Bluetooth Low Energy, en direct
entre le téléphone et le radiateur. Une intégration Home Assistant locale (ESPHome BLE
proxy ou adaptateur BLE sur l'hôte) est donc réalisable sans cloud.

La logique BLE est concentrée dans le bundle `assets/www/4496.*.js`.

## 2. Services et caractéristiques GATT

Deux services propriétaires (base vendeur `…-0002a5d5c51b`) :

| Rôle | Service UUID | Caractéristique UUID |
|---|---|---|
| **Commande** (contrôle) | `03366e80-cf3a-11e1-9ab4-0002a5d5c51b` | `350a1b80-cf4b-11e1-ac36-0002a5d5c51b` |
| **Données** (payload + notifications) | `03366e80-cf3a-11e1-9ab5-0002a5d5c51b` | `350a1b80-cf4b-11e1-ac37-0002a5d5c51b` |

- Le **scan** est non filtré (`startScan([])`) : l'appli liste tous les périphériques BLE.
  **Vérifié sur matériel** (TEMPO 3) : l'advertising ne contient **pas** l'UUID de service,
  seulement le nom (`TEMPO 3`). L'identification se fait par nom/adresse.
- **Propriétés GATT relevées sur un TEMPO 3** : caract. Commande `…ac36` = `write` ;
  caract. Données `…ac37` = `read`, `write`, `notify`.
- À la connexion, l'appli **attend 1 s** (`delayWhen(timer(1000))`) puis active les
  **notifications** sur `Service Données / Car. Données`. Pas de MTU ni de bonding explicite.

## 3. Modèle d'adressage : `(objectId, dataId)`

Chaque donnée est adressée par un couple d'octets `(objectId, dataId)`.

| objectId | dataId | Nom | Description |
|---|---|---|---|
| 100 | 1 | FactoryProductFWVersionLowLevel | Version firmware produit (octet faible) |
| 100 | 2 | FactoryProductFWVersionHighLevel | Version firmware produit (octet fort) |
| 100 | 3 | FactoryBleFWVersionLowLevel | Version firmware BLE (octet faible) |
| 100 | 4 | FactoryBleFWVersionHighLevel | Version firmware BLE (octet fort) |
| 113 | 1 | OpenWindowStatus | État détection fenêtre ouverte (lecture) |
| 113 | 2 | OpenWindowControl | Activation détection fenêtre ouverte (écriture) |
| 115 | 1 | CalendarStatus | État horloge |
| 115 | 2 | CalendarControl | Commande horloge (verrou/registre) |
| 115 | 3 | CalendarDayNumberWeek | Jour de la semaine (1=lundi … 7=dimanche) |
| 115 | 7 | CalendarHour | Heure |
| 115 | 8 | CalendarMinute | Minute |
| 115 | 9 | CalendarSecond | Seconde |
| 116 | 3 | ThermostatMode | **Mode de fonctionnement** (voir §5) |
| 116 | 4 | ThermostatEcoSetPoint | **Consigne Éco** (octet, voir §5) |
| 116 | 5 | ThermostatComfoSetPoint | **Consigne Confort** (octet, voir §5) |
| 116 | 6 | ThermostatOffset | Offset de calibration (Int8 signé, voir §5) |
| 117 | 1 | WeekPlanStatus | État programme hebdomadaire |
| 117 | 3..9 | WeekPlanDay1..Day7 | Programme par jour (20 octets/jour, voir §6) |

## 4. Protocole de transport

### 4.1 Lecture d'une donnée (`readData`)

1. **Requête** — écrire sur `Service Commande / Car. Commande` la trame 3 octets :
   ```
   [ 0x00, objectId, dataId ]        // octet 0 = 0 → opération LECTURE
   ```
2. **Réponse** — attendre une notification sur `Service Données / Car. Données` :
   ```
   [ objectId, dataId, length, data[0], data[1], … ]
   ```
   - Vérifier que `objectId`/`dataId` correspondent à la demande.
   - Si `length > 17` (valeur plus grande que le MTU de notification), relire la
     valeur complète par un **GATT read** explicite sur la caractéristique Données.
   - La valeur utile = `length` octets à partir de l'offset 3.

### 4.2 Écriture d'une donnée (`writeData`)

1. **Payload** — écrire sur `Service Données / Car. Données` une trame **30 octets**
   (remplie de zéros, puis) :
   ```
   [ objectId, dataId, dataLength, data[0], … data[dataLength-1], 0, 0, … ]  // 30 octets
   ```
2. **Ack payload** — relire la caractéristique Données jusqu'à obtenir l'écho
   `objectId`/`dataId` (l'app relit jusqu'à **10 fois** : `retry(10)`).
3. **Commit** — écrire sur `Service Commande / Car. Commande` la trame 3 octets :
   ```
   [ 0x01, objectId, dataId ]        // octet 0 = 1 → opération ÉCRITURE/COMMIT
   ```
4. **Ack commit** — relire la caractéristique Données jusqu'à `[ 0x00, 0x00, … ]` (10 essais).

> Note iOS/Android : sur Android l'écriture attend le statut `"OK"` entre chaque étape ;
> sur iOS l'enchaînement est direct (pas de statut intermédiaire).

### 4.3 Séquences haut niveau

- **Synchro lecture complète** : OpenWindow → Factory → Thermostat → WeekPlan.
- **Synchro écriture complète** : OpenWindow → Thermostat → Calendar (horloge remise à
  l'heure du téléphone à chaque écriture) → WeekPlan.

## 5. Encodage des valeurs thermostat (objectId 116)

| Donnée | Encodage octet → valeur | Valeur → octet |
|---|---|---|
| Consigne Confort (dataId 5) | `°C = 0.5 × octet` | `octet = 2 × °C` |
| Consigne Éco (dataId 4) | `°C = 0.5 × octet` | `octet = 2 × °C` |
| Offset calibration (dataId 6) | `°C = Int8 / 10` | `octet = 10 × °C` (signé) |

→ Résolution de consigne **0,5 °C** sur un octet non signé (ex. 20 °C ↔ `0x28` = 40 ;
21,5 °C ↔ `0x2B` = 43).

### Modes (`ThermostatMode`, objectId 116 / dataId 3)

| Octet | Mode (interne) | Signification |
|---|---|---|
| 1 | Standby | Veille / Arrêt |
| 2 | FrostProtection | Hors-gel |
| 3 | Night | Éco (température réduite) |
| 4 | Day | Confort *(valeur par défaut)* |
| 8 | User | Dérogation / consigne manuelle utilisateur |
| 9 | Auto | Programmation hebdomadaire active |

> À l'écriture du mode, l'appli positionne aussi un flag interne
> `setThermostatUpdateProgramMode(1)`.

## 6. Programme hebdomadaire (objectId 117, dataId 3..9)

Un jour = **20 octets**, codant des transitions de mode dans la journée :

```
[ mode0, startHour0, mode1, changeHour1, mode2, changeHour2, … ]
```

- Les **heures sont codées en pas de 15 min** : `heure_réelle = octet / 4`
  (à l'écriture : `octet = 4 × heure`).
- Les **modes** utilisés dans le programme : `4` = Confort (Day), toute autre valeur
  = Éco (Night).
- Le décodage s'arrête quand l'heure de changement vaut 0 ou n'est pas un entier
  (fin de liste des transitions pour la journée).

## 7. Autres fonctions

- **Détection fenêtre ouverte** (objectId 113) : activation via un couple
  set/reset (`OpenWindowSet`/`OpenWindowReset`).
- **Horloge** (objectId 115) : l'appli écrit heure/minute/seconde/jour courants, encadrés
  par une commande `CalendarControl` (verrou puis `SetNewClock`).
- **Versions firmware** (objectId 100) : produit et pile BLE, sur 2 octets chacune.

## 8. Pistes d'intégration Home Assistant

- **Transport** : `bleak` (Python) côté hôte, ou un **ESPHome Bluetooth Proxy** pour la
  portée. Pas de cloud requis.
- **Entité** : `climate` avec
  - `hvac_mode`/`preset_mode` ↔ `ThermostatMode` (mapping §5),
  - `target_temperature` ↔ consigne Confort (pas de 0,5 °C),
  - un éventuel preset Éco ↔ consigne Éco.
- **Séquence minimale pour changer une consigne** : connexion → notifications ON →
  `writeData(ThermostatComfoSetPoint, [2×°C])` (payload 30 o + commit 3 o) → attendre ack.
- **Attention** : l'écriture d'une donnée déclenche aussi, côté appli, la remise à
  l'heure de l'horloge ; à reproduire ou non selon le comportement firmware observé.

---

### Reproductibilité

```
# Extraction depuis le XAPK
unzip ACOVA+Control_3.4.1_APKPure.xapk -d xapk/
unzip xapk/fr.acova.toumiprogram.apk -d base/
# Logique BLE : base/assets/www/4496.*.js  (désobfusquer : npx js-beautify <fichier>)
```

> Toutes les valeurs ci-dessus sont issues de la lecture statique du bundle JS.
> À **valider sur matériel réel** (sniff BLE / essais) avant mise en production.
