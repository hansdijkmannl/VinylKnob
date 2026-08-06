# Luxe versie — ontwerpnotities

Idee: een rond touchscreen (Pimoroni **HyperPixel 2.1" Round**, 480×480 IPS met
capacitieve touch) met daaromheen een **draairing** die via tandwielen een
detentloze encoder aandrijft. Het scherm toont het volume, wat er draait,
en je hele platenkast om doorheen te bladeren. Een microfoon herkent welke plaat
er op staat, zodat de unit gewoon bij de bank kan blijven staan.

Onderdelen staan in [../v2/BOM.md](../v2/BOM.md), bouwvolgorde in
[../v2/PLAN.md](../v2/PLAN.md).

Dit document is de analyse vooraf, niet de bouwbeschrijving. De simpele versie
(zie [../README.md](../README.md)) blijft gewoon staan en werkt zelfstandig.

---

## De ring

De ring drijft via geprinte tandwielen een **detentloze rotary encoder** aan.
Geen potmeter, geen motor.

### Waarom geen potmeter

Een potmeter is absoluut: zijn hoek *is* het volume. Aantrekkelijk, tot iemand
de afstandsbediening pakt — dan klopt de stand van de ring niet meer met de
werkelijkheid. Dat is op te lossen met een motor die hem terugdraait, maar dat
kost een H-brug, een gesplitste voeding, een dode zone in de software tegen
speling, en het verbod om op te nemen terwijl de motor loopt (die zit
centimeters van de microfoon).

Er is een eenvoudiger argument, en het is doorslaggevend: **de volumeknop van de
SR7015 draait zelf ook niet mee met de afstandsbediening.** Dat is een oneindige
encoder. Onze ring hoort zich net zo te gedragen als de knop van het apparaat
dat hij bedient — anders bouw je een ding dat zich anders voelt dan de rest van
de installatie.

En het scherm zit precies in het midden van de ring. De volumeboog loopt langs
de rand, exact waar je vingers liggen. Díe boog is je standaanwijzer; daar heb je
geen absolute potmeter voor nodig.

Wat een encoder bovendien meebrengt: **geen eindaanslagen**. Een potmeter draait
~270° en houdt dan op. Voor een volumeknop is dat te verdedigen, maar oneindig
doordraaien is gewoon prettiger.

### De overbrenging

Geprinte rechte tandwielen, module 0,5-0,8: een binnentanding aan de binnenzijde
van de ring en een rondsel op de as van de encoder.

De verhouding volgt uit de geometrie. Een rondsel van 15-25 mm tegen een
binnentanding van ~70 mm geeft 3 tot 4,5:1. Met een encoder van 24 pulsen per
omwenteling levert dat 290 tot 430 quadratuur-stappen per ringomwenteling. De
`encDivider`-instelling uit versie 1 trimt dat daarna naar smaak — die knop zit
er al.

**Speling in de tanding is hier onschuldig.** Je meet alleen verandering, geen
absolute stand, dus bij het omkeren van de draairichting kost het je hooguit een
fractie van een graad. Dat was bij een potmeter met motorregeling wél een
probleem; nu niet meer.

Neem een **detentloze** encoder. Met de overbrenging erbij zou je anders 100 tot
150 klikjes per ringomwenteling voelen, en dat is precies het rammelige gevoel
dat we willen vermijden.

### Optisch had ook gekund, maar

Eerder gaf ik de voorkeur aan optisch aftasten: een meegeprinte ring met
zwart-witte segmenten en twee reflectiesensoren. Op je H2S met meerkleurendruk
is dat één printje, en het is contactloos.

Er zit alleen een maatprobleem in dat ik toen over het hoofd zag. Voor
quadratuur moeten de twee sensoren een **kwart segmentsteek** uit elkaar staan.
Met 120 segmenten op een ring van 70 mm is de steek 1,8 mm, dus een kwart is
0,45 mm — en een TCRT5000 is tien millimeter breed. Je kunt ze wel op *n plus
een kwart* steek zetten, maar dan is de plaatsingsnauwkeurigheid nog steeds een
paar tiende millimeter. Een tandwieltrein is een stuk vergevingsgezinder.

Optisch blijft de mooiere oplossing als de tandwielen je gaan irriteren. Begin
met de tandwielen.

### Massa en demping

De potmeter bracht zijn eigen demping mee; een encoder doet dat niet. Dus komt
de regelbare wrijving terug — en die is nu het enige dat het gevoel bepaalt:

- **Massa in de ring.** Een geprinte ring van 25 g voelt als speelgoed. Groef
  aan de binnenkant, stalen ring of M8-moeren erin, mik op 150-250 g.
- **Regelbare wrijving.** Een vilt- of PTFE-ring tussen de ring en het vaste
  deel, met de voorspanning instelbaar via drie schroefjes. Reken op een paar
  iteraties; dit is de parameter die je pas met het ding in je hand vindt, en je
  wil hem kunnen bijstellen zonder alles te slopen.
- **Vet in het lager.** Dikker lagervet geeft een merkbaar rijkere loop. Klein
  effect, maar gratis.

### Lager

Een dunwandig groefkogellager **6813** (65 mm binnen, 85 mm buiten, 10 mm dik)
valt ruim om een display van 71 mm heen. Goedkoper alternatief dat verrassend
goed werkt: een geprinte loopbaan met losse 3 mm airsoft-balletjes ertussen.

### Wie leest het uit

De **ESP32-C3**, met de quadratuur-decoder uit versie 1 ongewijzigd. Diezelfde
C3 draagt ook de microfoon en praat over één USB-verbinding met de Pi. Dat is
niet alleen taakverdeling maar noodzaak: de HyperPixel laat nauwelijks GPIO over
op de Pi.

---

## Architectuur: drie routes

Sinds de CrowPanel in beeld kwam zijn er drie manieren om dit te bouwen. De
onderste is nieuw en waarschijnlijk de beste.

### A. Pi + HyperPixel, alles in één

Wat er oorspronkelijk stond. Pi Zero 2 W met een HyperPixel 2.1" Round, een
ESP32-C3 voor de encoder en de microfoon, en zelfgebouwde ring met tandwielen en
lager. ~€140 en het meeste mechanische werk.

### B. Alleen een CrowPanel

**Elecrow CrowPanel 2.1" ESP32 Rotary Display**: ESP32-S3R8 met 8 MB PSRAM en
16 MB flash, rond IPS-scherm van 480×480 met capacitieve touch, ingebouwde
rotary encoder, in een behuizing van aluminium en acryl (79×79×30 mm, 80 g).
Rond de €35-40.

Dat vervangt display, computer, encoder, lager, tandwielen en behuizing in één
klap. Maar het kost twee dingen: er is geen gedocumenteerde vrije GPIO voor een
I2S-microfoon (alleen UART, I2C en een 12-pins FPC), en **shazamio draait niet
op een ESP32** — dat is Python met een Rust-kern. Je zit dan vast aan de
AudD-API, met een sleutel en kosten na het gratis niveau.

### C. CrowPanel + een kale Pi Zero ernaast — **gekozen**

De combinatie, en de meeste problemen verdwijnen erdoor:

| Doet | Wat |
|---|---|
| **CrowPanel** | scherm, knop, touch, telnet naar de AVR, de hele bediening |
| **Pi Zero (headless)** | USB-microfoon, shazamio, lokale fingerprint-database, Discogs, de webinterface met de koppelwachtrij |

Ze praten over het netwerk, of over de UART-connector van het CrowPanel.

De reden dat dit beter uitpakt dan route A: **de Pi hoeft geen scherm meer aan
te sturen.** Daarmee vervalt in één keer het GPIO-probleem van de HyperPixel, de
noodzaak van een tweede microcontroller voor de encoder, en het feit dat je
dertig seconden naar een opstartend Linux zit te kijken — het CrowPanel is
meteen aan, en de Pi start op de achtergrond op.

En de microfoon: omdat er geen display meer op de Pi zit, is de hele 40-pins
header vrij. Dus geen USB-dongeltje maar een **INMP441 op I2S** — rauwe PCM
zonder de verborgen versterkingsregeling en ruisonderdrukking die goedkope
USB-microfoons in hardware hebben zitten. Precies de bewerking die we in de
webproef expliciet uitzetten omdat ze herkenning schaadt.

Kosten: CrowPanel €40 + Pi Zero €22 + SD-kaart €8 + USB-microfoon €5 ≈ **€75**,
tegen €140 voor route A. En het mechanische werk is nul.

Wat je opgeeft is het knopgevoel: die ingebouwde encoder is klein, licht en
vrijwel zeker gedetenteerd. Dat is precies waar dit project om begonnen is, dus
het is geen detail — maar het is wel iets wat je met een geprinte ring eromheen
deels kunt bijsturen, en anders bouw je alsnog je eigen ring tegen een display
dat je dan al kent.

### De keuze

**Route C.** Meer mogelijkheden, shazamio blijft binnen bereik, geen API-sleutel
nodig, en de lokale fingerprint-database blijft mogelijk als cache.

Wat nu nog uitgezocht moet worden is niet de architectuur maar het gevoel:
**koop eerst alleen het CrowPanel** en voel hoe die ingebouwde knop draait.
Veertig euro tegenover een half ontwerp is geen gok, en je kunt er meteen fase 2
mee bouwen zonder één beslissing over de Pi te nemen.

---

## Platformkeuze: Pi of ESP32

De HyperPixel dwingt een Raspberry Pi af — het is een DPI-display dat op de
40-pins header zit. Dat is geen kleine keuze.

### Let op: de HyperPixel eet je GPIO op

DPI-displays gebruiken vrijwel alle GPIO-pinnen van de Pi. Wat er overblijft
voor twee encodersensoren is minimaal tot niets. **Controleer de pinout van de
2.1" Round voordat je iets bestelt.**

De robuuste oplossing is er niet omheen werken maar eromheen ontwerpen: laat de
**ESP32-C3 die je al hebt** de ring uitlezen en de tellingen over USB-serieel
naar de Pi sturen. Dat kost een paar euro aan niets, geeft je een gegarandeerd
strakke interrupt-timing, en de Pi hoeft alleen nog te tekenen en te praten met
de receiver.

### Welke Pi: de Zero 2 W komt terug in beeld

De geheugenberekening die eerder naar een Pi 4 met 4 GB leidde, kwam volledig
voort uit de lokale fingerprint-index. Nu die een cache is in plaats van het
hoofdmechanisme, valt dat beslag weg en past het geheel in **512 MB**:

| | |
|---|---|
| Raspberry Pi OS Lite, 64-bits, geen desktop | 80-120 MB |
| Python met pygame en Pillow | 60-80 MB |
| Hoesafbeeldingen in beeld (rest op schijf) | 20-40 MB |
| Audiobuffer van 8 s | verwaarloosbaar |
| Eventueel een cache van ~50 vaak gedraaide kanten | ~37 MB |
| **samen** | **~250-300 MB** |

En qua formaat is de Zero duidelijk de betere: 65×30 mm, dus hij verdwijnt
volledig achter een display van 71 mm. Met de ring eromheen wordt het geheel een
puck van zo'n 90-95 mm. Een Pi 4 past er ook achter, maar is dikker door zijn
connectoren en vraagt koeling.

Drie dingen die je dan wel moet regelen:

**Raspberry Pi OS Lite, 64-bits.** Niet de desktopversie: een X11- of
Wayland-sessie erbij trekt de Zero leeg. En 64-bits omdat shazamio een
Rust-extensie heeft — controleer vooraf of daar aarch64-wheels van zijn, want
zelf compileren op een Zero is geen pretje.

**De UI rechtstreeks op KMS/DRM.** Pygame op het framebuffer, geen browser en
geen desktop. 480×480 is maar 230.000 pixels; dat trekt een Zero 2 W prima,
mits je hoesjes vooraf op maat schaalt en op schijf cachet in plaats van ze bij
elke frame te verkleinen.

**Eén USB-apparaat, want de microfoon gaat op de C3.** Die heeft een
I2S-peripheral en GPIO genoeg, dus een INMP441 erop, en hij stuurt audio én de
encoderstand over dezelfde USB-verbinding naar de Pi. 16 kHz mono is 32 kB/s,
ruim binnen wat USB CDC op een C3 aankan.

Dat scheelt een USB-hub in de behuizing — de Zero heeft maar één datapoort — en
het bordje zit er toch al voor de encoder. De microfoon zit dan wel binnen in de
doos, dus er moet een akoestische opening in de wand.

Beslis dit pas als je weet welke platen Shazam *niet* herkent. Blijkt daar een
serieuze lokale database voor nodig, dan komt de geheugenvraag terug en zit je
alsnog aan 2 of 4 GB.

### De vergelijking

| | Pi + HyperPixel | ESP32-S3 met rond touchscreen onboard |
|---|---|---|
| Wat het is | los display op een Linux-computertje | kant-en-klaar bordje, bv. de Waveshare *ESP32-S3-Touch-LCD-2.1* (480×480 rond) — verifieer de specs |
| Kosten | ~€100 (display €60-70, Pi Zero 2 W €20, SD €8) | ~€35-45 |
| Aan na stroom | 25-40 s opstarten op een Zero | direct |
| Onderhoud | OS-updates, SD-kaartcorruptie (zet root read-only!) | geen |
| GPIO voor de ring | vrijwel niets over, extra MCU nodig | ruim voldoende |
| UI bouwen | Python + pygame, of LVGL — snel en vertrouwd | LVGL in C, mooier resultaat maar meer werk |
| Extra's | de muziekherkenning kan lokaal op hetzelfde bordje draaien | herkenning moet naar een dienstje elders in huis |

**Als de knop alleen input en volume doet: het ESP32-S3-bordje.** Een
volumeknop die 25 seconden moet opstarten en waar een SD-kaart in kan
corrumperen is een computer, geen apparaat.

**Wil je de muziekherkenning erbij: de Pi.** Dan draait de fingerprint-database
op hetzelfde bordje als het scherm, hoeft er geen audio het netwerk over, en heb
je Python voor zowel de UI als de matching. Dat is het enige echte argument voor
de Pi, maar het is een goed argument.

---

## Luisteren met een microfoon

De unit staat bij de bank en moet daar kunnen blijven staan: geen kabels naar de
platenspeler, geen Y-splitter, geen losse phono-voorversterker. Hij luistert
gewoon naar de kamer, net als een telefoon-app.

Ik heb daar eerder tegenin gebracht dat een microfoon op de verkeerde plek zit
en alles hoort. Dat eerste bezwaar vervalt bij nader inzien grotendeels, en het
tweede is oplosbaar — met iets dat we al hebben.

### Waarom dit beter uitpakt dan ik dacht

**De metingen zijn er al.** De herkenner in [../v2/recognizer/](../v2/recognizer/)
haalde het foutloos tot 20 dB signaal-ruisverhouding, en gaf bij 10 dB nog
steeds de goede plaat mét de exacte tijdpositie. Een telefoon op drie meter van
een set luidsprekers zit rond de 15-25 dB. Dat is precies het gebied dat al
gemeten is. Shazam werkt in een kroeg; dit is een living room.

**Kamerakoestiek valt weg tegen zichzelf.** Het argument dat vinyl-tegen-vinyl
beter matcht dan vinyl-tegen-master wordt hier nog sterker: de referentie is
opgenomen met dezelfde microfoon, in dezelfde kamer, op dezelfde plek, door
dezelfde luidsprekers. Alle vervorming van dat pad zit in beide opnames en valt
tegen elkaar weg — net als de snelheidsafwijking van het plateau.

Wel een gevolg: **verzet je de unit, dan verandert de akoestiek.** Opnieuw
vastleggen is goedkoop, maar het is geen apparaat dat je elke week verplaatst.

**Het "hij hoort alles"-probleem lost de AVR zelf op.** We zijn al over telnet
verbonden en weten daardoor precies of de ingang op phono staat, of de zone aan
is, of er niet gedempt is, en hoe hard het staat. Alleen als dat allemaal klopt
gaat de microfoon aan. Praten tijdens het luisteren blijft ruis, maar dat is
juist het geval dat 10-20 dB heet en dat gemeten is.

### Wat je nodig hebt

Een **USB-microfoon**. Dat is geen voorkeur maar een gevolg: alles wat over de
40-pins header of over I2S gaat, botst met de HyperPixel.

**Een ReSpeaker 2-Mics Pi HAT kan dus niet.** Die is een HAT: hij gaat op
dezelfde header staan waar de HyperPixel op moet, en gebruikt bovendien I2S plus
I2C voor zijn codec — precies de pinnen die het DPI-display opeist. Mechanisch
en elektrisch allebei uitgesloten. Hetzelfde geldt voor een losse
I2S-MEMS-microfoon als de INMP441.

Een simpel USB-dongeltje met een electret-capsule voldoet, en dat is minder een
compromis dan het lijkt: **de kwaliteit van de microfoon doet er voor herkennen
nauwelijks toe.** De referentie en de query lopen door dezelfde microfoon, dus
elke kleuring van dat pad valt tegen zichzelf weg — net als de kamerakoestiek en
de snelheid van het plateau. En we werken sowieso op 11 kHz mono. Waar het wél
om gaat is dat het altijd dezelfde microfoon op dezelfde plek is.

Twee praktische dingen voor de behuizing:

- **Een akoestische opening.** De microfoon mag niet in een dichte geprinte doos
  zitten. Een gaatje aan de voorkant, capsule er vlak achter, en niet stijf
  vastgelijmd aan de wand.
- **Geen motorgeluid om rekening mee te houden.** Dat was een zorg toen de ring
  nog een gemotoriseerde potmeter aandreef; met een encoder beweegt er niets uit
  zichzelf.

Voor "er speelt iets" is geen apart circuit meer nodig — het energieniveau van
de microfoonopname is genoeg, zolang je hem combineert met de toestand die de
AVR al meldt. Blijft dat niveau twintig tot dertig seconden laag terwijl phono
geselecteerd is en de zone aan staat, dan is de kant afgelopen.

---

## Herkenning — alleen om er iets moois mee te tonen

Doel is niet een tracklist, maar **hoesje of artiest op het scherm**. Een mooi
beeld dat hoort bij wat er draait. Dat scheelt enorm veel: je hoeft alleen het
**album** te herkennen, niet welk nummer erop loopt. Eén match per kant, geen
tijdlijn, geen nummergrenzen — precies het deel dat lastig is valt weg.

### De database is het probleem, niet het algoritme

Shazam's aanpak is goed gedocumenteerd en er is open source die het doet
(**Dejavu**, Python). Wat je niet hebt is hun database van tientallen miljoenen
nummers, en een officiële Shazam-API bestaat niet.

Maar die database heb je ook niet nodig: je hoeft alleen **jouw platenkast** te
herkennen. Een paar honderd albums. Op zo'n zoekruimte is matchen triviaal,
snel en volledig offline.

### Discogs sluit de cirkel

Als je je collectie in **Discogs** hebt staan, heb je de catalogus al. Discogs is
de enige bron die je *persing* kent — inclusief de juiste hoesafbeelding, wat bij
heruitgaven en speciale edities precies het verschil maakt. MusicBrainz met het
Cover Art Archive is het open alternatief.

Praktisch: Discogs werkt met een **personal access token** (geen OAuth-dans
nodig), staat 60 aanvragen per minuut toe, en **eist een eigen User-Agent-header**
— zonder die header weigert de API je botweg. Haal de collectie op via
`/users/{gebruiker}/collection/folders/0/releases`, gepagineerd. Cache de
hoesafbeeldingen lokaal in plaats van ze bij elke weergave op te halen.

### Getoetst: het werkt

**Gemeten op 31 juli 2026** met [../v2/webtest/](../v2/webtest/README.md):
muziek van een iPhone-luidspreker, opgevangen door de microfoon van een
MacBook, herkende in **8 seconden vrijwel alles** — met hoes, artiest, album.

Dat is belangrijker dan het lijkt, want het ruimt twee zorgen op die het hele
ontwerp stuurden:

- **Een kamermicrofoon is genoeg.** Geen aftakking op de phono-lijn, geen
  losse voorversterker, geen kabels naar de platenspeler.
- **Persingsverschillen zijn minder erg dan gedacht.** Ik had beredeneerd dat
  vinyl slecht zou matchen tegen een digitale master. In de praktijk gaat het
  goed. Dat argument voor een eigen lokale database is daarmee zwakker
  geworden.

En de echte opstelling is *makkelijker* dan de test: een Marantz met fatsoenlijke
luidsprekers geeft de microfoon meer om mee te werken dan een
telefoonspeakertje.

### Wat dit betekent voor de lokale database

De eigen fingerprint-database in `../v2/recognizer/` was bedoeld als het
hoofdmechanisme. Hij zakt nu naar een **cache**: leuk om niet elke keer het
netwerk op te hoeven en om offline te blijven werken, maar niet meer
noodzakelijk om überhaupt iets te herkennen.

Dat heeft een concreet gevolg voor de hardware. De hele geheugenberekening die
naar een Pi 4 met 4 GB leidde, kwam voort uit die lokale index. Zonder — of met
alleen een cache van platen die je vaak draait — komt een kleinere Pi weer in
beeld. **Beslis dat pas als je weet welke platen Shazam níet herkent**, want
precies daar verdient een eigen database zijn plek.

### Belangrijke beperking: vraag alleen bij verandering

shazamio is een onofficiële client op Shazam's eigen endpoints, zonder sleutel.
Voor een paar opzoekingen per dag is dat onopvallend; ga je elke vijftien
seconden vragen, dan zit je op honderden verzoeken per dag en loop je kans dat
het wordt afgeknepen. Bovendien is het een omgekeerd-ontworpen client die
zomaar kan breken bij een wijziging aan hun kant.

Dus: **niet op een timer opvragen, maar bij een gebeurtenis.** De AVR vertelt
over telnet wanneer de ingang op phono gaat, en het microfoonniveau vertelt
wanneer er na stilte weer geluid begint. Dat zijn de twee momenten waarop je
één keer vraagt — een handvol opzoekingen per avond in plaats van honderden.

### Koude start: één keer vragen, daarna zelf weten

Het zwakke punt van een zelflerende database is dat je elke plaat één keer
handmatig moet taggen. Dat lossen de bestaande herkenningsdiensten op:

1. Onbekende kant begint te spelen → **één** aanroep naar een herkenningsdienst.
2. Antwoord (artiest + album) → opzoeken in je Discogs-collectie → hoesje.
3. Fingerprint van die kant lokaal opslaan, gekoppeld aan die release.
4. Elke volgende keer: directe lokale match, geen aanroep meer.

Dat is **één API-aanroep per nieuwe plaat, ooit**. Een paar honderd voor een hele
collectie, en dat past ruim in een gratis of goedkoop niveau. Na een maand
gebruik je de dienst praktisch niet meer, en werkt het ding volledig offline.

De reden om lokaal op te slaan blijft staan: vinyl-tegen-vinyl matchen is
betrouwbaarder dan een dienst die tegen de digitale master vergelijkt.
Persingsverschillen en de snelheidsafwijking van je plateau vallen weg zodra de
referentie van je eigen draaitafel komt. De dienst geeft de plaat alleen een
naam; hij hoeft hem niet elke keer te herkennen.

| Kandidaat | Wat het is | Bruikbaar als |
|---|---|---|
| **AudD** | commerciële API, upload een fragment en krijg artiest/album terug; gratis proefniveau, daarna ~$5/mnd | de koude start — meest gebruikte keuze en het eenvoudigst te integreren |
| **ACRCloud** | commercieel met een gratis ontwikkelaarsniveau; kan daarnaast een *eigen* audiobucket hosten | koude start, of als je de hele database toch liever in de cloud zet |
| **AHA Music** | dienst met API, van origine een browserextensie | alternatief voor de koude start; minder gangbaar voor dit doel |
| **Audile / Audire** | open-source Android-clients (F-Droid) | **referentie-implementatie**, geen motor — ze roepen zelf een API aan (naar mijn weten AudD). Lees hun code voor samplelengte, formaat en foutafhandeling; controleer in de repo welke backend ze gebruiken |
| **Dejavu** | open-source Python fingerprinting, zelf te hosten | de lokale database die na de koude start het werk doet |

Let op dat "open source" bij Audile en Audire slaat op de app, niet op het
algoritme of de database. Je kunt ze niet op een Pi zetten en klaar zijn.

### Waar het draait

Niet op de microcontroller. Opnemen via een I2S-ADC (**PCM1808**-breakout, ~€8;
de interne ADC van de ESP32 is hier te slecht voor), ~15 s over wifi naar een
Python-dienstje, hoesje terug. Dat dienstje kan op je Mac of een Pi staan — en
kies je voor de Pi-variant, dan draait het gewoon op hetzelfde bordje als het
scherm.

---

## Onherkende platen: de wachtrij

Herkent Shazam een plaat niet, dan is dat geen dood spoor maar het beginpunt.
De opname die er toch al is wordt bewaard, en jij koppelt hem later aan de
juiste plaat. Vanaf dat moment herkent het apparaat hem **zelf**, zonder dienst.

Daarmee groeit de lokale database precies daar waar Shazam tekortschiet, en
alleen daar. Je hoeft je collectie niet vooraf in te lezen — de gaten vullen
zichzelf, in de volgorde waarin je ze tegenkomt.

### Blijf doorluisteren als het misgaat

Acht seconden is genoeg om het aan Shazam te vrágen, maar **niet genoeg om als
eigen referentie te dienen**. Uit de metingen in
[../v2/recognizer/](../v2/recognizer/README.md): een referentie van acht
seconden dekt acht seconden van de kant. Staat de naald de volgende keer ergens
anders, dan is er niets om mee te matchen.

Dus: mislukt de opzoeking, dan blijft het apparaat gewoon nog **60 tot 90
seconden doorluisteren**. De plaat speelt toch. Die langere opname is meteen
allebei: het geluidsfragment dat jij straks terugluistert, en de
fingerprint-referentie voor later.

### Wat je in de webinterface ziet

Een lijst met onherkende kanten, per stuk met tijdstip en een afspeelknop —
want na twee dagen weet je niet meer wat er dinsdagavond op stond. Per regel:

- **zoeken in Discogs**, eerst in je eigen collectie en dan pas in de hele
  database, want je bezit de plaat immers
- of **zelf een hoes uploaden**, voor bootlegs, privépersingen en alles wat
  Discogs niet kent
- of **weggooien**, als het toch de radio was

Bevestigen doet drie dingen tegelijk: de hoes wordt opgehaald en gecachet, het
fingerprint wordt aan die release gekoppeld, en de regel verdwijnt uit de
wachtrij. De volgende keer verschijnt het hoesje binnen een paar seconden,
zonder netwerk.

Daarnaast een tweede lijst met wat er wél gematcht is, met per regel "dit klopt
niet". Zonder die knop wordt een verkeerde match permanent, en dat is precies
het soort ding dat een leuk apparaat irritant maakt.

### Opruimen

De geluidsfragmenten zijn opnames uit je living room. Houd ze kort, neem alleen op
als de AVR meldt dat phono speelt, en **gooi het geluid weg zodra de kant
gekoppeld is** — het fingerprint is dan alles wat je nog nodig hebt, en dat is
geen audio meer. Ongekoppelde fragmenten na een maand automatisch opruimen.

## Naar de webinterface toe: QR op het schermpje

Het apparaat weet zijn eigen adres; jij niet. Dus toont het scherm een **QR-code**
die je met je telefoon scant, met het IP-adres eronder in gewone cijfers voor
wie het op een laptop wil intypen.

Twee keuzes daarin:

**Codeer het IP-adres, toon de hostnaam als tekst.** `marantzknob.local` is
mooier en verandert niet, maar niet elke telefoon lost mDNS betrouwbaar op. Het
IP werkt altijd. Geef een DHCP-reservering in je router, dan is het ook stabiel.

**Laat hem verschijnen op het moment dat er iets te doen is.** Niet permanent in
beeld — dat is lelijk en meestal overbodig. Maar zodra een plaat niet herkend
wordt, is dat precies het moment waarop je je telefoon pakt. De QR komt dan naar
je toe in plaats van dat je een instellingenscherm moet zoeken. Daarnaast
bereikbaar via een tik op het scherm.

Op een rond scherm van 480×480 past binnen de cirkel een vierkant van ongeveer
340×340 pixels. Ruim voldoende. Genereren kan met de `qrcode`-bibliotheek voor
Python: klein, zonder zware afhankelijkheden, en snel genoeg op een Zero.

## Het beeld

480×480 rond is een cadeau voor dit onderwerp: het is de vorm van een plaat.

**Toon het hoesje als een label.** Vierkante hoes rond bijgesneden, met een
subtiele spindelopening in het midden en fijne groeven naar de rand toe. Dat is
formaat-eigen op een manier die een vierkant scherm nooit kan zijn, en het
verliezen van de hoekjes van de hoes leest dan als opzet in plaats van als een
crop.

**Volume als een boog langs de rand.** Precies daar waar je vingers op de ring
liggen, dus de boog leest als de stand van de ring. Tijdens het draaien licht
hij op en komt de dB-waarde er kort overheen; daarna zakt hij weg en blijft het
hoesje over.

**Kleur uit het hoesje halen.** Haal de twee of drie dominante kleuren uit de
afbeelding en gebruik die voor de boog en de gloed. Kost weinig rekenwerk en het
apparaat ziet er bij elke plaat anders uit — dat is het soort detail waar het
"gemaakt" in plaats van "gebouwd" van gaat voelen.

**Niet laten draaien.** Verleidelijk, maar 33⅓ toeren is 1,8 seconde per
omwenteling en dat is onrustig; en langzamer draaien is een truc die na een week
gaat vervelen. Belangrijker: het beeld hoort stil te staan omdat de **ring** het
ding is dat beweegt. Twee dingen die tegelijk draaien vechten met elkaar.

**Als er geen hoesje is:** typografie. Artiestennaam groot, album eronder, in de
kleur van niets. Dat kan er beter uitzien dan een matige afbeelding. En bij een
andere ingang dan phono: gewoon groot het volume en de ingangsnaam, geen lege
cirkel.

## De collectie op het scherm

Naast "wat draait er nu" ook: **door je platenkast bladeren met de ring**. De
hoesjes schuiven langs, je tikt om te kiezen.

### Hoe het schakelt

Tik op het scherm om in de bladermodus te komen; de ring scrollt dan door de
lijst in plaats van het volume te regelen. Tik om te kiezen, of doe niets en na
een paar seconden gaat hij vanzelf terug.

Met een encoder is dat wisselen gratis. Bij een absolute potmeter zou de ring na
het bladeren op een stand staan die niet meer met het volume klopt, en dat was
eerder het hele argument voor een motor. Nu telt de ring alleen verandering, dus
er valt niets terug te zetten.

Aanwijzen doe je met het scherm. De ring heeft geen drukfunctie, en je kijkt er
toch al naar.

### Wat "kiezen" oplevert

Je kunt een plaat niet laten afspelen — er moet iemand opstaan. Twee dingen
waar het wél voor is, en allebei zijn ze de moeite:

- **"Wat zullen we opzetten?"** Door de kast scrollen met de hoezen in beeld is
  een prettigere manier om te kiezen dan langs de rug van je platen turen. Heb
  je in Discogs een bewaarlocatie ingevuld, toon die er dan bij.
- **Handmatig koppelen.** Herkent hij de plaat niet, dan draai je naar het juiste
  album en tikt. Daarmee verhuist het koppelen van de webinterface naar het
  apparaat zelf voor het gewone geval.

Dat laatste maakt de webinterface een stuk minder belangrijk: die blijft over
voor instellen, tokens, en het corrigeren van eerdere fouten in bulk.

### Vormgeving

Op een rond scherm werkt een boog beter dan een lijst. Drie of vijf hoesjes op
een cirkelsegment, het middelste groot en scherp, de buren kleiner en zachter.
Artiest en album eronder.

Scrollen doe je met je vinger over het scherm, of met de ring. Dat laatste werkt
nu beter dan in de eerdere opzet: een encoder telt alleen verandering en draait
oneindig door, dus je scrollt gewoon net zo lang als je wil in plaats van je
hele kast over 270 graden uitgesmeerd te krijgen. Voor een paar honderd albums
is dat het verschil tussen bruikbaar en frustrerend.

Zet er wel een alfabetische sprongindex langs de rand bij, zodat je niet door
driehonderd hoesjes hoeft te draaien om bij de W te komen.

### Buiten het bedieningspad houden

Herkenning voedt **alleen het scherm**. Ze schakelt niets en regelt niets. Zit
een match ernaast, dan staat er een verkeerd hoesje in beeld — geen versterker
die iets onverwachts doet. Input en volume blijven puur van de ring.

---

## Wat er overgaat uit versie 1

Direct herbruikbaar, ongeacht het platform:

- **De protocolkennis.** `MV`/`SI`/`MU`/`ZM`, het volumemodel (`dB = waarde-80`,
  halve stappen), `MVMAX`, en dat de receiver ongevraagd pusht. Zie
  [`src/marantz.cpp`](../src/marantz.cpp) — dat vertaalt regel voor regel naar
  Python.
- **De quadratuur-decoder** (de 16-waarden tabel in `src/main.cpp`).
- **De 250 ms uitstel bij ingangkeuze**, zodat de receiver niet elke
  tussenliggende ingang aantikt.
- **Het instellingenmodel** en de webinterface-opzet.
- De twee harde randvoorwaarden: Netwerkbesturing op "Altijd aan", en één
  telnet-sessie tegelijk.

Wat **niet** overgaat: de gebaren. Een ring heeft geen drukknop. Mute, aan/uit,
ingangkeuze en de favoriet verhuizen allemaal naar het touchscreen. Dat is geen
verlies — het is beter, want een radiaal menu met je ingangen erop is
zelfverklarend waar "twee keer drukken" dat nooit wordt.

---

## Volgorde

Bouw eerst versie 1 af. Niet uit voorzichtigheid, maar omdat je dan drie dingen
weet die je nu nog niet weet: of het telnet-protocol zich gedraagt zoals
verwacht op jouw toestel, hoeveel dB per stap prettig aanvoelt, en hoeveel
wrijving een draaiknop mag hebben voordat het vervelend wordt. Dat laatste is
precies de parameter die het gevoel van de luxe versie bepaalt, en je kunt hem
alleen met een knop in je hand vinden.

De signaaldetectie is trouwens niet aan de luxe versie gebonden. Een
envelope-detector op een vrije ADC-pin en dan `ZMON` + `SIPHONO` sturen is twee
onderdelen en twintig regels, die net zo goed in versie 1 passen. Goede eerste
uitbreiding zodra het bordje draait. De muziekherkenning is een project op
zichzelf en hoort bij de luxe versie, met zijn scherm om het op te tonen.
