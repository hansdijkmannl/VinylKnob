"""
Acoustic fingerprints, Shazam-style.

The idea: build a spectrogram, find the local peaks in it, and pair every peak
with a handful of peaks shortly after. Each pair becomes a hash of (frequency 1,
frequency 2, time difference). Those three values together are characteristic of
the sound but indifferent to volume, noise and EQ — exactly what you need when
the source is a needle in a groove.

Deliberately small. Dejavu and similar packages aim at millions of tracks and
bring a MySQL server along. We only have to recognise one record collection; a
few hundred albums fit in SQLite and run comfortably on the smallest Pi.
"""

from __future__ import annotations

import numpy as np
from scipy import signal
from scipy.io import wavfile
from scipy.ndimage import maximum_filter, uniform_filter1d

# 11 kHz is ample: everything that identifies a record sits below 4 kHz, and
# fewer samples means less work for the Pi.
SAMPLE_RATE = 11025
WINDOW = 4096
HOP = 512

# How far a peak has to rise above its surroundings. Larger = fewer peaks,
# fewer hashes, faster but less robust against noise.
#
# The time window is the most sensitive parameter here. At 20 frames (~0.9 s) a
# peak has to dominate a whole second; so few survive that each one is marginal
# and shifts at the slightest noise. At 3 frames, over three times as many
# survive a second playing.
PEAK_BOX_FREQ = 9       # bands
PEAK_BOX_TIME = 3       # frames

# A peak only counts once it rises this many dB above the local noise floor.
# Deliberately a *relative* threshold: surface noise lifts the whole spectrum,
# and an absolute threshold would then pass either everything or nothing.
PEAK_MIN_SALIENCE_DB = 3.0
BACKGROUND_BINS = 41    # bands the noise floor is estimated over

# Per time frame we keep only the strongest peaks. Noise produces many weak
# local maxima that just clear the threshold; the real peaks stay the strongest
# even in a noisy signal. This also bounds the size of the database, since the
# number of hashes scales linearly with it.
MAX_PEAKS_PER_FRAME = 10

# Every peak is paired with the next FAN_OUT peaks inside the time window.
#
# With ten peaks per frame those partners nearly all come from the same or the
# next frame, so the time difference in the hash is almost always 1 or 2 and
# carries little information. Trying to spread them across the window (with a
# minimum distance between partner frames) made it measurably worse: which
# partner gets chosen then depends on which frames happen to have peaks, and
# that is precisely what noise disturbs. The margin dropped from 5x to 2.3x.
# Close and stable beats distant and information-rich here.
#
# Consequence elsewhere: the low bits of a hash are therefore nearly constant.
# Anyone thinning hashes out has to mix them first — see `mix` below.
FAN_OUT = 10
MIN_DT = 1              # frames
MAX_DT = 80             # frames (~3.7 s at the settings above)

# Frequencies enter the hash as a *logarithmic band*, not as a bin.
#
# This is the most important choice in the file. A platter running 0.3 % fast
# shifts every frequency by 0.3 %. In linear bins that is already three bins
# away at 1 kHz and the hash breaks. In quarter-tone bands (2.9 % wide) such a
# shift almost always stays inside the same band. Eighth tones are 1.45 % wide,
# so a 0.3 % deviation stays comfortably within one. Quarter tones (24 per
# octave) turned out too coarse — only ~130 bands, at which point the hash space
# saturates and every record resembles every other.
BANDS_PER_OCTAVE = 48
F_MIN = 60.0
BAND_BITS = 9
MAX_BAND = (1 << BAND_BITS) - 1

SECONDS_PER_FRAME = HOP / SAMPLE_RATE


def _bin_to_band() -> np.ndarray:
    """Lookup table from FFT bin to logarithmic band."""
    freqs = np.arange(WINDOW // 2 + 1) * (SAMPLE_RATE / WINDOW)
    with np.errstate(divide="ignore", invalid="ignore"):
        bands = BANDS_PER_OCTAVE * np.log2(freqs / F_MIN)
    bands = np.where(np.isfinite(bands), bands, -1.0)
    return np.clip(np.floor(bands), -1, MAX_BAND).astype(np.int16)


BIN_TO_BAND = _bin_to_band()
N_BANDS = int(BIN_TO_BAND.max()) + 1

# For folding into bands: the range of FFT bins per band.
_BAND_ORDER = np.argsort(BIN_TO_BAND, kind="stable")
_BAND_SORTED = BIN_TO_BAND[_BAND_ORDER]
_BAND_START = np.searchsorted(_BAND_SORTED, np.arange(N_BANDS), side="left")
_BAND_STOP = np.searchsorted(_BAND_SORTED, np.arange(N_BANDS), side="right")


def to_bands(magnitude: np.ndarray) -> np.ndarray:
    """Fold the linear spectrogram into logarithmic bands.

    This happens *before* peak detection, and that is the point. Find peaks in
    linear bins and quantise afterwards, and at high frequencies several bin
    peaks fall into the same band, with a different one winning each time you
    play the record. Peaks belong in the same space you hash in.
    """
    ordered = magnitude[_BAND_ORDER]
    out = np.zeros((N_BANDS, magnitude.shape[1]), dtype=np.float32)
    for band in range(N_BANDS):
        start, stop = _BAND_START[band], _BAND_STOP[band]
        if stop > start:
            out[band] = ordered[start:stop].max(axis=0)
    return out


def load_wav(path: str, speed: float = 1.0) -> np.ndarray:
    """Read a WAV into mono float32 at SAMPLE_RATE.

    `speed` simulates a platter running fast or slow: 1.003 is 0.3 % fast.
    Useful for testing how sensitive matching is to that.
    """
    rate, data = wavfile.read(path)
    samples = np.asarray(data, dtype=np.float64)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    # Normalise integer formats to -1..1
    if np.issubdtype(np.asarray(data).dtype, np.integer):
        samples /= float(np.iinfo(np.asarray(data).dtype).max)

    return resample_to_working_rate(samples, rate, speed)


def resample_to_working_rate(samples: np.ndarray, rate: int,
                             speed: float = 1.0) -> np.ndarray:
    """Resample to SAMPLE_RATE, optionally with a speed deviation."""
    target = SAMPLE_RATE / speed
    if abs(rate - target) > 1e-6:
        n = int(round(len(samples) * target / rate))
        samples = signal.resample(samples, n)
    return np.asarray(samples, dtype=np.float32)


def spectrogram(samples: np.ndarray) -> np.ndarray:
    """Magnitude spectrogram, shaped (frequency bin, frame).

    By hand rather than scipy.signal.stft: that is legacy now, and six lines of
    numpy is both clearer and faster here. Frames are processed in blocks so a
    whole side never has to be in memory at once — on a Pi with 512 MB that is
    the difference between working and not.
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
    """Local maxima in the spectrogram. Returns an array of (frame, bin)."""
    magnitude = spectrogram(samples)
    if magnitude.shape[1] == 0:
        return np.zeros((0, 2), dtype=int)

    magnitude = to_bands(magnitude)
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(magnitude, 1e-10))

    # Estimate the local noise floor per frame and subtract it. What remains is
    # how far a peak stands out, regardless of how loud or noisy the whole is.
    background = uniform_filter1d(db, size=BACKGROUND_BINS, axis=0, mode="nearest")
    salience = db - background

    local_max = maximum_filter(salience, size=(PEAK_BOX_FREQ, PEAK_BOX_TIME), mode="constant")
    hits = (salience == local_max) & (salience > PEAK_MIN_SALIENCE_DB)

    bands, frames = np.nonzero(hits)
    if len(frames) == 0:
        return np.zeros((0, 2), dtype=int)

    strength = salience[bands, frames]

    # Sort by time, and within each frame by strength. The pairing below walks
    # forward through time, so time order is a precondition.
    order = np.lexsort((-strength, frames))
    frames, bands = frames[order], bands[order]

    # Keep only the strongest MAX_PEAKS_PER_FRAME in each frame.
    rank = np.arange(len(frames)) - np.searchsorted(frames, frames, side="left")
    sel = rank < MAX_PEAKS_PER_FRAME
    return np.stack([frames[sel], bands[sel]], axis=1).astype(int)


# When looking up we allow the time difference one frame of slack. Measurement
# showed peaks are stable in frequency but can shift by a frame in time: exact
# overlap between two playings is ~17 %, with one frame of slack ~44 %. Because
# a hash needs two peaks, that is the difference between 3 % and 19 % usable
# hashes — which is to say, between not working and working.
DT_TOLERANCE = 1


def hashes(peak_list: np.ndarray, dt_tolerance: int = 0) -> list[tuple[int, int]]:
    """Pair peaks into (hash, time-of-the-first-peak).

    The hash is 28 bits: 9 for each frequency band and 10 for the time
    difference. The absolute time is deliberately *not* in it — that is stored
    separately, so that when matching we can check whether all the hits share
    the same time offset. That is what separates a real match from a handful of
    coincidental collisions.
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
    """Mix a hash so that every bit is about equally random.

    Necessary because the low bits of our hashes hold the time difference, and
    that is almost always 1 or 2. Thinning out with `h % N` therefore discards
    either nothing or everything.

    Note: multiplying by an odd constant alone does not help. That is bijective
    modulo a power of two, so the low bits stay exactly as skewed — the entropy
    moves to the high bits. A real avalanche mix is needed, with shifts that
    fold the high bits back over the low ones.
    """
    h = (h * 2654435761) & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return h


def fingerprint(samples: np.ndarray, dt_tolerance: int = 0) -> list[tuple[int, int]]:
    """From sound to a list of (hash, time in frames).

    Recording happens with no slack (compact database); looking up uses
    `dt_tolerance=DT_TOLERANCE` (better hit rate, and only costs more at query
    time).
    """
    return hashes(peaks(samples), dt_tolerance)
