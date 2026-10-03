from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.pitch.notes import hz_to_midi, median_smooth, midi_to_hz
from vocal_ai_studio.pitch.scales import KEYS, SCALES, nearest_scale_midi
from vocal_ai_studio.voice_analysis.metrics import VocalAnalysis
from vocal_ai_studio.voice_analysis.notes import NoteSegment
from vocal_ai_studio.voice_analysis.song import SongAnalysis

MODE_PRESETS: dict[str, dict] = {
    "Natural": {"amount": 40.0, "speed_ms": 120.0, "humanize": 70.0},
    "Balanced": {"amount": 70.0, "speed_ms": 40.0, "humanize": 40.0},
    "Hard Autotune": {"amount": 100.0, "speed_ms": 8.0, "humanize": 0.0},
    "Extreme": {"amount": 100.0, "speed_ms": 1.0, "humanize": 0.0},
}
MODE_NAMES = list(MODE_PRESETS.keys())


@dataclass
class CorrectionSettings:
    key: str = "C"
    scale: str = "Mayor"
    amount: float = 70.0
    speed_ms: float = 40.0
    humanize: float = 40.0
    preserve_formants: bool = True
    mode: str = "Balanced"

    @classmethod
    def from_mode(cls, mode: str, key: str = "C", scale: str = "Mayor",
                 preserve_formants: bool = True) -> "CorrectionSettings":
        preset = MODE_PRESETS.get(mode, MODE_PRESETS["Balanced"])
        return cls(key=key, scale=scale, preserve_formants=preserve_formants, mode=mode, **preset)

    def to_dict(self) -> dict:
        return {"key": self.key, "scale": self.scale, "amount": self.amount, "speed_ms": self.speed_ms,
                "humanize": self.humanize, "preserve_formants": self.preserve_formants, "mode": self.mode}

    @classmethod
    def from_dict(cls, data: dict) -> "CorrectionSettings":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def suggest_correction_settings(vocal: VocalAnalysis, song: SongAnalysis | None = None,
                                preserve_formants: bool = True) -> tuple["CorrectionSettings", str]:
    """Propone Modo/Amount/Speed/Humanize/Tonalidad a partir del análisis vocal y de la canción.

    Puramente numérico (sin red ni modelos): cada ajuste sale de una medida concreta del análisis,
    nunca se inventa. La explicación que devuelve puede reescribirse con un proveedor de IA (ver
    Session.suggest_pitch_settings) para sonar más natural, pero los números no cambian.
    """
    dev = vocal.avg_cents_deviation
    reasons: list[str] = []

    if dev < 10:
        mode, amount = "Natural", 35.0
        reasons.append(f"tu afinación ya es muy precisa (se desvía solo {dev:.0f} cents de media)")
    elif dev < 25:
        mode, amount = "Balanced", 65.0
        reasons.append(f"tu afinación se desvía unos {dev:.0f} cents de media")
    else:
        mode, amount = "Hard Autotune", 90.0
        reasons.append(f"tu afinación se desvía bastante ({dev:.0f} cents de media)")

    base = MODE_PRESETS[mode]
    speed_ms, humanize = base["speed_ms"], base["humanize"]

    natural_vibrato = (vocal.vibrato_rate_hz is not None and 4.5 <= vocal.vibrato_rate_hz <= 7.0
                      and (vocal.vibrato_extent_cents or 0.0) <= 150.0)
    if natural_vibrato:
        speed_ms *= 1.8
        humanize = min(100.0, humanize + 20.0)
        reasons.append(f"tu vibrato ({vocal.vibrato_rate_hz:.1f} Hz) suena natural, así que se afloja "
                       "el retune para no aplastarlo")
    elif vocal.stability_cents > 30:
        speed_ms = max(5.0, speed_ms * 0.5)
        reasons.append(f"el tono tiembla dentro de las notas (variación de {vocal.stability_cents:.0f} "
                       "cents), así que se ajusta un retune más rápido para estabilizarlo")

    # 0.55: bastante por encima del 0.5 de "sin correlación" de estimate_key — evita sugerir una
    # tonalidad que el propio detector no tiene claro (ver voice_analysis/song.py:estimate_key).
    if song is not None and song.key_confidence > 0.55:
        key = song.key_root
        scale = "Mayor" if song.key_is_major else "Menor natural"
        reasons.append(f"la canción está en {song.key_label}")
    else:
        key, scale = "C", "Mayor"

    settings = CorrectionSettings(key=key, scale=scale, amount=amount, speed_ms=speed_ms,
                                  humanize=humanize, preserve_formants=preserve_formants, mode=mode)
    explanation = f"Sugerencia «{mode}» ({amount:.0f}%): " + "; ".join(reasons) + "."
    return settings, explanation


@dataclass
class NoteOverride:
    start: float
    end: float
    semitone_offset: int = 0
    bypass: bool = False

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "semitone_offset": self.semitone_offset,
                "bypass": self.bypass}

    @classmethod
    def from_dict(cls, data: dict) -> "NoteOverride":
        return cls(**data)


def overrides_from_notes(notes: list[NoteSegment]) -> list[NoteOverride]:
    return [NoteOverride(n.start, n.end, 0, False) for n in notes]


def _smooth_towards(quantized: np.ndarray, times: np.ndarray, speed_ms: float) -> np.ndarray:
    n = len(quantized)
    out = quantized.copy()
    if n < 2 or speed_ms <= 0:
        return out
    current = np.nan
    prev_t = times[0]
    for i in range(n):
        if np.isnan(quantized[i]):
            current = np.nan
            continue
        if np.isnan(current):
            current = quantized[i]
        else:
            dt_ms = max((times[i] - prev_t) * 1000.0, 1e-3)
            alpha = 1.0 - np.exp(-dt_ms / max(1.0, speed_ms))
            current = current + alpha * (quantized[i] - current)
        out[i] = current
        prev_t = times[i]
    return out


def _apply_humanize(corrected: np.ndarray, orig_midi: np.ndarray, times: np.ndarray,
                     notes: list[NoteSegment], humanize_pct: float, sustain_start: float = 0.25) -> np.ndarray:
    out = corrected.copy()
    h = float(np.clip(humanize_pct / 100.0, 0.0, 1.0))
    if h <= 0:
        return out
    for note in notes:
        if note.duration < 0.3:
            continue
        mask = (times >= note.start) & (times < note.end) & ~np.isnan(corrected)
        if not mask.any():
            continue
        rel = (times[mask] - note.start) / max(note.duration, 1e-6)
        rel = np.clip((rel - sustain_start) / max(1.0 - sustain_start, 1e-6), 0.0, 1.0)
        blend = h * rel
        out[mask] = corrected[mask] * (1 - blend) + orig_midi[mask] * blend
    return out


def _apply_overrides(final_midi: np.ndarray, orig_midi: np.ndarray, times: np.ndarray,
                      overrides: list[NoteOverride]) -> np.ndarray:
    out = final_midi.copy()
    for ov in overrides:
        mask = (times >= ov.start) & (times < ov.end) & ~np.isnan(out)
        if not mask.any():
            continue
        if ov.bypass:
            out[mask] = orig_midi[mask]
        else:
            out[mask] = out[mask] + ov.semitone_offset
    return out


def build_target_curve(track: PitchTrack, notes: list[NoteSegment], settings: CorrectionSettings,
                        overrides: list[NoteOverride] | None = None) -> np.ndarray:
    f0, times = track.f0, track.times
    n = len(f0)
    if n == 0:
        return np.zeros(0)
    voiced = ~np.isnan(f0)
    orig_midi = np.full(n, np.nan)
    orig_midi[voiced] = hz_to_midi(f0[voiced])
    if not voiced.any():
        return np.full(n, np.nan)

    smoothed_for_quantizing = median_smooth(orig_midi)
    quantized = np.full(n, np.nan)
    quantized[voiced] = [nearest_scale_midi(m, settings.key, settings.scale) for m in smoothed_for_quantizing[voiced]]

    corrected = _smooth_towards(quantized, times, settings.speed_ms)
    if settings.humanize > 0:
        corrected = _apply_humanize(corrected, orig_midi, times, notes, settings.humanize)

    amt = float(np.clip(settings.amount / 100.0, 0.0, 1.0))
    final_midi = np.where(voiced, orig_midi * (1 - amt) + corrected * amt, np.nan)

    if overrides:
        final_midi = _apply_overrides(final_midi, orig_midi, times, overrides)

    return np.where(~np.isnan(final_midi), midi_to_hz(np.nan_to_num(final_midi, nan=69.0)), np.nan)
