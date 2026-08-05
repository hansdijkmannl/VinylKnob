# De Pi als brein — fase 4

Alles om de Raspberry Pi 5 headless in te richten: het brein uit
[../brein/](../brein/) als dienst, en een luisteraar die de USB-microfoon in de
gaten houdt.

Er is **niets gewijzigd in `../brein/`**. Die code draait op je Mac en blijft
het testbed; hier staat alleen wat er nodig is om hem op een Pi te laten
draaien.

## Morgen, in volgorde

### 1. De kaart schrijven

Raspberry Pi Imager, **Raspberry Pi OS Lite (64-bit)**. Geen desktop — die kost
alleen geheugen en de Pi krijgt nooit een scherm.

Zet in het tandwielmenu meteen goed:

| | |
|---|---|
| hostnaam | `marantzknob` |
| SSH | aan, met je publieke sleutel |
| wifi | je netwerk (of gewoon ethernet) |
| gebruiker | je eigen naam, niet `pi` |

Waarom die hostnaam: dan is alles hieronder bereikbaar op
`marantzknob.local`, ook als de router een ander IP uitdeelt.

### 2. Overzetten en installeren

```bash
rsync -av --exclude '.venv' --exclude '._*' /Volumes/Opslag/Apps/MarantzKnob/ marantzknob.local:/opt/marantzknob/
```

Dan op de Pi:

```bash
ssh marantzknob.local
cd /opt/marantzknob/luxe/pi && ./installeer.sh
```

Dat script is idempotent — een tweede keer draaien mag altijd. Het zet
pakketten, een virtuele omgeving, de twee diensten, en beperkt het schrijven
naar de SD-kaart (logs naar RAM, swap uit — zie [../BOM.md](../BOM.md) over
waarom dat meer scheelt dan een snellere kaart).

`numpy` en `scipy` komen bewust uit `apt` en niet uit `pip`: scipy zelf bouwen
duurt op een Pi 5 met 1 GB ruim een uur en past nauwelijks in het geheugen.

### 3. De microfoon controleren

```bash
/opt/marantzknob/luxe/pi/microfoon.sh
```

Dit is de vijfminutencontrole uit [../BOM.md](../BOM.md), maar dan uitgevoerd
in plaats van beschreven. Hij zoekt de kaart, zet **Auto Gain Control** uit,
neemt vijf seconden op en zegt of daar signaal in zit.

Twee uitkomsten die betekenen dat je de verkeerde microfoon hebt:

- **geen enkele regelaar** — dan zit de firmware zelf aan het signaal en kun je
  er niets aan veranderen;
- **piek onder 0,002** — stil, dus verkeerd apparaat of gedempt.

Een *laag* niveau is geen probleem. De vingerafdrukker werkt met een relatieve
drempel; wat herkenning sloopt is een pompende AGC, niet een zachte opname.

### 4. Kijken of het loopt

```bash
journalctl -u marantzknob-brein -u marantzknob-luister -f
```

| Wat | Waar |
|---|---|
| webinterface | <http://marantzknob.local> |
| ruwe niveaus als JSON | <http://marantzknob.local/status> |
| nu meteen luisteren | `curl -X POST http://marantzknob.local/luister` |

Op **Collection** staat de platenkast als rond bladerscherm: de hoezen op een
rij, de sprongindex als letterring langs de binnenrand met de opening onderaan.
Scrollen, slepen of op een letter tikken. De zoekbalk eronder filtert ook het
bladerscherm, dus zoeken en bladeren werken op dezelfde lijst.

Het scherm van het paneel volgt de versterker: gaat de hoofdzone uit — met de
afstandsbediening, of door je Apple TV via HDMI — dan gaat het schermpje mee, en
bij het aanzetten komt het weer op. Uit te zetten onder **Panel › Display ›
Follow the amplifier**.

Op **Now** staat een kopie van het schermpje van het CrowPanel, op ware schaal en
met dezelfde gegevens: dezelfde hoes van `/hoes`, dezelfde accentkleur uit
dezelfde berekening als `bepaalAccent()` in `crowpanel/src/hoes.cpp`, en dezelfde
keuze tussen dB-getal, titel of alleen de hoes als in `uiRender()`. Verander je
daar iets aan de opmaak, dan hoort het hier ook te veranderen.

Eén pagina met tabbladen — Now, Queue, Collection, Panel en System — geserveerd
door de oren op poort 80 en 8791. Wat eronder ligt is nog steeds verdeeld: de
wachtrij en de collectie komen van het brein op 8790 (doorgegeven onder `/api/`)
en de instellingen van het paneel komen van het paneel zelf (onder `/paneel/`).
Voor de browser is dat één adres, en dat scheelt drie poortnummers onthouden.

Op `/status` zie je `niveauDb`, `ruisvloerDb` en `drempelDb`. Daarmee stel je de
drempel af zonder gokken: zet een plaat op, kijk waar `niveauDb` heen gaat, en
vergelijk dat met de drempel.

### 5. Je Discogs-sleutel en collectie

De database gaat niet mee met `rsync` (die staat in `brein/data/`). Op de Pi
vul je in de webinterface opnieuw je Discogs-token in en synchroniseer je de
collectie. Wil je je opgebouwde vingerafdrukken meenemen, kopieer dan
`brein/data/brein.db` er los naartoe voordat je de dienst start.

---

## Hoe het luisteren werkt

Er wordt **niet op een timer** gevraagd maar op een gebeurtenis: geluid na
stilte. Dat is het moment waarop je de naald neerzet.

Waarom dat zo moet, staat in [../PLAN.md](../PLAN.md): shazamio is een
onofficiele client zonder sleutel, en een handvol opzoekingen per avond valt
niet op waar honderden dat wel doen. Het is bovendien zinloos — een plaatkant
duurt twintig minuten en verandert in die tijd niet van naam.

En het werkt zonder dat deze dienst iets van de versterker hoeft te weten. Dat
is geen toeval maar noodzaak: de SR7015 laat maar één telnet-sessie toe, en die
is van het CrowPanel.

**De drempel volgt de kamer.** De stilste tien procent van de afgelopen minuut
geldt als ruisvloer; er wordt aangeslagen bij 12 dB daarboven. Zo werkt hetzelfde
getal in een stille kamer en met een raam open.

**De klok telt geluid, geen wandtijd.** Elk blok is precies 0,1 s aan audio, en
daarop lopen alle drempels. Dat lijkt een detail maar is het niet: met
`time.time()` zou een hapering van `arecord` een kant kunnen overslaan of juist
midden in een plaat opnieuw laten vragen.

Afstellen doe je in `marantzknob-luister.service`:

| | Standaard | Waarvoor |
|---|---|---|
| `TRIGGER_DB` | 12 | hoeveel boven de ruisvloer telt als muziek |
| `START_SECONDS` | 2,5 | zo lang geluid voordat het "het speelt" heet |
| `SETTLE_SECONDS` | 4 | de naald laten zakken voor we happen |
| `CLIP_SECONDS` | 8 | lengte van het fragment |
| `QUIET_SECONDS` | 25 | zo lang stilte betekent: kant afgelopen |

Na `systemctl daemon-reload && systemctl restart marantzknob-luister`.

## Waarom `web.py` bestaat

`../brein/server.py` bindt op `127.0.0.1`. Op je Mac is dat precies goed, op een
headless Pi betekent het dat je er niet bij kunt — terwijl die webinterface juist
is waar je met je telefoon in de hand onherkende platen koppelt.

`web.py` onderschept alleen die adreskeuze en laat de rest ongemoeid. Wil je het
ooit netter: maak van de host in `server.py` een instelling en gooi dit bestand
weg.

Let op dat de webinterface daarmee **zonder wachtwoord open staat op je hele
thuisnetwerk**. Voor dit apparaat is dat een bewuste afweging — er staat niets
gevoeligers in dan je platenkast — maar zet hem niet door je router naar buiten.

## Wat het bij de eerste installatie opleverde (1 augustus 2026)

Pi OS Lite 64-bits is inmiddels **Debian 13 (trixie) met Python 3.13**. Twee
dingen die daardoor misgingen en nu in `installeer.sh` zitten:

| | |
|---|---|
| `audioop` weg uit Python 3.13 | pydub importeert hem in drie bestanden — `audioop-lts` erbij |
| ffmpeg ontbrak | shazamio laat pydub de opname omzetten; zonder ffmpeg faalt dat **stil** en belandt alles onherkend in de wachtrij |

Die tweede is de vervelendste soort fout: er is geen foutmelding, alleen een
wachtrij die volloopt. Het script controleert daarom nu na installatie of
`import shazamio` werkelijk lukt.

Gemeten aan de microfoon (`AB13X USB Audio`): ruisvloer −53 dB, signaal tussen
−32 en −53, en die vloer bleef stil staan terwijl de muziek bewoog. Geen AGC dus.

## Wifi overleeft de eerste herstart niet — cloud-init

Pi OS van 2026 (pi-gen, image 18 juni 2026) zet de wifi op via **cloud-init**,
met een `network-config` op de bootpartitie. Dat werkt bij de eerste start, maar
cloud-init legt het niet vast op een plek waar NetworkManager het terugvindt:
`/etc/NetworkManager/system-connections/` blijft leeg en het door NM
gegenereerde netplan-bestand is nul bytes. Na de eerste herstart is de wifi weg.

Het lastige eraan is hoe het zich voordoet: de Pi doet niets meer op het
netwerk, terwijl het CrowPanel gewoon aangaat — dat hangt aan de USB-poort en
die krijgt al stroom voordat Linux iets doet. Het lijkt daardoor op een kapotte
SD-kaart terwijl er niets aan de hand is.

Zo stel je vast wat het is: **hang er een netwerkkabel aan.** Verschijnt hij,
dan start Linux prima en is het puur wifi.

En zo repareer je het, met de PSK die al in `network-config` op de bootpartitie
staat (die 64 tekens zijn de sleutel zelf, geen wachtwoord dat je hoeft te
kennen):

```bash
sudo nmcli connection add type wifi con-name <SSID> ifname wlan0 ssid <SSID> \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk <64-tekens-uit-network-config> \
  connection.autoconnect yes
```

Dat profiel belandt in `/etc/NetworkManager/system-connections/` en overleeft
wel een herstart — nagemeten op 2 augustus 2026: na `reboot` staat `wlan0`
vanzelf weer op `connected` en starten beide diensten mee.

## De seriële verbinding met het CrowPanel

Nagemeten met het paneel aan de USB van de Pi:

```
/dev/ttyACM0    crw-rw---- root dialout
Bus 001 Device 002: ID 303a:1001 Espressif USB JTAG/serial debug unit
```

Die ene USB-kabel draagt dus werkelijk stroom **en** een seriële verbinding, en
dat is precies de bedrade koppeling die fase 5 nodig heeft. Een aparte draad
naar de UART-connector is daarvoor niet nodig.

Wil je hem tóch op UART: `cmdline.txt` bevat `console=serial0,115200`, dus de
GPIO-UART is bezet door een inlogconsole. Die moet er dan eerst af.

## Wat hier nog niet in zit

- **Het eindpunt waarmee het CrowPanel om een opzoeking vraagt.** Nu luistert de
  Pi zelfstandig; het paneel weet er niets van. Zodra het paneel binnen is en
  over USB met de Pi praat, komt dat erbij.
- **De QR-code op het scherm** als er iets te koppelen valt.
- **De index in het geheugen** voor de lokale database, die pas nodig wordt
  voorbij ongeveer honderd kanten.
