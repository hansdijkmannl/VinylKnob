"""
Akoestische fingerprints, Shazam-stijl.

Het idee: maak een spectrogram, zoek daarin de lokale pieken, en koppel elke
piek aan een handvol pieken die er kort na komen. Elk zo'n paar wordt een hash
van (frequentie 1, frequentie 2, tijdsverschil). Die drie waarden zijn samen
karakteristiek voor het geluid maar ongevoelig voor volume, ruis en EQ - precies
wat je nodig hebt als de bron een naald in een groef is.

Bewust klein gehouden. Dejavu en soortgelijke pakketten mikken op miljoenen
nummers en trekken daar een MySQL-server bij. Wij hoeven alleen een platenkast
te herkennen; een paar honderd albums past in SQLite en draait moeiteloos op
een Pi Zero.
"""

from __future__ import annotations

import numpy as np
from scipy import signal
from scipy.io import wavfile
from scipy.ndimage import maximum_filter, uniform_filter1d

# 11 kHz is ruim genoeg: alles wat een plaat identificeert zit onder 4 kHz, en
# minder samples betekent minder rekenwerk op de Pi.
SAMPLE_RATE = 11025
WINDOW = 4096
HOP = 512

# Hoe ver een piek boven zijn omgeving moet uitsteken. Groter = minder pieken,
# minder hashes, sneller maar minder robuust tegen ruis.
# Het tijdvenster is hier de gevoeligste parameter. Op 20 frames (~0,9 s) moet
# een piek een hele seconde domineren; er blijven er dan zo weinig over dat ze
# stuk voor stuk marginaal zijn en bij de minste ruis verspringen. Op 3 frames
# overleeft ruim drie keer zoveel een tweede afspeelbeurt.
PEAK_BOX_FREQ = 9       # banden
PEAK_BOX_TIME = 3       # frames

# Een piek telt pas als hij zoveel dB boven het lokale ruisniveau uitkomt. Dit
# is bewust een *relatieve* drempel: oppervlakteruis tilt het hele spectrum op,
# en een absolute drempel zou dan of alles of niets doorlaten.
PEAK_MIN_SALIENCE_DB = 3.0
BACKGROUND_BINS = 41    # banden waarover het ruisniveau wordt geschat

# Per tijdframe houden we alleen de sterkste pieken over. Ruis levert veel
# zwakke lokale maxima op die de drempel net halen; de echte pieken blijven ook
# in een ruisig signaal de sterkste. Dit begrenst bovendien de omvang van de
# database, want het aantal hashes wordt er lineair door bepaald.
MAX_PEAKS_PER_FRAME = 10

# Elke piek wordt gekoppeld aan de eerstvolgende FAN_OUT pieken binnen het
# tijdvenster.
#
# Met tien pieken per frame komen die partners vrijwel allemaal uit hetzelfde of
# het volgende frame, dus het tijdsverschil in de hash is bijna altijd 1 of 2 en
# draagt weinig informatie. Een poging om ze over het venster te spreiden (met
# een minimale afstand tussen partnerframes) maakte het meetbaar slechter: welke
# partner gekozen wordt hangt dan af van welke frames pieken hebben, en juist
# dat is ruisgevoelig. De marge zakte van 5x naar 2,3x. Dichtbij en stabiel wint
# hier van ver weg en informatierijk.
#
# Gevolg voor elders: de lage bits van een hash zijn dus bijna constant. Wie
# hashes wil uitdunnen moet ze eerst mengen - zie `mix` hieronder.
FAN_OUT = 10
MIN_DT = 1              # frames
MAX_DT = 80             # frames (~3,7 s bij bovenstaande instellingen)

# Frequenties gaan niet als bin maar als *logaritmische band* de hash in.
#
# Dit is de belangrijkste keuze in het hele bestand. Een plateau dat 0,3 % te
# snel draait verschuift alle frequenties met 0,3 %. In lineaire bins is dat bij
# 1 kHz al drie bins verderop en breekt de hash. In banden van een kwarttoon
# (2,9 % breed) blijft zo'n verschuiving vrijwel altijd binnen dezelfde band.
# Achtste tonen: 1,45 % breed, dus een afwijking van 0,3 % blijft ruim binnen
# een band. Kwarttonen (24 per octaaf) bleken te grof - dan zijn er nog maar
# ~130 banden, raakt de hashruimte verzadigd en lijkt elke plaat op elke andere.
BANDS_PER_OCTAVE = 48
F_MIN = 60.0
BAND_BITS = 9
MAX_BAND = (1 << BAND_BITS) - 1

SECONDS_PER_FRAME = HOP / SAMPLE_RATE


def _bin_to_band() -> np.ndarray:
    """Opzoektabel van FFT-bin naar logaritmische band."""
    freqs = np.arange(WINDOW // 2 + 1) * (SAMPLE_RATE / WINDOW)
    with np.errstate(divide="ignore", invalid="ignore"):
        bands = BANDS_PER_OCTAVE * np.log2(freqs / F_MIN)
    bands = np.where(np.isfinite(bands), bands, -1.0)
    return np.clip(np.floor(bands), -1, MAX_BAND).astype(np.int16)


BIN_TO_BAND = _bin_to_band()
N_BANDS = int(BIN_TO_BAND.max()) + 1

# Voor het omklappen naar banden: per band het bereik van FFT-bins.
_BAND_ORDER = np.argsort(BIN_TO_BAND, kind="stable")
_BAND_SORTED = BIN_TO_BAND[_BAND_ORDER]
_BAND_START = np.searchsorted(_BAND_SORTED, np.arange(N_BANDS), side="left")
_BAND_STOP = np.searchsorted(_BAND_SORTED, np.arange(N_BANDS), side="right")


def to_bands(magnitude: np.ndarray) -> np.ndarray:
    """Klapt het lineaire spectrogram om naar logaritmische banden.

    Dit gebeurt *voor* de piekdetectie, en dat is het punt. Zoek je pieken in
    lineaire bins en kwantiseer je pas daarna, dan vallen bij hoge frequenties
    meerdere bin-pieken in dezelfde band en wisselt het per afspeelbeurt welke
    er wint. Pieken horen gezocht te worden in dezelfde ruimte waarin je hasht.
    """
    ordered = magnitude[_BAND_ORDER]
    out = np.zeros((N_BANDS, magnitude.shape[1]), dtype=np.float32)
    for band in range(N_BANDS):
        start, stop = _BAND_START[band], _BAND_STOP[band]
        if stop > start:
            out[band] = ordered[start:stop].max(axis=0)
    return out


def load_wav(path: str, speed: float = 1.0) -> np.ndarray:
    """Leest een wav, maakt er mono float32 van op SAMPLE_RATE.

    `speed` simuleert een plateau dat te snel of te langzaam draait: 1.003 is
    0,3 % te snel. Handig om te testen hoe gevoelig het matchen daarvoor is.
    """
    rate, data = wavfile.read(path)
    samples = np.asarray(data, dtype=np.float64)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    # Integer-formaten normaliseren naar -1..1
    if np.issubdtype(np.asarray(data).dtype, np.integer):
        samples /= float(np.iinfo(np.asarray(data).dtype).max)

    return resample_to_working_rate(samples, rate, speed)


def resample_to_working_rate(samples: np.ndarray, rate: int,
                             speed: float = 1.0) -> np.ndarray:
    """Zet een signaal om naar SAMPLE_RATE, eventueel met snelheidsafwijking."""
    target = SAMPLE_RATE / speed
    if abs(rate - target) > 1e-6:
        n = int(round(len(samples) * target / rate))
        samples = signal.resample(samples, n)
    return np.asarray(samples, dtype=np.float32)


def spectrogram(samples: np.ndarray) -> np.ndarray:
    """Magnitude-spectrogram, vorm (frequentiebin, frame).

    Met de hand in plaats van scipy.signal.stft: dat is inmiddels legacy, en
    zes regels numpy is hier duidelijker én sneller. Het venster wordt per blok
    verwerkt zodat een hele plaatkant niet in één keer in het geheugen hoeft -
    op een Pi Zero met 512 MB is dat het verschil tussen werken en niet werken.
    """
    if len(samples) < WINDOW:
        return np.zeros((WINDOW // 2 + 1, 0), dtype=np.float32)

    n_frames = 1 + (len(samples) - WINDOW) // HOP
    window = np.hanning(WINDOW).astype(np.float32)
    out = np.empty((WINDOW // 2 + 1, n_frames), dtype=np.float32)

    block = 256
    for start in range(0, n_frames, block):
        stop = min(start + block, n_frames)
        idx = np.arange(WINDOW)[None, :] + HOP * np.arange(start, stop)[:, None]
        frames = samples[idx] * window
        out[:, start:stop] = np.abs(np.fft.rfft(frames, axis=1)).T

    return out


def peaks(samples: np.ndarray) -> np.ndarray:
    """Lokale maxima in het spectrogram. Geeft een array van (frame, bin)."""
    magnitude = spectrogram(samples)
    if magnitude.shape[1] == 0:
        return np.zeros((0, 2), dtype=int)

    magnitude = to_bands(magnitude)
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(magnitude, 1e-10))

    # Het lokale ruisniveau per frame schatten en eraf trekken. Wat overblijft
    # is hoe sterk een piek uitsteekt, ongeacht hoe luid of ruisig het geheel is.
    background = uniform_filter1d(db, size=BACKGROUND_BINS, axis=0, mode="nearest")
    salience = db - background

    local_max = maximum_filter(salience, size=(PEAK_BOX_FREQ, PEAK_BOX_TIME), mode="constant")
    hits = (salience == local_max) & (salience > PEAK_MIN_SALIENCE_DB)

    bands, frames = np.nonzero(hits)
    if len(frames) == 0:
        return np.zeros((0, 2), dtype=int)

    strength = salience[bands, frames]

    # Sorteren op tijd, en binnen elk frame op sterkte. Het koppelen hieronder
    # loopt vooruit door de tijd, dus de tijdsvolgorde is een voorwaarde.
    order = np.lexsort((-strength, frames))
    frames, bands = frames[order], bands[order]

    # Alleen de sterkste MAX_PEAKS_PER_FRAME per frame overhouden.
    rank = np.arange(len(frames)) - np.searchsorted(frames, frames, side="left")
    sel = rank < MAX_PEAKS_PER_FRAME
    return np.stack([frames[sel], bands[sel]], axis=1).astype(int)


# Bij het opzoeken laten we het tijdsverschil een frame speling houden. Meting
# wees uit dat pieken in frequentie stabiel zijn maar in tijd een frame kunnen
# verspringen: exacte overlap tussen twee afspeelbeurten is ~17 %, met een frame
# speling ~44 %. Omdat een hash twee pieken nodig heeft, is dat het verschil
# tussen 3 % en 19 % bruikbare hashes - oftewel tussen niet en wel werken.
DT_TOLERANCE = 1


def hashes(peak_list: np.ndarray, dt_tolerance: int = 0) -> list[tuple[int, int]]:
    """Koppelt pieken tot (hash, tijdstip-van-de-eerste-piek).

    De hash is 28 bits: 9 bits voor elke frequentieband en 10 voor het
    tijdsverschil. Het absolute tijdstip zit er bewust *niet* in - dat wordt
    apart bewaard, zodat we bij het matchen kunnen kijken of alle treffers
    hetzelfde tijdsverschil hebben. Dat is wat een echte match onderscheidt van
    een handvol toevallige botsingen.
    """
    out: list[tuple[int, int]] = []
    n = len(peak_list)

    for i in range(n):
        t1, f1 = int(peak_list[i][0]), int(peak_list[i][1])
        paired = 0
        for j in range(i + 1, n):
            t2, f2 = int(peak_list[j][0]), int(peak_list[j][1])
            dt = t2 - t1
            if dt < MIN_DT:
                continue
            if dt > MAX_DT:
                break
            for shift in range(-dt_tolerance, dt_tolerance + 1):
                d = dt + shift
                if MIN_DT <= d <= MAX_DT:
                    out.append(((f1 << 19) | (f2 << 10) | d, t1))
            paired += 1
            if paired >= FAN_OUT:
                break

    return out


def mix(h: int) -> int:
    """Mengt een hash zodat alle bits ongeveer even willekeurig zijn.

    Nodig omdat de lage bits van onze hashes het tijdsverschil bevatten, en dat
    is bijna altijd 1 of 2. Uitdunnen met `h % N` gooit daardoor of niets of
    alles weg.

    Let op: alleen vermenigvuldigen met een oneven constante helpt hier niet.
    Dat is bijectief modulo een macht van twee, dus de lage bits blijven precies
    even scheef verdeeld - de entropie gaat naar de hoge bits. Er is een echte
    avalanche-menging nodig, met verschuivingen die de hoge bits terugvouwen
    over de lage.
    """
    h = (h * 2654435761) & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return h


def fingerprint(samples: np.ndarray, dt_tolerance: int = 0) -> list[tuple[int, int]]:
    """Van geluid naar een lijst (hash, tijdstip in frames).

    Vastleggen gebeurt zonder speling (compacte database), opzoeken met
    `dt_tolerance=DT_TOLERANCE` (betere trefkans, alleen duurder bij de query).
    """
    return hashes(peaks(samples), dt_tolerance)
