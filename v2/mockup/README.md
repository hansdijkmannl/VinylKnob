# Interface-mockup

Werkende schets van hoe het CrowPanel eruit gaat zien en aanvoelt. Geen code
voor het apparaat — dit is er om de bediening te beoordelen voordat er een
regel LVGL geschreven wordt.

```bash
open /Volumes/Opslag/Apps/MarantzKnob/v2/mockup/index.html
```

Scroll met je muiswiel over het ronde scherm om aan de knop te draaien, klik
erop voor een korte druk. De knoppen eronder doen hetzelfde.

## Het bedieningsmodel

Met rotatie, druk én touch hoeft niets modaal te zijn. Dat is de kern van dit
ontwerp: **draaien is altijd volume**, in elk scherm, zonder uitzondering.

| De knop | |
|---|---|
| draaien | volume — altijd, nooit iets anders |
| kort drukken | mute aan/uit |
| dubbel drukken | direct naar de platenspeler |
| vasthouden | versterker aan/uit |

| Het scherm | |
|---|---|
| tik op de ingangsnaam | ingangenlijst; draaien loopt erdoorheen |
| tik op de hoes | de platenkast doorbladeren |
| tik om te bevestigen | of doe niets: na een paar seconden valt hij terug |

Alles wat je zonder kijken wil doen zit op de knop. Alles waarvoor je toch naar
het scherm kijkt, zit op het scherm.

## Wat de vormgeving probeert

**De hoes is het beeld, niet een cijfer.** Het volumegetal verschijnt alleen
terwijl je draait en verdwijnt na anderhalve seconde weer. Anders staat er
permanent een getal over je platenlabel.

**De boog ligt op de rand**, precies waar je vingers de knopring vastpakken.
Daarmee is de boog de standaanwijzer, en heb je geen absolute potmeter nodig om
te zien hoe hard het staat.

**De hoes wordt rond bijgesneden**, met een spindelgaatje in het midden. Op een
rond scherm leest dat als opzet in plaats van als een crop.

**De accentkleur komt uit de hoes.** In de mockup zit die kleur in de nepdata;
in het echt haal je de dominante kleur uit de afbeelding. Kost weinig rekenwerk
en het apparaat ziet er bij elke plaat anders uit.

**Terugvallen in plaats van bevestigen.** Elk keuzescherm keert vanzelf terug
naar het volume. Er is nergens een "annuleren".

## Wat er niet klopt aan de mockup

- De hoezen zijn gegenereerde kleurverlopen, geen echte albumhoezen.
- De QR-code is nep; alleen de verhouding klopt.
- Het bezel is een tekening. Hoe die knop in het echt draait is nog steeds het
  enige dat je niet op een scherm kunt beoordelen — daarvoor moet het bordje
  besteld worden.
