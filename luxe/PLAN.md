# Luxe versie — bouwvolgorde

Rond touchscreen met draaiknop, voor de Marantz SR7015. Ontwerpanalyse staat in
[../docs/luxe-versie.md](../docs/luxe-versie.md), onderdelen in [BOM.md](BOM.md).

## De architectuur

**Route C**: een kant-en-klaar CrowPanel voor de bediening, met een kale
Raspberry Pi Zero ernaast als brein.

| Doet | Wat |
|---|---|
| **Elecrow CrowPanel 2.1"** | scherm, knop, touch, telnet naar de AVR, de hele bediening. ESP32-S3, LVGL, meteen aan |
| **Pi Zero 2 W, headless** | INMP441-microfoon, shazamio, lokale fingerprint-database, Discogs, de webinterface met de koppelwachtrij |

Ze praten over het netwerk, of over de UART-connector van het CrowPanel.

Waarom dit beter uitpakt dan een Pi met een HyperPixel: **de Pi hoeft geen
scherm aan te sturen.** Daarmee vervalt het GPIO-probleem van een DPI-display,
de tweede microcontroller voor de encoder, en het wachten op een opstartend
Linux — het CrowPanel is meteen aan en de Pi start op de achtergrond op. En
omdat de 40-pins header vrij is, kan de microfoon een rauwe I2S-MEMS zijn in
plaats van een USB-dongel met verborgen ruisonderdrukking.

Ongeveer €100, en er zit geen enkel mechanisch precisiedeel meer in.

---

## Fase 0 — Herkenning bewijzen ✅

**Klaar.** [recognizer/](recognizer/): eigen fingerprinting in Python, foutloos
tot 20 dB SNR met snelheidsafwijking, grenzen rond 100 kanten.

Rest hier: de index in het geheugen (factor 20-50 in zoektijd), en toetsen op
echte naaldopnames in plaats van synthetische.

## Fase 0b — Herkenning met een microfoon ✅

**Klaar en geslaagd.** [webproef/](webproef/) herkende op 31 juli 2026 in 8
seconden vrijwel alles, van een iPhone-luidspreker via de microfoon van een
MacBook, inclusief hoes.

Gevolg: de eigen fingerprint-database uit fase 0 zakt van hoofdmechanisme naar
**cache**, die alleen groeit waar Shazam tekortschiet.

Randvoorwaarde die daarbij hoort: **niet op een timer opvragen maar bij een
gebeurtenis** (ingang gaat naar phono, of geluid begint na stilte). shazamio is
een onofficiële client zonder sleutel; een handvol opzoekingen per avond is
onopvallend, honderden niet.

## Fase 1 — Het CrowPanel bestellen en voelen ✅

Binnen en in gebruik. De knop heeft detents; met de versnelling erop
(0,5 dB rustig, 4,0 dB doordraaiend) is dat in de praktijk geen bezwaar
gebleken, dus de eigen ring is niet nodig.

## Fase 1b — Interface-mockup ✅

**Klaar.** [mockup/](mockup/) is een werkende schets van de vier schermen en het
bedieningsmodel, te openen in je browser. Dient als referentie bij het schrijven
van de LVGL-firmware.

Kern van het model: met rotatie, druk én touch hoeft niets modaal te zijn.
**Draaien is altijd volume**, in elk scherm. Alles wat je zonder kijken wil doen
zit op de knop (mute, favoriet, aan/uit); alles waarvoor je toch naar het scherm
kijkt zit op het scherm (ingang, platenkast).

## Fase 2 — Het CrowPanel als bediening ✅

**Af en beproefd op hardware, 1 augustus 2026.** Werkend: scherm, aanraking,
volume met de knop, mute, aan/uit, de ingangenlijst en telnet naar de SR7015.
17,5% flash, 29,9% RAM. Zie [crowpanel/](crowpanel/).

Vier dingen bleken pas met het paneel op tafel:

- **Een bootlus** door `board_build.flash_size`, dat niets doet — de bootloader
  leest `board_upload.flash_size`. Zie de bijlage in [OPBOUW.md](OPBOUW.md).
- **`lv_label_set_text_fmt` kan geen `%f`.** LVGL's eigen printf laat drijvende
  komma standaard weg, dus er stond letterlijk `f` op het scherm.
- **De encoder telt andersom** dan die van versie 1 (`ENC_INVERT`), en één
  detent is precies één stap. Rustig 0,5 dB, snel 4,0 dB.
- **Het uitstel van 250 ms bij een ingangkeuze moest juist weg.** In versie 1
  was draaien de keuze; hier is er een lijst en een bevestiging, en meesturen
  tijdens het bladeren sleepte je door elke tussenliggende ingang.

En één ding dat niet aan de firmware lag: een Marantz negeert `SI`-commando's
voor bronnen die op `DEL` staan. `SSSOD ?` vraagt op welke dat zijn.

De driver stond hier lang als het enige dat pas met hardware op tafel te
schrijven viel. Dat bleek maar half waar. Uit Elecrow's eigen repo:

- de ST7701-initialisatiereeks is **niet** paneelspecifiek maar gewoon
  `st7701_type5_init_operations` uit Arduino_GFX, en hun meegeleverde kopie is
  byte voor byte upstream **v1.3.1** (nieuwere versies hebben een herschreven
  API én een andere BGR-bit, dus die tag staat vastgepind);
- de aanraakchip is een **CST826** op `0x15`;
- wat wél niet te raden was, is de **opstartvolgorde** — LCD en aanraakchip
  hangen allebei achter de PCF8574 en willen elk hun eigen resetpuls vóór
  `gfx->begin()`. Die staat nu in `board.cpp`.

`ui_serial.cpp` blijft bestaan als tweede omgeving: dezelfde firmware met de
seriële monitor als scherm, om de bediening te volgen zonder dat het paneel in
de weg zit.

## Fase 3 — De sokkel

Geprinte sokkel waar het CrowPanel op staat, met de Pi en de microfoon erin.
Geen tandwielen, geen lager, geen precisiewerk meer — maar wél **gewicht**: het
CrowPanel weegt 80 gram en schuift anders over je tafel als je aan de knop
draait. Holte voor ~300 g ballast, vier antislipvoetjes eronder, en een
akoestische opening voor de microfoon.

## Fase 4 — De Pi als brein ✅

**Draait, 1 augustus 2026.** Raspberry Pi 5 (`AVRKNOB`, Debian 13 trixie),
beide diensten actief en ingeschakeld. Volledige keten beproefd: microfoon →
drempel → Shazam → koppeling aan de collectie, zonder de Mac.

Drie dingen die pas op de echte Pi bovenkwamen:

- **Pi OS is inmiddels Debian 13, met Python 3.13**, en daar is `audioop` uit de
  standaardbibliotheek gesloopt terwijl pydub — waar shazamio op leunt — hem in
  drie bestanden importeert. `audioop-lts` lost dat op; het installatiescript
  zet hem er nu bij en controleert daarna of `import shazamio` echt lukt.
- **ffmpeg ontbrak**, en dat faalt stil: shazamio laat pydub de opname omzetten,
  en zonder ffmpeg belandde alles onherkend in de wachtrij zonder dat er iets op
  een fout leek. Staat nu in de pakketlijst.
- **De USB-dasspeldmicrofoon heeft geen AGC**, en dat is nu gemeten in plaats van
  gehoopt: de ruisvloer bleef strak op −53 dB terwijl het signaal tussen −32 en
  −53 bewoog. Bij automatische versterking was die vloer meegekropen.

Wat er nog los van staat: het signaal komt maar 10 à 20 dB boven de ruisvloer
uit — de ondergrens van waarop de vingerafdrukker beproefd is. Voorlopig genoeg,
maar `Mic Capture Volume` (nu 80%) is de knop als het tegenvalt.

**Oorspronkelijke opzet, ongewijzigd:** Zie [pi/](pi/): een installatiescript voor een
verse Raspberry Pi OS Lite 64-bits, twee systemd-diensten, en een luisteraar op
de USB-dasspeldmicrofoon.

Er is niets gewijzigd in [brein/](brein/) — dat blijft het testbed op de Mac.
`pi/web.py` onderschept alleen de bindkeuze zodat de webinterface vanaf je
telefoon bereikbaar is.

Het luisteren gaat **op een gebeurtenis, niet op een timer**: geluid na stilte,
met een drempel die de kamer volgt (de stilste tien procent van de afgelopen
minuut is de ruisvloer, aanslaan bij 12 dB daarboven). Dat werkt zonder dat de
Pi iets van de versterker hoeft te weten, en dat is noodzaak: de SR7015 laat
maar één telnet-sessie toe en die is van het CrowPanel.

Eén ding dat bij het uitproberen bovenkwam en makkelijk mis te gaan was: de
drempels lopen op een **klok die geluid telt, geen wandtijd**. Met `time.time()`
kan een hapering van `arecord` een kant overslaan of juist midden in een plaat
opnieuw laten vragen.

De referentieopnames lopen zo automatisch via dezelfde microfoon op dezelfde
plek, waardoor kamerakoestiek en luidsprekerkleuring tegen elkaar wegvallen.

## Fase 5 — Paneel en Pi aan elkaar ✅

**Werkt sinds 2 augustus 2026.** Het paneel haalt elke vier seconden bij de Pi
op wat er speelt, toont artiest en album, en de hoes erbij.

Keuze die het meeste bepaalde: **HTTP over wifi, niet serieel.** De USB-kabel
draagt wel degelijk een seriële verbinding (`/dev/ttyACM0`, nagemeten), maar die
gebruiken vraagt een eigen protocol met framing, een seriële client op de Pi, en
het opgeven van de monitor waarmee dit paneel te volgen is. Het paneel zit al op
wifi — dat moet, voor telnet — en de Pi serveert al HTTP. Eén GET volstaat.

| | |
|---|---|
| `GET /nu` | artiest, album, of er een hoes klaarstaat, hoeveel er te koppelen valt |
| `GET /hoes` | de hoes, door de Pi teruggebracht tot 240×240 (~9 kB) |
| `POST /luister` | het paneel vraagt om een opzoeking |

Drie dingen die daarbij opvielen:

- **De Pi schaalt de hoes, niet het paneel.** Een ESP32 die een JPEG van 600
  pixels moet verkleinen kost geheugen en tijd die hij niet heeft; de Pi doet
  het in tientallen milliseconden met Pillow, en het paneel decodeert één op één
  in een buffer die het vooraf kan reserveren.
- **De QR-code dringt zich niet op.** Er staat een stipje op het volumescherm
  als er iets te koppelen valt; tikken op de hoes brengt je naar de code. Een
  scherm dat zichzelf naar voren duwt terwijl je aan de volumeknop draait is
  precies wat je niet wilt.
- **Het paneel lokt een opzoeking uit** zodra de ingang naar je favoriet gaat.
  Dat is het moment waarop je de naald neerzet, en het scheelt de Pi het wachten
  tot hij het zelf hoort.

Bijvangst: [crowpanel/flash-via-pi.sh](crowpanel/flash-via-pi.sh) flasht het
paneel over het netwerk via de Pi. De kabel hoeft niet meer heen en weer, want
esptool zet de S3 zelf in de bootloader over zijn native USB.

## Fase 5b — De wachtrij en de webinterface ✅

**Draait op de Pi.** Zie [brein/](brein/): luisteren met eerst de eigen
database en dan pas een dienst, beide motoren naast elkaar,
Discogs-collectie synchroniseren en doorzoeken, de koppelwachtrij met
geluidsfragmenten, zelf invoeren met een eigen hoes, en een "dit klopt
niet"-knop. Dezelfde code gaat straks op de Pi draaien; dan komt de opname van
de USB-microfoon in plaats van uit de browser.

Wat er nog moet: de QR-code op het scherm van het CrowPanel, en het eindpunt
waarmee het paneel om een opzoeking vraagt.

Onherkende kanten belanden in een wachtrij met hun geluidsfragment. In de
webinterface koppel je die aan een Discogs-release of upload je zelf een hoes;
daarna herkent het apparaat ze zelf, zonder dienst. Zo groeit de lokale
database precies daar waar Shazam tekortschiet.

Mislukt een opzoeking, dan blijft de Pi nog 60-90 seconden doorluisteren. Acht
seconden is genoeg om het te vrágen, maar te weinig als eigen referentie: dan
dek je acht seconden van een kant van twintig minuten.

Naar die webinterface toe: een **QR-code op het scherm** met het IP-adres
eronder in gewone cijfers. Hij verschijnt op het moment dat er iets te koppelen
valt — dan is het ook precies het moment waarop je je telefoon pakt.

## Fase 6 — De collectiebladeraar ✅

Drie hoezen op een rij, de knop als positie, de sprongindex als letterring langs
de binnenrand. Tik op de hoes om erin te komen, druk om eruit te gaan; draaien
bladert, ingedrukt draaien springt per letter.

**Kiezen doet twee dingen, afhankelijk van wat er speelt.**

Draait er een plaat die niet herkend werd, dan is kiezen een **koppeling**. Het
brein hangt jouw keuze aan die luisterbeurt én legt het bewaarde fragment vast
als vingerafdruk, waarna dezelfde kant voortaan lokaal herkend wordt zonder
dienst. Dat is precies de les die alleen jij kunt geven, en dit is het moment
waarop je hem kunt geven: met de naald er nog in en de hoes in je hand, in
plaats van 's avonds met je telefoon door een wachtrij. De kop van het scherm
zegt dan **KOPPEL AAN WAT SPEELT**, want je hoort te weten dat je iets vastlegt.

Speelt er niets bijzonders, dan is kiezen alleen "laat zien": de hoes komt
schermvullend terug. Opleggen kan dit apparaat niet. Die keuze blijft staan tot
het brein iets anders meldt — zet je daarna werkelijk een plaat op, dan wint de
herkenning. Wat er klinkt is waarheid, wat je aanwees was een keuze.

De Pi houdt daarvoor bij welke opzoeking nog openstaat (`open_play_id`). Die
vervalt bij een geslaagde herkenning en na vijf minuten stilte, want dan hoort
wat je aanwijst niet meer bij wat je hoorde. Koppelen gebeurt alleen aan een
album dat werkelijk in de kast staat: een koppeling is blijvend en zet een
vingerafdruk vast, dus die maak je niet op goed vertrouwen.

Tijdens het springen per letter komt die letter groot in beeld, in Montserrat op
130 pixels. Daar is een eigen lettertype voor gegenereerd (`font_kastletter.c`,
alleen A-Z en `#`, 52 kB flash): LVGL levert Montserrat tot 48 px en dat is op
een scherm van 480 te klein om tijdens het draaien te lezen. De ring blijft
klein — die laat zien wáár je bent, de grote letter waar je naartoe gaat.

De verdeling is dezelfde als overal: de Pi weet, het paneel toont. De namen komen
in één keer binnen via `/kast` — 25 kB platte tekst, want 40 kB JSON ontleden
kost een ESP32 seconden en regels splitsen op een tab bijna niets. De hoezen
komen per stuk via `/kasthoes`, op maat gemaakt door de Pi, en alleen die van de
drie die in beeld staan; er passen er negen in het geheugen zodat heen en weer
draaien over dezelfde plek niets kost.

Ophalen gebeurt nooit tijdens het draaien: de tekst schuift meteen mee, de
hoezen komen na als je tweehonderd milliseconden stilhoudt. Een knop die per
stap op het netwerk staat te wachten voelt kapot, ook al is er niets mis.

Alle drie de hoezen zijn even groot. Dat scheelt werk: was het middelste plaatje
groter, dan zou één stap drie nieuwe plaatjes vergen in plaats van één. Welke de
huidige is zie je aan de rand eromheen en aan de titel eronder.

Sinds de hoes naar de kast leidt heeft de QR-code voor het koppelen een eigen
aanraakvlak gekregen rond het stipje — tien pixels raak je niet met een vinger.

---

## Wat overkomt uit versie 1

Versie 1 blijft zelfstandig werken en is geen weggooiwerk. Direct herbruikbaar:

- het protocol (`MV`/`SI`/`MU`/`ZM`, `dB = waarde - 80`, halve stappen, `MVMAX`)
- dat de receiver ongevraagd pusht, dus geen polling nodig
- de quadratuur-decoder en de `encDivider`-gedachte, om de stapgrootte per klik
  af te stemmen
- het uitstel van 250 ms bij ingangkeuze
- de rolverdeling: apparaat toont, webinterface configureert

En de twee randvoorwaarden: Netwerkbesturing op "Altijd aan", en één
telnet-sessie tegelijk.
