from __future__ import annotations

import numpy as np

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def hz_to_midi(freq):
    freq = np.asarray(freq, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = 69.0 + 12.0 * np.log2(np.where(freq > 0, freq, np.nan) / 440.0)
    return float(midi) if midi.ndim == 0 else midi


def midi_to_hz(midi):
    midi = np.asarray(midi, dtype=np.float64)
    hz = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
    return float(hz) if hz.ndim == 0 else hz


def midi_to_note_name(midi_round: int) -> str:
    midi_round = int(round(midi_round))
    return f"{NOTE_NAMES[midi_round % 12]}{midi_round // 12 - 1}"


def note_name_to_midi(name: str) -> int:
    name = name.strip()
    has_accidental = len(name) > 1 and name[1] in ("#", "b")
    pitch = name[: 2 if has_accidental else 1]
    octave = int(name[2 if has_accidental else 1:])
    if pitch.endswith("b"):
        idx = (NOTE_NAMES.index(pitch[0]) - 1) % 12
    else:
        idx = NOTE_NAMES.index(pitch)
    return (octave + 1) * 12 + idx


def note_name_to_hz(name: str) -> float:
    return midi_to_hz(note_name_to_midi(name))


def cents_deviation(freq: float) -> float:
    midi = hz_to_midi(freq)
    if np.isnan(midi):
        return 0.0
    return float((midi - round(float(midi))) * 100.0)


def median_smooth(values: np.ndarray, window: int = 9) -> np.ndarray:
    n = len(values)
    out = values.copy()
    half = window // 2
    present = ~np.isnan(values)
    i = 0
    while i < n:
        if not present[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and present[j + 1]:
            j += 1
        segment = values[i:j + 1]
        for k in range(len(segment)):
            lo, hi = max(0, k - half), min(len(segment), k + half + 1)
            out[i + k] = np.median(segment[lo:hi])
        i = j + 1
    return out
