# Herkenner — werkend prototype

Fingerprinting van plaatkanten, zoals Shazam maar dan voor één platenkast.
Draait zonder hardware; dit is bewust het eerste dat gebouwd is, omdat het het
enige deel van het luxe-project was waarvan niet vaststond dát het kon.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python test_roundtrip.py      # synthetische toets
.venv/bin/python listen.py selftest     # pijplijn zonder microfoon
```

| Bestand | |
|---|---|
| `fingerprint.py` | spectrogram → pieken → landmark-hashes |
| `store.py` | SQLite-opslag en het matchen |
| `test_roundtrip.py` | maakt zijn eigen "platen" en meet waar het ophoudt |
| `experiment_window.py` | hoeveel van een kant je moet vastleggen |
| `listen.py` | testen met de microfoon van je Mac, op echte muziek |

## Werkt het?

Ja. Uit `test_roundtrip.py`, met vijf kanten in de database en een fragment van
15 seconden vanaf 30,0 s in plaat 3:

```
     SNR   snelheid  uitslag   score    marge   positie
  schoon    normaal  ok         2082    11.6x     30.0s
   45 dB    normaal  ok         1130     7.7x     30.0s
   45 dB     +0,3 %  ok          415     5.5x     30.0s
   25 dB    normaal  ok          801     6.7x     30.0s
   25 dB     +0,3 %  ok          357     4.4x     30.0s
   10 dB    normaal  ok          653     5.4x     30.0s
```

Foutloos tot en met 20 dB SNR met én zonder snelheidsafwijking. Ter ijking:
normale vinyl zit op 45-55 dB, een plaat die je niet meer zou opzetten op 25-35.
De teruggevonden tijdpositie is in elk geval exact 30,0 s — het weet dus niet
alleen wélke plaat het is maar ook waar de naald staat.

## Testen met echte muziek

Alles hierboven is gemeten op synthetisch materiaal. `listen.py` gebruikt de
microfoon van je Mac, zodat je het op echte muziek kunt toetsen zonder iets te
bestellen.

```bash
.venv/bin/python listen.py proef            # begeleide proefsessie - begin hier
.venv/bin/python listen.py devices          # welke microfoons ziet hij
.venv/bin/python listen.py learn "Naam"     # 60 s opnemen en vastleggen
.venv/bin/python listen.py id               # 15 s opnemen: wat is dit?
.venv/bin/python listen.py watch            # blijven luisteren
.venv/bin/python listen.py list             # database tonen
.venv/bin/python listen.py forget 3         # koppeling weggooien
```

Tijdens het opnemen loopt er een niveaumetertje, zodat je meteen ziet of er iets
binnenkomt. Komt er niets: **Systeeminstellingen → Privacy en beveiliging →
Microfoon** en je terminal aanzetten.

`proef` loopt de drie stappen die ertoe doen met je mee, met een eigen database
die telkens wordt leeggegooid:

1. Zet een nummer op en laat het vastleggen
2. Laat het doorlopen — hij moet het terugherkennen, mét de juiste tijdpositie
3. **Zet iets heel anders op** — hij hoort dan "Niets herkend" te zeggen

Die derde stap is de belangrijkste. Iets herkennen is makkelijk; *niets*
herkennen wanneer het er niet is, is waar zwakke fingerprinting op stukloopt.
Daarom geeft `listen.py` drie uitkomsten (zeker / twijfel / onbekend) in plaats
van altijd een beste gok, en toont hij ook de nummers twee en drie.

`learn` legt hier standaard alles vast (`--density 1`). Werkt dat, probeer dan
`--density 4` — dat is de instelling waarmee een hele collectie in het geheugen
van een Pi past.

## Wat het onderweg heeft gekost

Vier keer gemeten en bijgesteld. De uitkomsten zijn het waard om te bewaren,
want het zijn precies de dingen die je niet uit een tutorial haalt.

**Logaritmische frequentiebanden lossen het snelheidsprobleem op.** Een plateau
dat 0,3 % te snel draait verschuift alle frequenties met 0,3 %; in lineaire
FFT-bins is dat bij 1 kHz drie bins verderop en breekt elke hash. In banden van
een achtste toon (1,45 % breed) blijft zo'n verschuiving binnen dezelfde band.
Dit alleen al bracht de marge van 1,3× naar 10,9×.

**Maar niet té grof.** Kwarttoonbanden (24 per octaaf) gaven maar ~130 banden,
waardoor de hashruimte verzadigde en elke plaat op elke andere leek — hoge
scores, marge 1,0×. 48 banden per octaaf is het werkbare midden.

**Het piekvenster in de tijd was de grootste fout.** Op 20 frames (~0,9 s) moet
een piek een hele seconde domineren. Er bleven er zo weinig over dat ze stuk
voor stuk marginaal waren: van twee afspeelbeurten overleefde 8 % van de pieken.
Op 3 frames werd dat 23 %.

**En de doorslag: de instabiliteit zit in de tijd, niet in de frequentie.**
Meten met tolerantie liet zien dat ±1 band de overlap nauwelijks verbetert
(16 → 17 %), maar ±1 frame die verdubbelt (17 → 44 %). Een piek in een
aangehouden noot verspringt onder ruis één frame. Omdat een hash twéé pieken
nodig heeft, is dat het verschil tussen 3 % en 19 % bruikbare hashes — oftewel
tussen niet en wel werken. De oplossing is `DT_TOLERANCE`: bij het opzoeken
wordt elke hash ook met tijdsverschil ±1 uitgegeven, en het uitlijnen telt drie
naburige bakjes bij elkaar op. Vastleggen blijft exact, dus de database groeit
er niet van.

## Hoeveel van een kant leg je vast?

Shazam heeft maar ~10 seconden nodig — maar dat is de lengte van de **opname die
je maakt**, niet van wat er in de database staat. Shazam heeft het hele nummer
vastgelegd, en precies daarom kun je hem midden in een liedje aanzetten.

Leg je alleen het begin van een kant vast, dan herken je alleen als de naald
daar staat. Uit `experiment_window.py`, kanten van 5 minuten, luisteren op drie
posities:

```
variant                 h/s  RAM 400 alb        @10s        @60s       @200s
eerste 45 s             513       3938 MB   999/ 5.3x   425/ 2.9x?  447/ 2.5x?
eerste 90 s             542       4164 MB   999/ 5.3x  1010/ 5.5x   487/ 2.7x?
hele kant               605       4643 MB   999/ 5.1x  1010/ 5.0x  1231/ 5.9x
hele kant, 1 op 4       152       1165 MB   271/ 4.6x   260/ 4.3x   287/ 4.6x
hele kant, 1 op 8        77        591 MB   138/ 3.1x?  134/ 3.7x?  143/ 3.8x?
hele kant, 1 op 16       37        285 MB    59/ 3.5x?   55/ 3.1x?   62/ 3.3x?
```

**Uitdunnen is een betere knop dan afkappen.** De hele kant vastleggen met een
op de vier hashes geeft volledige dekking bij een marge die niet onderdoet voor
een venster van 90 s — en dat venster laat je in de steek zodra de naald verder
staat. Vandaar dat `enroll` nu standaard `keep_one_in=4` gebruikt en de hele
kant vastlegt.

Twee kanttekeningen bij deze tabel: de synthetische platen delen per stuk één
toonladder, waardoor een niet-vastgelegd stuk nog te veel op het vastgelegde
deel lijkt — bij echte muziek zullen die vensterrijen op @200s eerder GEMIST
opleveren dan een zwakke treffer. En de marges zijn gemeten tegen vier
concurrenten; bij achthonderd kanten wordt de sterkste toevalstreffer hoger en
zakken ze.

## Waar het ophoudt

Met 100 kanten van 90 s op volle dichtheid:

```
4.760.532 hashes, database 152 MB
45 dB: correct, marge 4,8x, zoektijd 1,8 s
30 dB: correct, marge 4,0x, zoektijd 2,0 s
```

Nog steeds goed, maar de marge zakt van ~7× naar ~4,8× en de zoektijd loopt op.
Doorgetrokken naar 400 albums (800 kanten) wordt dat ~1,2 GB en op een Pi Zero
al snel een halve minuut per zoekopdracht. **Dat is de grens van deze opzet en
het volgende dat aangepakt moet worden.**

De aanpak ligt voor de hand en is niet groot:

1. **Index in het geheugen in plaats van SQLite-rijen.** 5 miljoen hashes is
   40 MB als gesorteerde numpy-array; `np.searchsorted` doet daar in
   milliseconden wat de huidige Python-lus in seconden doet. Dit is vrijwel
   zeker een factor 20-50 en het meeste werk zit in het laden bij het opstarten.
2. **Eerst grof filteren, in twee trappen.** Houd een uitgedunde index in het
   geheugen (bijvoorbeeld een op de 32 hashes — voor achthonderd kanten ~40 MB),
   gebruik die om tien kandidaat-kanten te kiezen, en lees pas dan van die
   kandidaten de volledige hashes van schijf. Dat is per kant een aaneengesloten
   stuk bestand, dus sequentieel lezen. De naïeve variant — de hele index op
   schijf laten en er willekeurig in zoeken — loopt juist stuk, want dat worden
   tienduizenden losse leesacties.
3. **Verder uitdunnen.** Van een op de vier naar een op de acht halveert alles,
   ten koste van marge (4,5x naar 3,5x). Zie de tabel hierboven.

## Instellingen die ertoe doen

Allemaal boven in `fingerprint.py`, met de gemeten onderbouwing erbij.

| | | |
|---|---|---|
| `BANDS_PER_OCTAVE` | 48 | fijner = meer entropie, grover = meer snelheidstolerantie |
| `PEAK_BOX_TIME` | 3 | groter = minder en instabielere pieken |
| `MAX_PEAKS_PER_FRAME` | 10 | bepaalt vrijwel lineair de omvang van de database |
| `DT_TOLERANCE` | 1 | 0 maakt het onbruikbaar; hoger kost alleen querytijd |
| `enroll(keep_one_in=)` | 4 | de belangrijkste knop voor databaseomvang |
| `enroll(seconds=)` | None | hele kant; afkappen kost dekking, zie hierboven |

## Nog niet gedaan

- De index in het geheugen (zie hierboven) — het echte volgende werk
- De uitdunfactor opnieuw bepalen zodra er honderden echte kanten in zitten
- Audio inlezen van het apparaat; nu alleen wav-bestanden en numpy-arrays
- Koppeling met Discogs en de webinterface om onherkende kanten te taggen
- Getest op **echte** naaldopnames. Alles hierboven is gemeten op synthetisch
  materiaal met realistische ruis en snelheidsafwijking. Dat is genoeg om de
  aanpak te vertrouwen, niet om hem af te tekenen.
