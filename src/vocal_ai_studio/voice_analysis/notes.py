from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.pitch.notes import hz_to_midi, midi_to_note_name


@dataclass
class NoteSegment:
    start: float
    end: float
    midi: int
    name: str
    avg_freq: float
    avg_cents: float
    max_abs_cents: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def segment_notes(track: PitchTrack, min_note_duration: float = 0.08, merge_gap: float = 0.06) -> list[NoteSegment]:
    # merge_gap une tramos de la misma nota separados por un hueco corto (p. ej. una consonante)
    f0, times = track.f0, track.times
    n = len(f0)
    if n == 0:
        return []
    voiced = ~np.isnan(f0)
    if not voiced.any():
        return []
    midi_round = np.full(n, np.nan)
    midi_round[voiced] = np.round(hz_to_midi(f0[voiced]))

    runs: list[tuple[int, int, int]] = []
    i = 0
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and voiced[j + 1] and midi_round[j + 1] == midi_round[i]:
            j += 1
        runs.append((i, j, int(midi_round[i])))
        i = j + 1

    merged: list[tuple[int, int, int]] = []
    for run in runs:
        if merged and merged[-1][2] == run[2] and (times[run[0]] - times[merged[-1][1]]) <= merge_gap:
            start_i, _, midi = merged[-1]
            merged[-1] = (start_i, run[1], midi)
        else:
            merged.append(run)

    hop_dt = times[1] - times[0] if n > 1 else 0.0
    segments: list[NoteSegment] = []
    for start_i, end_i, midi in merged:
        start, end = float(times[start_i]), float(times[end_i] + hop_dt)
        if end - start < min_note_duration:
            continue
        freqs = f0[start_i:end_i + 1]
        freqs = freqs[~np.isnan(freqs)]
        if freqs.size == 0:
            continue
        cents = (hz_to_midi(freqs) - midi) * 100.0
        segments.append(NoteSegment(
            start, end, midi, midi_to_note_name(midi),
            float(np.mean(freqs)), float(np.mean(cents)), float(np.max(np.abs(cents))),
        ))
    return segments
