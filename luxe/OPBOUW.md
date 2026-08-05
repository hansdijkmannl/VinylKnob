# Opbouw, stap voor stap

Alle onderdelen zijn binnen. Dit is de volgorde waarin je ze in gebruik neemt,
met per stap wat je moet zien en wat je doet als dat niet zo is.

Bedrading staat in [bedrading.svg](bedrading.svg). Achtergrond bij de keuzes in
[PLAN.md](PLAN.md) en [BOM.md](BOM.md).

---

## Stap 0 — Laat de versterker los

De SR7015 accepteert **één telnet-sessie tegelijk**. Zolang het brein op je Mac
verbonden is, komt het CrowPanel er niet in. Dat is de meest verwarrende fout
die je kunt maken, want het paneel meldt gewoon "geen receiver".

Controleer:

```bash
curl -s http://127.0.0.1:8790/api/avr/state
```

Staat daar `"connected": true`, verbreek dan eerst:

```bash
curl -X POST http://127.0.0.1:8790/api/avr/disconnect
```

Vanaf nu is het **CrowPanel** de eigenaar van die verbinding. De webinterface op
je Mac blijft werken voor herkenning en Discogs; druk daar alleen niet meer op
"verbind".

---

## Stap 1 — Het CrowPanel flashen

PlatformIO staat sinds vandaag in `~/.platformio-venv`. Kortere vorm:
zet `export PATH="$HOME/bin:$PATH"` in je `~/.zshrc`, dan volstaat `pio`.

**1a. Zoek de kabel.** Het paneel heeft géén USB-C. Voeding en data lopen over de
connector `USB-5V-IN`: een **JST MX1.25 met 4 polen** (`GND · D+ · D− · VCC`).
Elecrow levert daar normaal een USB-A-kabel bij — die heb je nodig.

**1b. In flash-modus zetten.** Er is geen automatische reset: `RESET` en `GPIO0`
liggen op de 12-pins FPC, niet op die 4-polige connector.

1. Houd de **BOOT**-knop ingedrukt
2. Steek de kabel in je Mac
3. Laat BOOT los

Controleer dat hij zich meldt:

```bash
ls /dev/cu.usbmodem*
```

Zie je niets, dan is het bijna altijd de kabel of de BOOT-timing. Probeer
opnieuw en houd BOOT iets langer vast.

**1c. Flashen.**

```bash
cd /Volumes/Opslag/Apps/MarantzKnob/luxe/crowpanel && ~/.platformio-venv/bin/pio run -t upload
```

**1d. Druk daarna op RESET.** Na het uploaden staat de chip nog in de
ROM-bootloader; pas na een reset draait je firmware. De poortnaam kan daarbij
veranderen.

**1e. Meekijken.**

```bash
cd /Volumes/Opslag/Apps/MarantzKnob/luxe/crowpanel && ~/.platformio-venv/bin/pio device monitor
```

Je hoort te zien:

```
MarantzKnob — CrowPanel
[bord] aanraakchip gevonden
Setup-accesspoint "MarantzKnob-setup" op 192.168.4.1
```

Staat er `[bord] GEEN aanraakchip op 0x15`, dan is de PCF8574 niet gevonden of
liep de resetvolgorde mis — het scherm staat daar los van. Blijft het scherm
zwart maar is de rest goed, zie de foutzoeklijst in
[crowpanel/README.md](crowpanel/README.md).

---

## Stap 2 — De knop voelen

Dit is de vraag die vanaf het begin openstaat en die je nu in één minuut
beantwoordt: **draait die ingebouwde encoder met klikjes?**

Vrijwel zeker van wel, en dat is precies wat je niet wilde — de volumeknop van
de Marantz doet het ook niet. Valt het tegen, dan is `encDivider` in de
instellingen de knop om het te temmen: die bepaalt hoeveel
quadratuur-overgangen één stap zijn.

Doe dit vóór je aan de Pi begint. Het is het enige dat de hele route nog kan
veranderen.

---

## Stap 3 — Het CrowPanel instellen

Het paneel heeft geen toetsenbord, dus dit gaat via een webpagina.

1. Verbind je telefoon of Mac met het wifi-netwerk **MarantzKnob-setup**
2. Ga naar <http://192.168.4.1>
3. Vul in: je eigen wifi, het IP-adres van je receiver, en de ingangenlijst
   (PHONO als favoriet)
4. Opslaan — hij herstart op je eigen netwerk

Daarna staat dezelfde pagina op <http://marantzpaneel.local> — of gewoon op het
IP dat in de monitor verschijnt. **Niet** `marantzknob`: zo heet de Pi.

**Nu testen tegen de versterker.** Draai aan de knop: het volume hoort mee te
gaan. Kort drukken is mute, lang drukken is aan/uit, tikken op de ingangsnaam
opent de ingangenlijst.

Werkt het niet, loop dan stap 0 nog eens na — negen van de tien keer houdt er
nog iets anders die telnet-sessie vast.

---

## Stap 4 — De SD-kaart voor de Pi

Raspberry Pi Imager staat al in je Applications.

- **Raspberry Pi OS Lite (64-bit)** — geen desktop, die kost alleen geheugen en
  de Pi krijgt nooit een scherm
- In het tandwielmenu:

| | |
|---|---|
| hostnaam | `marantzknob` (het paneel heet `marantzpaneel`) |
| SSH | aan, met je publieke sleutel |
| wifi | je eigen netwerk |
| gebruiker | je eigen naam, niet `pi` |

Die hostnaam maakt alles hierna bereikbaar op `marantzknob.local`, ook als de
router een ander IP uitdeelt.

Kaart erin, koellichaam erop, 27 W-adapter in de USB-C van de Pi. Wacht een
minuut en probeer:

```bash
ssh marantzknob.local
```

---

## Stap 5 — De Pi inrichten

Vanaf je Mac:

```bash
rsync -a --exclude '.venv' --exclude '._*' --exclude 'data' --exclude '*.stl' /Volumes/Opslag/Apps/MarantzKnob/ admin@<ip-van-de-pi>:marantzknob/
```

Dan op de Pi. Let op de `-t`: het script gebruikt `sudo` en moet dus om je
wachtwoord kunnen vragen.

```bash
ssh -t admin@<ip-van-de-pi> 'cd ~/marantzknob/luxe/pi && ./installeer.sh'
```

De map staat in je home en niet in `/opt`, zodat het kopiëren zelf geen root
nodig heeft. Het script leidt alle paden af van zijn eigen plek, dus het werkt
vanaf elke locatie.

Dat duurt een paar minuten: pakketten, een virtuele omgeving, twee
systemd-diensten, en het beperken van schrijfacties naar de SD-kaart (logs naar
RAM, swap uit). Het script mag je zo vaak draaien als je wilt.

---

## Stap 6 — De microfoon controleren

Steek de dasspeldmicrofoon in een **USB-A**-poort van de Pi en draai:

```bash
ssh admin@<ip-van-de-pi> marantzknob/luxe/pi/microfoon.sh
```

Dit is de vijfminutencontrole uit [BOM.md](BOM.md), maar dan uitgevoerd: hij
zoekt de kaart, zet **Auto Gain Control** uit, neemt vijf seconden op en zegt of
daar signaal in zit.

Twee uitkomsten betekenen dat je de verkeerde microfoon hebt:

- **geen enkele regelaar** — dan zit de firmware zelf aan het signaal en kun je
  er niets aan veranderen;
- **piek onder 0,002** — stil, dus verkeerd apparaat of gedempt.

Een *laag* niveau is juist geen probleem. De vingerafdrukker werkt met een
relatieve drempel; wat herkenning sloopt is een pompende AGC, niet een zachte
opname.

---

## Stap 7 — Kijken of de Pi loopt

```bash
ssh admin@<ip-van-de-pi> 'journalctl -u marantzknob-brein -u marantzknob-luister -f'
```

| Wat | Waar |
|---|---|
| webinterface | <http://marantzknob.local:8790> |
| niveaus van de oren | <http://marantzknob.local:8791/status> |
| nu meteen luisteren | `curl -X POST http://marantzknob.local:8791/luister` |

Vul in de webinterface je Discogs-token in en synchroniseer de collectie — die
gaat niet mee met `rsync`. Wil je je opgebouwde vingerafdrukken behouden,
kopieer dan eerst `luxe/brein/data/brein.db` los naar de Pi en herstart de
dienst.

**Afstellen zonder gokken:** zet een plaat op en kijk op `/status` waar
`niveauDb` heen gaat ten opzichte van `drempelDb`. De schroefjes staan in
`marantzknob-luister.service`.

---

## Stap 8 — Het CrowPanel op de Pi

Tot nu toe hing het paneel aan je Mac. Verhuis de USB-kabel naar een USB-A-poort
van de Pi. Alles blijft werken: het paneel praat over wifi met de versterker, de
Pi over wifi met Shazam en Discogs.

Let op: de twee praten nog **niet** met elkaar. De Pi luistert zelfstandig en
het paneel weet daar niets van. Dat koppelstuk — het paneel dat om een
opzoeking vraagt, en de QR-code als er iets te koppelen valt — is het volgende
werk. Zie [PLAN.md](PLAN.md), fase 5.

---

## Als er iets niet lukt

| Symptoom | Meestal |
|---|---|
| paneel zegt "geen receiver" | er houdt nog iets anders de telnet-sessie vast (stap 0) |
| `/dev/cu.usbmodem*` verschijnt niet | BOOT niet lang genoeg vastgehouden, of de verkeerde kabel |
| na uploaden gebeurt er niets | druk op RESET; de chip staat nog in de bootloader |
| scherm blijft zwart, monitor spuwt `ESP-ROM` | bootlus — zie hieronder |
| scherm zwart, monitor wel goed | zie [crowpanel/README.md](crowpanel/README.md) |
| verkeerde kleuren op het scherm | Arduino_GFX niet op v1.3.1 — `pio pkg list` |
| `marantzknob.local` niet vindbaar | avahi nog niet op; probeer het IP uit je router |
| een ingang doet niets, andere wel | die bron staat op `DEL` in de receiver — zie [crowpanel/README.md](crowpanel/README.md) |

---

## Bijlage — de bootlus van 1 augustus

Bij de eerste keer flashen bleef het scherm zwart. In de monitor stond, veertig
keer per seconde:

```
ESP-ROM:esp32s3-20210327
rst:0x3 (RTC_SW_SYS_RST),boot:0xa (SPI_FAST_FLASH_BOOT)
Saved PC:0x403cdb0a
entry 0x403c98d0
```

Geen enkele regel van de firmware zelf. Dat is dus geen schermprobleem: het
bordje herstartte al voordat er code van mij draaide.

Hoe het gevonden is, in stappen die elk iets uitsloten:

1. **De kale seriële firmware** (zonder scherm, LVGL of achtergrondverlichting)
   liep in dezelfde lus → niet het scherm, en ook geen stroomtekort.
2. **Een bouwsel zonder PSRAM** liep er ook in → niet de `memory_type`.
3. **De flash volledig wissen** hielp niet → geen restant van Elecrow's
   fabrieksimage.
4. **Elecrow's eigen fabrieksimage flashen** wérkte meteen → het bord, de
   voeding en de flash zijn in orde, dus het zat in mijn bouwconfiguratie.
5. De flash-header van beide images vergelijken bracht het aan het licht:
   die van mij zei **8 MB** terwijl er een partitietabel voor **16 MB** onder
   hing.

De oorzaak: `board_build.flash_size` doet niets. De bootloader leest zijn
flashgrootte uit **`board_upload.flash_size`**, en die stond op de
bordstandaard van 8 MB. De bootloader vond dan partities voorbij het einde van
wat hij dacht te hebben, en herstartte.

```ini
board_upload.flash_size = 16MB
board_upload.maximum_size = 16777216
board_build.partitions = default_16MB.csv
```

De werkelijke flash is nagemeten met esptool: manufacturer `ba`, device `4018`,
16 MB, quad volgens eFuse. En de chip is een echte S3R8 — `Embedded PSRAM 8MB
(AP_3v3)` — dus `memory_type = qio_opi` klopte al.

Handig om te onthouden voor de volgende keer: **de bootloader logt naar UART0
(GPIO43/44), niet naar USB.** Over de USB-kabel zie je daarom alleen de
ROM-regels en nooit de reden. Wil je die reden wel zien, hang dan een
USB-serieeladapter aan de UART-connector.
