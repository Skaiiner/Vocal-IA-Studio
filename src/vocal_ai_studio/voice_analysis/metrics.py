from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.pitch.notes import hz_to_midi, midi_to_note_name
from vocal_ai_studio.pitch.yin import yin_pitch_track
from vocal_ai_studio.voice_analysis.notes import NoteSegment, segment_notes

Progress = Callable[[float, str], None]
Cancelled = Callable[[], bool]


@dataclass
class VocalAnalysis:
    pitch: PitchTrack
    duration: float
    notes: list[NoteSegment] = field(default_factory=list)
    avg_cents_deviation: float = 0.0
    stability_cents: float = 0.0
    vocal_range: tuple[str, str] | None = None
    pauses: list[tuple[float, float]] = field(default_factory=list)
    vibrato_rate_hz: float | None = None
    vibrato_extent_cents: float | None = None
    voiced_fraction: float = 0.0


def _find_pauses(track: PitchTrack, min_pause: float = 0.3) -> list[tuple[float, float]]:
    n = len(track.f0)
    if n == 0:
        return []
    voiced = ~np.isnan(track.f0)
    hop_dt = track.times[1] - track.times[0] if n > 1 else 0.0
    pauses: list[tuple[float, float]] = []
    i = 0
    while i < n:
        if voiced[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and not voiced[j + 1]:
            j += 1
        start, end = float(track.times[i]), float(track.times[j] + hop_dt)
        if end - start >= min_pause:
            pauses.append((start, end))
        i = j + 1
    return pauses


def _estimate_vibrato(notes: list[NoteSegment], track: PitchTrack,
                       min_duration: float = 0.3) -> tuple[float | None, float | None]:
    # Cruces por cero de la curva de cents destendenciada; solo notas >= min_duration, 3-9 Hz.
    rates: list[float] = []
    extents: list[float] = []
    for note in notes:
        if note.duration < min_duration:
            continue
        mask = (track.times >= note.start) & (track.times < note.end) & ~np.isnan(track.f0)
        if mask.sum() < 6:
            continue
        cents = (hz_to_midi(track.f0[mask]) - note.midi) * 100.0
        trend = np.linspace(cents[0], cents[-1], len(cents))
        detrended = cents - trend
        if np.std(detrended) < 3.0:
            continue
        signs = np.sign(detrended)
        signs[signs == 0] = 1
        crossings = int(np.count_nonzero(np.diff(signs)))
        rate = (crossings / 2.0) / note.duration
        if 3.0 <= rate <= 9.0:
            rates.append(rate)
            extents.append(float((detrended.max() - detrended.min()) / 2.0))
    if not rates:
        return None, None
    return float(np.mean(rates)), float(np.mean(extents))


def analyze_vocal(samples: np.ndarray, sr: int, progress: Progress | None = None,
                   cancelled: Cancelled | None = None) -> VocalAnalysis:
    def pitch_progress(frac: float) -> None:
        if progress:
            progress(frac * 0.9, "Detectando afinación…")

    track = yin_pitch_track(samples, sr, progress=pitch_progress, cancelled=cancelled)
    if progress:
        progress(0.92, "Agrupando notas…")
    notes = segment_notes(track)

    voiced = ~np.isnan(track.f0)
    if voiced.any():
        cents = (hz_to_midi(track.f0[voiced]) - np.round(hz_to_midi(track.f0[voiced]))) * 100.0
        avg_cents_dev = float(np.mean(np.abs(cents)))
        stability = float(np.std(cents))
        midi_vals = np.round(hz_to_midi(track.f0[voiced])).astype(int)
        vocal_range = (midi_to_note_name(int(midi_vals.min())), midi_to_note_name(int(midi_vals.max())))
    else:
        avg_cents_dev, stability, vocal_range = 0.0, 0.0, None

    if progress:
        progress(0.96, "Buscando respiraciones y vibrato…")
    pauses = _find_pauses(track)
    vib_rate, vib_extent = _estimate_vibrato(notes, track)

    if progress:
        progress(1.0, "Análisis completado")

    return VocalAnalysis(
        pitch=track, duration=len(samples) / sr if sr else 0.0, notes=notes,
        avg_cents_deviation=avg_cents_dev, stability_cents=stability, vocal_range=vocal_range,
        pauses=pauses, vibrato_rate_hz=vib_rate, vibrato_extent_cents=vib_extent,
        voiced_fraction=float(voiced.mean()) if len(voiced) else 0.0,
    )


def to_dict(analysis: VocalAnalysis) -> dict:
    return {
        "duration": analysis.duration,
        "avg_cents_deviation": analysis.avg_cents_deviation,
        "stability_cents": analysis.stability_cents,
        "vocal_range": list(analysis.vocal_range) if analysis.vocal_range else None,
        "pauses": [list(p) for p in analysis.pauses],
        "vibrato_rate_hz": analysis.vibrato_rate_hz,
        "vibrato_extent_cents": analysis.vibrato_extent_cents,
        "voiced_fraction": analysis.voiced_fraction,
        "notes": [
            {"start": n.start, "end": n.end, "midi": n.midi, "name": n.name,
             "avg_freq": n.avg_freq, "avg_cents": n.avg_cents, "max_abs_cents": n.max_abs_cents}
            for n in analysis.notes
        ],
    }


def from_dict(data: dict, pitch: PitchTrack) -> VocalAnalysis:
    notes = [NoteSegment(**n) for n in data["notes"]]
    vocal_range = tuple(data["vocal_range"]) if data.get("vocal_range") else None
    return VocalAnalysis(
        pitch=pitch, duration=data["duration"], notes=notes,
        avg_cents_deviation=data["avg_cents_deviation"], stability_cents=data["stability_cents"],
        vocal_range=vocal_range, pauses=[tuple(p) for p in data["pauses"]],
        vibrato_rate_hz=data.get("vibrato_rate_hz"), vibrato_extent_cents=data.get("vibrato_extent_cents"),
        voiced_fraction=data.get("voiced_fraction", 0.0),
    )
