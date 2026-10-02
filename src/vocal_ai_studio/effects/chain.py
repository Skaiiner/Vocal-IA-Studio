from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from vocal_ai_studio.effects.dynamics import apply_compressor, apply_deesser
from vocal_ai_studio.effects.eq import apply_eq
from vocal_ai_studio.effects.formants import shift_formants
from vocal_ai_studio.effects.reverb import apply_delay, apply_reverb


def _default_eq_bands() -> list[dict]:
    return [
        {"type": "low_shelf",  "freq": 100,  "gain_db": 0.0, "q": 0.7},
        {"type": "peak",       "freq": 300,  "gain_db": 0.0, "q": 1.0},
        {"type": "peak",       "freq": 1000, "gain_db": 0.0, "q": 1.0},
        {"type": "peak",       "freq": 3500, "gain_db": 0.0, "q": 1.0},
        {"type": "high_shelf", "freq": 8000, "gain_db": 0.0, "q": 0.7},
    ]


@dataclass
class CompressorSettings:
    enabled: bool = False
    threshold_db: float = -18.0
    ratio: float = 3.0
    attack_ms: float = 5.0
    release_ms: float = 50.0
    makeup_db: float = 0.0

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "threshold_db": self.threshold_db,
                "ratio": self.ratio, "attack_ms": self.attack_ms,
                "release_ms": self.release_ms, "makeup_db": self.makeup_db}

    @classmethod
    def from_dict(cls, d: dict) -> "CompressorSettings":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DeEsserSettings:
    enabled: bool = False
    threshold_db: float = -20.0
    freq_hz: float = 7000.0
    bandwidth: float = 3000.0

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "threshold_db": self.threshold_db,
                "freq_hz": self.freq_hz, "bandwidth": self.bandwidth}

    @classmethod
    def from_dict(cls, d: dict) -> "DeEsserSettings":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ReverbSettings:
    enabled: bool = False
    room_size: float = 0.3
    wet: float = 0.15

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "room_size": self.room_size, "wet": self.wet}

    @classmethod
    def from_dict(cls, d: dict) -> "ReverbSettings":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DelaySettings:
    enabled: bool = False
    time_ms: float = 250.0
    feedback: float = 0.3
    wet: float = 0.2

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "time_ms": self.time_ms,
                "feedback": self.feedback, "wet": self.wet}

    @classmethod
    def from_dict(cls, d: dict) -> "DelaySettings":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class VoiceLabSettings:
    formant_shift: float = 0.0
    eq_bands: list[dict] = field(default_factory=_default_eq_bands)
    compressor: CompressorSettings = field(default_factory=CompressorSettings)
    de_esser: DeEsserSettings = field(default_factory=DeEsserSettings)
    reverb: ReverbSettings = field(default_factory=ReverbSettings)
    delay: DelaySettings = field(default_factory=DelaySettings)
    preset_name: str = "Custom"

    def to_dict(self) -> dict:
        return {
            "formant_shift": self.formant_shift,
            "eq_bands": list(self.eq_bands),
            "compressor": self.compressor.to_dict(),
            "de_esser": self.de_esser.to_dict(),
            "reverb": self.reverb.to_dict(),
            "delay": self.delay.to_dict(),
            "preset_name": self.preset_name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VoiceLabSettings":
        return cls(
            formant_shift=float(d.get("formant_shift", 0.0)),
            eq_bands=d.get("eq_bands", _default_eq_bands()),
            compressor=CompressorSettings.from_dict(d.get("compressor", {})),
            de_esser=DeEsserSettings.from_dict(d.get("de_esser", {})),
            reverb=ReverbSettings.from_dict(d.get("reverb", {})),
            delay=DelaySettings.from_dict(d.get("delay", {})),
            preset_name=d.get("preset_name", "Custom"),
        )

    @classmethod
    def from_preset(cls, preset_name: str) -> "VoiceLabSettings":
        from vocal_ai_studio.effects.presets import PRESETS
        if preset_name not in PRESETS:
            return cls()
        d = PRESETS[preset_name]
        obj = cls.from_dict(d)
        obj.preset_name = preset_name
        return obj


Progress = Callable[[float, str], None]
Cancelled = Callable[[], bool]


def apply_chain(
    samples: np.ndarray,
    sr: int,
    settings: VoiceLabSettings,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> np.ndarray:
    def _prog(f: float, msg: str) -> None:
        if progress:
            progress(f, msg)

    def _done() -> bool:
        return bool(cancelled and cancelled())

    out = samples.astype(np.float32)
    _prog(0.0, "Iniciando Voice Lab…")

    if abs(settings.formant_shift) > 0.01 and not _done():
        _prog(0.05, "Ajustando formantes…")
        out = shift_formants(out, sr, settings.formant_shift)

    if _done():
        return out

    eq_active = any(abs(b.get("gain_db", 0.0)) > 0.01 for b in settings.eq_bands)
    if eq_active and not _done():
        _prog(0.25, "Aplicando EQ…")
        out = apply_eq(out, sr, settings.eq_bands)

    if _done():
        return out

    if settings.de_esser.enabled and not _done():
        _prog(0.40, "Aplicando de-esser…")
        de = settings.de_esser
        out = apply_deesser(out, sr, de.threshold_db, de.freq_hz, de.bandwidth)

    if _done():
        return out

    if settings.compressor.enabled and not _done():
        _prog(0.55, "Aplicando compresor…")
        c = settings.compressor
        out = apply_compressor(out, sr, c.threshold_db, c.ratio, c.attack_ms, c.release_ms, c.makeup_db)

    if _done():
        return out

    if settings.reverb.enabled and not _done():
        _prog(0.70, "Aplicando reverb…")
        out = apply_reverb(out, sr, settings.reverb.room_size, settings.reverb.wet)

    if _done():
        return out

    if settings.delay.enabled and not _done():
        _prog(0.85, "Aplicando delay…")
        d = settings.delay
        out = apply_delay(out, sr, d.time_ms, d.feedback, d.wet)

    _prog(1.0, "Voice Lab completado.")
    return out
