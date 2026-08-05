# Onderdelenlijst — luxe versie

Rond touchscreen met draaiknop, voor de Marantz SR7015. Gekozen architectuur is
**route C**: een kant-en-klaar CrowPanel voor de bediening, met een kale
Raspberry Pi Zero ernaast als brein. Onderbouwing staat in
[../docs/luxe-versie.md](../docs/luxe-versie.md), bouwvolgorde in
[PLAN.md](PLAN.md).

Prijzen zijn indicatief (2026, EU). Het CrowPanel komt van Elecrow zelf, via
Amazon of Tindie; de rest bij Kiwi Electronics of TinyTronics.

## Wat er daadwerkelijk besteld is (31 juli 2026)

| Onderdeel | Prijs |
|---|---|
| Raspberry Pi 5, 1 GB (bij Kiwi) | ~€50 |
| ELECROW ESP32 Rotary Display 2.1" | €53,29 |
| SanDisk High Endurance microSD 32 GB | €25,53 |
| InnoMaker 27 W USB-C PD, 5,1 V / 5 A | €12,61 |
| YFYWINSH USB-dasspeldmicrofoon, 1,5 m | €7,99 |
| **samen** | **~€150** |

Dat is meer dan de ~€100 die hier eerder stond. Die schatting ging uit van een
Pi Zero 2 W (€22) en een CrowPanel van €40; het werden een Pi 5 en een duurder
paneel. De opzet is verder ongewijzigd.

Nog nodig: een **koellichaam of koelbehuizing voor de Pi 5** (geen ventilator),
en de kabel van de Pi naar het CrowPanel. Let op: **het CrowPanel heeft geen
USB-C.** Voeding en data lopen over een **JST MX1.25-connector van 4 polen**
(`USB-5V-IN`: GND, D+, D−, VCC). Elecrow levert daar normaal een USB-A-kabel
bij — controleer dat in de doos, want los is dat kabeltje lastig te vinden.

## Bediening

| # | Aantal | Onderdeel | Wat je zoekt | ~Prijs |
|---|---|---|---|---|
| 1 | 1 | **Elecrow CrowPanel 2.1" ESP32 Rotary Display** | ESP32-S3R8, 8 MB PSRAM, 16 MB flash, rond IPS 480×480, capacitieve touch, ingebouwde encoder. Behuizing van aluminium en acryl, 79×79×30 mm | €40 |

Dit ene bordje vervangt het display, de computer, de encoder, het lager, de
tandwielen én de behuizing uit het eerdere ontwerp.

## Brein

| # | Aantal | Onderdeel | Wat je zoekt | ~Prijs |
|---|---|---|---|---|
| 2 | 1 | Raspberry Pi **Zero 2 W** | de **2** is essentieel — zie hieronder. Liefst de WH-uitvoering met voorgesoldeerde header | €22 |
| 3 | 1 | microSD-kaart | 16-32 GB, **A1**, liefst "High Endurance" — zie hieronder | €10 |
| 4 | 1 | Microfoon — **hangt af van welke Pi**, zie hieronder | INMP441 op I2S bij een Zero 2 W; **USB-geluidskaartje met electret** bij een Pi 5 | €4-8 |
| 5 | 1 | Voeding | bij een Pi 5: de **officiele 27 W USB-C PD-adapter**, geen generieke lader — zie hieronder | €12-15 |
| 6 | 1 | USB-A naar JST MX1.25 4-polig | van de Pi naar `USB-5V-IN` van het CrowPanel: stroom **en** data over dezelfde vier draden. Zit meestal bij het paneel | €4 |
| 7 | — | Soepele draad 0,25 mm², female jumpers | zes draadjes van de microfoon naar de Pi | €3 |

## Behuizing

| # | Aantal | Onderdeel | Waarvoor | ~Prijs |
|---|---|---|---|---|
| 8 | ~300 g | Ballast | stalen ringen, M8-moeren of loodhagel | €0-4 |
| 9 | 4 | Antislipvoetjes ~12 mm | **niet overslaan**, zie hieronder | €1 |
| 10 | 4 | Heat-set inserts M3 + schroeven M3×10 | bodemplaat | €0,60 |
| 11 | — | Filament | PETG, of ASA voor een matte look | — |

Zelf te printen: een sokkel waar het CrowPanel op staat, met de Pi en de
microfoon erin.

**Totaal ongeveer €100.** Het CrowPanel is er veertig procent van, en er zit
geen enkel mechanisch precisiedeel meer in.

---

## Aandachtspunten

### De microfoon hangt af van welke Pi (4)

**Op een Pi 5 werkt de INMP441 niet.** Dat is geen kanttekening maar een
bekend, onopgelost probleem: de RP1-chip heeft een andere I2S-opzet met
gescheiden master- en slave-klokblokken, en de gangbare
`googlevoicehat-soundcard`-overlay levert daarmee stilte of fouten op. Het staat
open als issue bij Raspberry Pi zelf en er is nog geen werkende configuratie
gepubliceerd. Op een Pi 3 en een Zero 2 W werkt exact dezelfde opstelling wel.

Dus:

| Pi | Microfoon |
|---|---|
| Zero 2 W (of Pi 3/4) | **INMP441 op I2S** — aansluitschema hieronder |
| **Pi 5** | **USB**, want I2S-capture werkt daar niet |

#### Op een Pi 5: welk USB-geluidskaartje

Waar het om draait is de **C-Media CM108, CM108B of CM119**. Die chips zitten in
vrijwel elk goedkoop USB-geluidsdongeltje en hebben géén automatische
versterkingsregeling of ruispoort in hardware. Wat er wel is, is een
ALSA-schakelaar "Auto Gain Control" die je gewoon uitzet. Dat is precies het
verschil met een kant-en-klare USB-vergadermicrofoon, waar die bewerking in de
firmware zit en niet uit kan.

| Optie | Wat | ~Prijs |
|---|---|---|
| **A. USB-dasspeldmicrofoon** | Eén onderdeel: dezelfde soort chip in de USB-stekker, met een gewone electret aan een kabeltje. Precies de goede opzet, maar dan voorgemonteerd. | €8-10 |
| B. dongle + 3,5 mm lavalier | Los USB-geluidskaartje met een aparte dasspeldmicrofoon erin. Zelfde resultaat, twee onderdelen. | €10 |
| C. dongle + losse capsule | Je soldeert zelf een electret aan een 3,5 mm plug. Goedkoopst, wel soldeerwerk. | €6 |
| D. USB-audio-interface | Behringer UMC22 of vergelijkbaar. Echt schone omzetters, maar log en duur. Alleen zinvol als je ooit alsnog de phono-lijn wil aftakken. | €35 |

**Aanbeveling: A, een gewone USB-dasspeldmicrofoon van onder de tien euro.**
Eén stekker, capsule aan een kabeltje dat je vlak achter de akoestische opening
legt, en geen soldeerwerk. Dat het als spraakmicrofoon verkocht wordt is hier
geen bezwaar:

- **Omnidirectioneel is precies goed.** Een dasspeldmicrofoon vangt de hele
  kamer op, en dat is wat we willen — geen smalle bundel op één punt.
- **De kleuring van de frequentiekromme valt weg tegen zichzelf.** Lavaliers
  zijn vaak afgestemd op spraak, maar referentie en query lopen door dezelfde
  microfoon. Precies hetzelfde argument als bij de kamerakoestiek en de
  plateausnelheid.

Let op bij dit type: **neem USB-A** (dat heeft de Pi 5), en blijf weg bij
*draadloze* dasspeldsets met een zender en ontvanger — die hebben compressie en
automatische versterking in het draadloze pad zitten en zijn daarmee onbruikbaar.

**Blijf weg bij** USB-vergadermicrofoons (Anker PowerConf, eMeet, Jabra), de
ReSpeaker USB Mic Array en alles met "AI-ruisonderdrukking" op de doos. Die doen
bundelvorming en ruisonderdrukking in firmware, en dat is niet uit te zetten.

#### Waar je op let bij het bestellen

Het exacte chipnummer is minder belangrijk dan deze drie:

1. **Een aparte microfooningang.** De goede uitvoering heeft **twee** 3,5
   mm-aansluitingen: groen voor koptelefoon uit, roze voor microfoon in. Er
   bestaan ook dongeltjes met alleen uitgang — daar heb je niets aan. En een
   variant met één gecombineerde aansluiting (TRRS) werkt wel, maar dan moet je
   dasspeldmicrofoon ook een TRRS-plug hebben, anders komt de capsule op de
   verkeerde ring uit.
2. **Class-compliant, geen driver.** Alles in deze prijsklasse is dat, maar als
   er een cd-tje of een download bij zit is dat een waarschuwing.
3. **Geen "ruisonderdrukking" of "AI" in de omschrijving.** Dat is precies de
   firmwarebewerking die we niet willen.

"7.1 virtueel surround" op de doos is geen bezwaar; dat is een softwaretruc voor
de uitgang en raakt de microfooningang niet.

#### De echte controle duurt vijf minuten

Na aansluiten:

```bash
amixer -c 1 controls
```

Zie je daar een gewone `Mic`-regelaar en een `Auto Gain Control`-schakelaar, dan
is het het juiste soort chip en zet je die laatste uit. Zie je alleen een
apparaat zonder regelaars, dan doet de firmware zelf iets en kun je hem beter
terugsturen. Voor vijf tot acht euro is dat een goedkope test.

Instellen en controleren:

```bash
arecord -l                                    # welke kaart is het
amixer -c 1 controls                          # welke regelaars zijn er
amixer -c 1 sset 'Auto Gain Control' off      # deze uit
amixer -c 1 sset 'Mic' 80%
arecord -D plughw:1,0 -f S16_LE -r 44100 -c 1 -d 10 test.wav
```

Op forums lees je dat het niveau met AGC uit aan de lage kant is. Voor ons is
dat geen probleem: de fingerprinter werkt met een **relatieve** drempel — hij
trekt het lokale ruisniveau eraf en kijkt hoever een piek daarboven uitsteekt.
Een wat zacht maar schoon signaal is prima; wat herkenning sloopt is een
pompende AGC en weggefilterde ruis, niet een lage versterking.

Wat je verliest ten opzichte van I2S is dus niet de ruwheid van het signaal maar
de elegantie: een dongeltje in plaats van zes draadjes.

#### Aansluitschema INMP441 (alleen bij een Zero 2 W of Pi 3/4)

> **Niet van toepassing op wat je gebouwd hebt.** Het is een Pi 5 geworden met
> de USB-dasspeldmicrofoon, en dan wordt er niets gesoldeerd. Zie
> [bedrading.svg](bedrading.svg): drie USB-kabels en verder niets. Dit schema
> blijft staan voor het geval er ooit alsnog een Zero 2 W in gaat.

```
INMP441        Pi
-------        ----------
VDD  --------- 3V3   (pin 1)
GND  --------- GND   (pin 6)
SCK  --------- GPIO18 (pin 12, PCM_CLK)
WS   --------- GPIO19 (pin 35, PCM_FS)
SD   --------- GPIO20 (pin 38, PCM_DIN)
L/R  --------- GND    (kies het linkerkanaal)
```

In `/boot/firmware/config.txt`: `dtparam=i2s=on` met de
`googlevoicehat-soundcard`-overlay. Twee dingen bij het eerste opnemen: de Pi
neemt op in stereo met één stil kanaal (neem het linker), en in 32-bits formaat
waarvan de werkelijke data in de bovenste bits zit.

### Voeding: het scherm kán via de Pi 5 (5, 6)

Ja — en dat maakt het netter dan de twee losse laders die hier eerst stonden.
Maar het hangt aan de voeding die je kiest.

De Pi 5 begrenst zijn USB-poorten standaard op **600 mA samen**. Dat is te
krap voor het CrowPanel, dat 5 V/1 A vraagt. Die grens gaat automatisch naar
**1,6 A** zodra de Pi met een USB-PD-voeding 5 V bij 5 A heeft onderhandeld —
in de praktijk de officiële 27 W-adapter van Raspberry Pi.

Dus: **neem die officiële adapter**, geen generieke 5 V/3 A-lader. Dan wordt het:

```
27 W USB-C PD  --->  Pi 5  --USB-A naar JST MX1.25-->  CrowPanel
```

Eén stekker in het stopcontact, één kabel naar het scherm.

Er zit een tweede voordeel aan: die kabel draagt **ook data**. Uit Elecrow's
schema blijkt dat `USB-5V-IN` niet alleen voeding is maar een echte
USB-verbinding — D− en D+ lopen via R43/R44 rechtstreeks naar `GPIO19/USB_D−`
en `GPIO20/USB_D+` van de ESP32-S3, en er zit geen CH340 of CP2102 tussen. Het
is dus de native USB van de chip zelf, en de twee praten er meteen over met
elkaar. Daarmee vervalt de wifi-koppeling
tussen de twee apparaten volledig — geen IP-adressen die veranderen, geen
router die ertussen kan zitten, en één minder faalpunt. Alleen de Pi hoeft nog
op het netwerk voor Shazam en Discogs.

Lukt de officiële adapter niet, dan kun je `usb_max_current_enable=1` in
`config.txt` zetten om de grens alsnog op te trekken — maar dan moet je voeding
die 1,6 A ook echt kunnen leveren, anders val je onder belasting om.

### Als de Zero 2 W niet leverbaar is

Dat gebeurt regelmatig. Een Pi 5 als tijdelijke vervanger werkt prima — het is
een kaal brein, en alles in het ontwerp blijft hetzelfde: INMP441 op I2S,
dezelfde software, dezelfde rolverdeling met het CrowPanel.

Mijn eerdere bezwaar tegen de Pi 5 was **specifiek de ventilator naast de
microfoon**, en dat is minder hard dan ik het bracht. De belasting hier is een
paar seconden rekenwerk per plaat en verder niets. De officiële koeler van de
Pi 5 wordt PWM-geregeld en staat bij die belasting vrijwel altijd stil; een
fatsoenlijk passief koellichaam volstaat waarschijnlijk ook. Alleen bij continue
zware belasting is een draaiende ventilator onvermijdelijk, en dat scenario
hebben we niet.

Wat er wél verandert:

- **Voeding wordt USB-C.** De Pi 5 vraagt officieel 5 V/5 A voor volledige
  randapparatuur; zonder USB-apparaten loopt hij prima op 5 V/3 A. Wij hangen
  er niets aan, dus dat is geen probleem — maar de kabel en de poort veranderen.
- **Groter: 85×56 mm** tegenover 65×30, dus breder dan het CrowPanel (79 mm).
- **Controleer de I2S-overlay.** De GPIO van de Pi 5 loopt via de RP1-chip, en
  device tree-overlays voor I2S-audio zijn daarvoor aangepast. Het zou moeten
  werken op een actueel OS, maar controleer het bij het opzetten — net als bij
  het HyperPixel-verhaal is de RP1-architectuur het punt om op te letten.
- **Meer sluimerverbruik**: ~3 W tegen ~0,7 W. Voor een apparaat dat dag en
  nacht aanstaat is dat ~26 kWh per jaar in plaats van ~6.

#### De Pi 5 met 1 GB is hier een prima keuze

Die variant is recent toegevoegd voor $45, als antwoord op de sterk gestegen
geheugenprijzen. Voor dit project pakt hij goed uit:

- **1 GB is het dubbele van de Zero.** Na het OS en Python houd je ~650 MB over
  voor de fingerprint-index, tegen ~150 MB op een Zero. Dat is genoeg voor zo'n
  200 albums op 1 op 4, of 400 op 1 op 8 — een groot deel van de ambitie om de
  lokale database het hoofdmechanisme te maken komt daarmee alsnog binnen bereik.
- **Quad-core Cortex-A76 op 2,4 GHz** tegen de A53 op 1 GHz van de Zero. Het
  matchen dat op een Zero traag zou zijn, gaat hier vlot.
- **Dual-band wifi**, dus het 2,4 GHz-voorbehoud van de Zero vervalt. Het
  CrowPanel blijft wel 2,4 GHz-only.

Het is dus meer dan een noodgreep; als de Zero schaars blijft, is dit gewoon het
betere bordje. Je betaalt met formaat, sluimerverbruik en prijs.

**Als het tijdelijk is: ontwerp de sokkel er niet omheen.** Zet de elektronica
op de Pi 5 op tafel, krijg de software werkend, en print de behuizing pas als je
weet welk bordje er definitief in gaat. Dat past ook bij de fasering in
[PLAN.md](PLAN.md), waar de sokkel sowieso pas na de bediening komt.

### Waarom de Zero en geen Pi 4

**De Zero 2 W.** Een Pi 4 is even overwogen, maar de reden ervoor hield geen
stand.

Dat argument was RAM voor de fingerprint-index. Maar bedenk wat er werkelijk in
die database komt: **alleen de platen die Shazam níet herkent.** Uit de webproef
bleek dat hij vrijwel alles pakt, dus dat is een handvol tot enkele tientallen
kanten — geen complete platenkast.

| Wat er in de database komt | Geheugen (1 op 4) |
|---|---|
| 25 kanten die Shazam mist | ~37 MB |
| 50 kanten | ~73 MB |
| 200 kanten (somber scenario) | ~292 MB, met 1 op 8 nog ~146 MB |

Daar komt bij: de SD-kaart is de opslag, het geheugen alleen de werkindex. Dat
is sowieso de juiste indeling, ongeacht welke Pi. Bij het opstarten inlezen,
daarna in RAM doorzoeken.

Verbruik van 512 MB samen: OS Lite 64-bits 80-120 MB, Python met numpy 60-80 MB,
hoesjes in beeld 20-40 MB, de index 40-75 MB, en shazamio tijdens het rekenen
kortstondig 50-100 MB. Samen ~350 MB. Het past, zonder ruimte te verspillen.

En verder pleit alles voor de Zero: 65×30 mm verdwijnt volledig onder het
CrowPanel, hij trekt 0,7 A in plaats van 1,2 A, heeft geen koellichaam nodig, en
de twee HDMI-poorten, vier USB-poorten en de ethernetaansluiting van een Pi 4
zijn hier dood gewicht.

**Geen ventilator, en dat is geen detail.** Een Pi 5 vraagt actieve koeling, en
die zou in een dichte sokkel centimeters naast de microfoon komen te zitten. Je
voegt dan een continue breedbandige ruisbron toe aan een apparaat waarvan de
hoofdtaak luisteren is.

#### Als de database ooit tóch groot wordt

Dan hoef je niet naar een grotere Pi. Zoeken in twee trappen lost het op:

1. Houd een **grove index** in het geheugen — bijvoorbeeld één op de 32 hashes.
   Voor achthonderd kanten is dat ~40 MB. Die is te grof om mee te beslissen,
   maar ruim genoeg om een lijstje van tien kandidaat-kanten op te leveren.
2. Lees alleen van **die kandidaten** de volledige hashes van de SD-kaart, en
   doe daarmee het echte uitlijnen.

Dat werkt omdat stap 2 per kant een aaneengesloten stuk bestand is: sequentieel
lezen, waar een SD-kaart goed in is. De naïeve aanpak — de hele index op schijf
laten staan en er willekeurig in zoeken — zou juist stuklopen, want dan doe je
tienduizenden losse leesacties op iets dat daar traag in is.

Bijkomend: een index die van schijf komt betekent meer leesacties, wat het
advies hieronder over een High Endurance-kaart en logs naar tmpfs alleen maar
zwaarder maakt.

### De SD-kaart: A1, niet A2 (3)

Tegen de intuïtie in, en het is een Pi-eigenaardigheid.

A1 en A2 zijn snelheidsklassen voor willekeurige toegang: A1 belooft 1500
lees-IOPS, A2 belooft er 4000. Maar **A2 haalt dat met command queuing, en de
SD-controller van de Raspberry Pi ondersteunt dat niet.** Een A2-kaart valt daar
terug op gewoon gedrag en presteert in de praktijk gelijk aan of soms zelfs
slechter dan een A1-kaart — terwijl hij meer kost.

Dus: **A1**. Heb je al een A2 liggen, gebruik hem gerust; hij is niet slechter,
alleen zonde van het geld.

Wat wél uitmaakt voor dit apparaat:

- **Merk boven klasse.** SanDisk, Samsung of Kingston bij een betrouwbare
  verkoper. Namaak-SD-kaarten zijn een plaag, en die falen juist bij een
  apparaat dat continu aanstaat.
- **"High Endurance"** (bedoeld voor dashcams) is hier zinniger dan snel. Deze
  Pi draait dag en nacht en schrijft logs.
- **16-32 GB is ruim voldoende.** Groter helpt niets; de fingerprint-cache blijft
  in de honderden megabytes.
- **Schrijfacties beperken scheelt meer dan welke klasse ook.** Logs naar tmpfs,
  swap uit, en overweeg een read-only root. Dat verlengt de levensduur van een
  kaart aanzienlijk meer dan een hogere klasse.

### Ballast en voetjes (8, 9)

Het CrowPanel weegt 80 gram. Dat is licht voor iets waar je aan gaat draaien:
zonder maatregelen schuift het over je bijzettafel. De geprinte sokkel is dan
ook geen doos maar een **gewicht**: ontwerp er een holte in voor ~300 g moeren
of ringen, en zet er vier antislipvoetjes onder.

Dat lost meteen het zwakste punt van deze route op. Die ingebouwde encoder is
klein en licht, en een zware sokkel eronder maakt merkbaar verschil in hoe het
geheel aanvoelt.

### De akoestische opening

De microfoon zit in de sokkel, dus er moet een gaatje in de wand met de capsule
er vlak achter, niet stijf vastgelijmd. Richt hem de kamer in, niet naar
beneden.

### Wat je nog moet uitzoeken

- **Hoe die ingebouwde knop draait.** Vrijwel zeker met detents, en dat is
  precies wat je niet wilde. Dit is de reden om het CrowPanel als eerste te
  bestellen en er een avond mee te spelen voordat je de rest koopt.
- **Of de encoder softwarematig te temmen is.** De detents zitten mechanisch in
  de encoder, maar je kunt wel de stapgrootte per klik instellen — dezelfde
  `encDivider`-gedachte als in versie 1.

Zie [../BOM.md](../BOM.md) voor de onderdelen van versie 1, die apart blijft
werken.
