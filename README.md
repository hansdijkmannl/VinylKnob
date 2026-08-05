# MarantzKnob — versie 1, de simpele

Eén draaiknop die alles doet, voor de Marantz SR7015, via het netwerk.
Eén doosje naast de bank aan de USB. Instellen doe je in een webinterface op het
bordje zelf — je hoeft de firmware nooit meer aan te raken om een ingang of de
stapgrootte te wijzigen.

| Gebaar | Effect |
|---|---|
| draaien | volume; snel draaien = grotere stappen |
| indrukken + draaien | ingang doorlopen |
| kort indrukken | mute aan/uit |
| dubbel indrukken | direct naar je favoriete ingang |
| vasthouden (1 s) | hoofdzone aan/uit |
| vasthouden (8 s) | wifi wissen, opstarten in setup-modus |

> Er is een luxere opvolger in de planning: een rond touchscreen met een
> draairing eromheen. De ontwerpanalyse staat in
> [docs/luxe-versie.md](docs/luxe-versie.md). Deze versie blijft zelfstandig
> werken en is geen tussenstap die je later weggooit.

## Waarom dit werkt

De SR7015 heeft het klassieke Denon/Marantz control-protocol op **TCP poort 23**
(telnet). Platte ASCII-commando's, afgesloten met `\r`:

| Commando | Effect |
|---|---|
| `SIPHONO` | schakel naar de phono-ingang |
| `MV45` | volume op 45 (= -35 dB) |
| `MV455` | volume op 45.5 (halve dB-stappen) |
| `MVUP` / `MVDOWN` | een halve dB omhoog/omlaag |
| `MUON` / `MUOFF` | mute |
| `ZMON` / `ZMOFF` | hoofdzone aan/uit |
| `PWON` / `PWSTANDBY` | hele toestel |
| `MV?` `SI?` `MU?` `ZM?` | opvragen |

Het volumegetal loopt van `00` t/m `98`, waarbij **80 = 0 dB**. Dus
`dB = waarde - 80`. De AVR meldt ook `MVMAX 98` zodat je weet waar het plafond
zit.

Het mooie: de receiver **pusht** wijzigingen ongevraagd over dezelfde
verbinding. Draai je aan de knop op het toestel of pakt iemand de
afstandsbediening, dan komt er spontaan een `MV52` binnen. Daardoor blijft het
schermpje in sync — geen polling nodig.

### Twee dingen om vooraf te regelen

1. **Setup → Netwerk → Netwerkbesturing → "Altijd aan"**. Staat dit op
   "Uit in stand-by", dan valt poort 23 weg zodra het toestel in stand-by gaat
   en kun je hem niet meer aanzetten.
2. **Er is maar één telnet-sessie tegelijk.** Als Home Assistant of een ander
   script al verbonden is, krijgt dit bordje niets. De HEOS-app zit op een
   andere poort en zit niet in de weg.

Er is ook een HTTP-variant (`http://<ip>/goform/formiPhoneAppDirect.xml?SIPHONO`)
zonder sessielimiet, maar die is te traag en te dom voor een draaiknop: geen
push-updates en een hele TCP-handshake per klik.

## Onderdelen

De volledige lijst met typeaanduidingen en aandachtspunten bij het bestellen
staat in **[BOM.md](BOM.md)**. Kort samengevat: de C3 die je al hebt, een
Bourns PEC11R-encoder met drukschakelaar (detentloos, als de vloeiende loop van
de Marantz-knop je voorkeur heeft), een zware aluminium knop, een OLED-schermpje
en een LED met weerstand. Rond de €15-35, waarvan de
knop het grootste deel is. Losse drukknoppen zijn er niet — alles zit in de
draaiknop.

## Aansluiten

Alles op interne pull-ups, dus geen externe weerstanden nodig.

```
C3 SuperMini       onderdeel
------------       ---------
GPIO5   ---------- encoder A
GPIO6   ---------- encoder B
GPIO7   ---------- encoder drukschakelaar
GND     ---------- encoder C (common) + andere poot van de drukschakelaar

GPIO20  ---------- OLED SDA
GPIO21  ---------- OLED SCL
3V3     ---------- OLED VCC
GND     ---------- OLED GND

GPIO10  --[1k]---- LED anode, kathode naar GND   (optioneel)

vrij:   GPIO0 / 1 / 3 / 4 (ruimte voor uitbreiding)
        GPIO2 / 8 / 9 -> afblijven, zie hieronder
```

De encoder heeft drie pootjes aan één kant (A, common, B — common zit in het
midden) en twee aan de andere kant voor de drukschakelaar. De drukschakelaar
gaat tussen GPIO7 en GND. Werk je met lange draadjes, dan helpt 100 nF over
encoder A→GND en B→GND tegen gestuiter. Op een compact printje niet nodig.

Elf soldeerverbindingen in totaal.

### Waarom GPIO 2, 8 en 9 niet meedoen

Op de ESP32-C3 zijn dat **strapping-pinnen**: ze moeten hoog zijn op het moment
dat de chip opstart. Zet je daar een drukknop naar GND op, dan start het bordje
niet op als je hem net indrukt — een bug waar je een avond aan kwijt bent.
GPIO 8 is bovendien de onboard blauwe LED en GPIO 9 de BOOT-knop.

Daarom staat I2C hier op **GPIO 20/21** (normaal UART0). Dat mag, omdat de
seriële monitor via de native USB van de C3 loopt — geregeld met de
`ARDUINO_USB_CDC_ON_BOOT` flags in `platformio.ini`.

### Antenne

De C3 SuperMini staat bekend om zijn matige wifi-bereik; de keramische antenne
is op veel exemplaren slecht afgestemd. Naast de bank, een paar meter van je
accesspoint, gaat dat vrijwel altijd goed — maar de firmware anticipeert erop:

- `WiFi.setSleep(false)`, anders voelt de knop merkbaar traag
- na 15 s zonder verbinding wordt de hele wifi-stack opnieuw opgezet, want de
  automatische reconnect van de SDK geeft het soms stil op
- de signaalsterkte staat in de webinterface, en onder -72 dBm ook op het
  schermpje

Zie je die waarschuwing structureel, dan is een C3-module met U.FL-connector en
externe antenne de oplossing.

### Voeding

Gewoon USB-C in de C3. Wil je hem intern voeden: 5 V op de `5V`-pin, die gaat
naar de onboard regelaar. **Niet tegelijk** met USB aangesloten — de meeste
SuperMini-klonen hebben geen scheidingsdiode. Verbruik is ~60 mA met wifi
actief.

### Printje

Begin op gaatjesprint — het zijn elf verbindingen. Werkt het,
dan is dit een triviaal 2-laags PCB'tje: encoder, OLED en LED aan de voorkant,
de C3 er achter op twee rijtjes headers.

### Behuizing

Zelf printen. Frontpaneel **maximaal 3 mm** dik, want de M7-bus van de encoder
heeft niet meer dan ~5 mm schroefdraad en daar moet de moer nog op.

Het belangrijkste ontwerpdetail zit niet in de maten maar in het gewicht: een
geprinte kast weegt 60-80 g en een aluminium knop vraagt merkbare kracht om te
draaien. Zonder ballast schuift het doosje over de tafel bij elke draai.
Ontwerp een holte in de bodem voor ~300 g moeren of ringen, en zet er vier
rubberen antislipvoetjes onder. Maten en de rest staan in [BOM.md](BOM.md).

## Over dat OLED-schermpje

Het blijft technisch optioneel — de firmware tast bij het opstarten af of er
iets op I2C hangt en slaat het display anders gewoon over, zonder foutmelding of
vertraging. Maar met één knop is mijn advies omgeslagen: **hang hem erin.**

In de opzet met vier losse inputknoppen was een schermpje overbodig; je zag aan
welke knop je indrukte wat er ging gebeuren, en voor het volume zijn de detents
zelf de feedback. Nu je de ingangen doorloopt door in te drukken en te draaien,
is dat gebaar zonder terugkoppeling blind — je weet niet waar in de lijst je
zit. Het schermpje toont tijdens dat gebaar de kandidaat-ingang groot in beeld,
met je positie eronder (`2 / 4`).

Kan het zonder? Ja. De firmware stuurt de nieuwe ingang 250 ms nadat je
stilhoudt, dus je ziet en hoort het alsnog op de receiver zelf. Je kunt alleen
niet vooruitkijken voordat je schakelt, en je moet de volgorde van je lijst uit
je hoofd kennen.

Los daarvan blijft de status-LED nuttig, want die zegt iets wat het schermpje
niet doet — of het commando daadwerkelijk de deur uit is:

| LED | betekenis |
|---|---|
| kort flitsje | commando verstuurd |
| continu aan | mute, of je bent een ingang aan het kiezen |
| langzaam knipperen (1 s) | geen verbinding met de receiver |
| snel knipperen (0,2 s) | setup-accesspoint actief |

Het display uitzetten zonder te desolderen kan in de webinterface.

### SSD1306 of SH1106

Beide drivers zitten in de firmware; je kiest het type in de webinterface, dus
je hoeft niet te flashen als je het verkeerd hebt. 0,96"-modules zijn bijna
altijd SSD1306, 1,3"-modules bijna altijd SH1106. Ze zitten allebei op
I2C-adres 0x3C en zijn softwarematig niet van elkaar te onderscheiden, vandaar
de keuze met de hand.

Symptoom van de verkeerde keuze: het beeld staat een paar pixels verschoven en
klapt aan de rand om. Ander type kiezen, herstarten, klaar.

## Firmware bouwen

PlatformIO staat nog niet op deze Mac:

```bash
brew install platformio
```

Daarna, met het bordje aan de USB:

```bash
cd /Volumes/Opslag/Apps/MarantzKnob && pio run -t upload && pio device monitor
```

De C3 is het standaard-target. Voor een klassiek ESP32-bordje:
`pio run -e esp32dev -t upload`.

Wil de C3 niet flashen, dan de eerste keer handmatig in download-mode: BOOT
(GPIO9) ingedrukt houden, RESET aantikken, BOOT los, dan uploaden.

Beide targets zijn schoon gebouwd: ~66% flash, ~14% RAM. Ruim genoeg over.

### Let op: dit project staat op een exFAT-volume

`/Volumes/Opslag` is exFAT, en daar schrijft macOS naast elk bestand een
`._naam` AppleDouble-sidecar. De compiler ziet die als broncode en struikelt
erover met `stray '\377' in program`. `platformio.ini` vangt dat op twee
manieren op:

- `build_dir` en `libdeps_dir` staan op de interne schijf, dus de libraries
  (U8g2, ArduinoJson) krijgen geen sidecars
- `build_src_filter = +<*> -<._*>` gooit de sidecars van onze eigen
  bronbestanden weg

Zonder die twee regels faalt de build. Kopieer ze mee naar elk ander
C/C++-project op dit volume.

## Instellen

Bij de eerste start is er nog geen wifi bekend, dus opent het bordje een eigen
accesspoint **MarantzKnob-setup**. Verbind ermee en ga naar
<http://192.168.4.1> — de configuratiepagina komt op je telefoon meestal
automatisch omhoog.

Daarna is de pagina te vinden op <http://marantzknob.local> (of het IP dat het
schermpje vier seconden na het opstarten toont).

Wat je er instelt:

| | |
|---|---|
| IP of hostnaam van de receiver | geef hem een DHCP-reservering in je router |
| halve dB per klik | 1 = fijn afstelbaar, 2-3 = sneller bij de juiste stand |
| encoderresolutie | 1 stap per detent, of 2×/4× fijner voor een detentloze encoder |
| versnelling bij snel draaien | vermenigvuldiger, standaard 6× |
| wat "snel" betekent | drempel in ms tussen twee klikken |
| volumeplafond in dB | noodrem, standaard -15 dB |
| ingangenlijst | tot 8 ingangen, elk met een eigen label; de volgorde is de draairichting |
| favoriete ingang | waar de dubbelklik naartoe springt |
| vasthouden voor aan/uit | standaard 1000 ms |
| dubbelklikvenster | standaard 350 ms; 0 zet de dubbelklik uit |
| wifi | SSID en wachtwoord |
| OLED aan/uit + controllertype | SSD1306 of SH1106, zie hieronder |

Bovenaan staat een live statusbalk met het huidige volume, de gekozen ingang,
of de receiver bereikbaar is en de signaalsterkte. Er is een testknop die direct
naar de eerste ingang schakelt, en een kaart met alle gebaren erop — zodat de
handleiding in het apparaat zelf zit.

Alles wordt in NVS bewaard en blijft dus staan over een herstart en een nieuwe
firmware-upload heen. Een leeg wifi-wachtwoordveld betekent "laat staan", niet
"wis het".

## Bediening

| Gebaar | Effect |
|---|---|
| draaien | volume; snel draaien = grotere stappen |
| draaien vanuit mute | heft mute op |
| indrukken + draaien | ingang doorlopen; wordt 250 ms na stilhouden verstuurd |
| kort indrukken | mute aan/uit |
| dubbel indrukken | direct naar je favoriete ingang |
| vasthouden (1 s) | hoofdzone aan/uit |
| vasthouden (8 s) | wifi-gegevens wissen en opstarten in setup-modus |

Een paar keuzes die erin verwerkt zitten:

**Indrukken + draaien versus vasthouden.** Zodra je tijdens het indrukken draait,
worden de mute en de aan/uit onderdrukt. Je kunt dus niet per ongeluk je
versterker uitzetten door tijdens het kiezen van een ingang te lang te blijven
hangen.

**Waarom 250 ms uitstel bij het kiezen.** Zonder dat uitstel zou de receiver bij
het doorlopen van je lijst elke tussenliggende ingang echt aantikken — relais
die klikken en geluid dat wegvalt. Nu stuurt hij alleen waar je op stilhoudt.

**Mute reageert met een kleine vertraging.** Die is gelijk aan het
dubbelklikvenster (350 ms), want de firmware moet even afwachten of er nog een
tweede klik komt. Zet je het venster op 0, dan is mute direct, maar verlies je de
favoriet.

**8 seconden vasthouden zet ook de zone om**, omdat de aan/uit al bij 1 seconde
is afgevuurd. Onvermijdelijk met één knop, en de wifi-reset is iets wat je eens
per paar jaar nodig hebt — bijvoorbeeld als je router verandert en je de
webinterface niet meer kunt bereiken.

## Eerst testen zonder te solderen

```bash
/Volumes/Opslag/Apps/MarantzKnob/tools/avr.sh 192.168.1.60 SIPHONO
```

Springt de receiver naar de platenspeler, dan is de rest afmonteren.

## Opbouw van de code

| Bestand | |
|---|---|
| `src/config.h` | pinout en fabrieksinstellingen (build-time) |
| `src/settings.{h,cpp}` | instellingen in NVS + JSON voor de webinterface |
| `src/marantz.{h,cpp}` | telnet-verbinding, commando's, protocol parsen |
| `src/web.{h,cpp}` | webserver en de configuratiepagina |
| `src/main.cpp` | encoder, de gebaren-machine, display, LED, wifi, de loop |
| `tools/avr.sh` | testcommando's vanaf je Mac |

## Ingangen van de SR7015

`PHONO` `CD` `TUNER` `DVD` `BD` `TV` `SAT/CBL` `MPLAY` `GAME` `8K` `AUX1`
`AUX2` `NET` `BT` `USB` `HDRADIO` `SPOTIFY` `IRADIO` `SERVER` `FAVORITES`

Deze staan in de dropdown van de webinterface. Niet elke ingang is op elk
toestel geconfigureerd; wat er echt is zie je aan wat `SI?` terugmeldt in de
seriële monitor.
