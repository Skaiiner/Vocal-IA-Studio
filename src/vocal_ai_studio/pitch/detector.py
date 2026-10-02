from __future__ import annotations

from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.pitch.yin import yin_pitch_track


class YinPitchDetector:
    name = "YIN (CPU)"

    def detect(self, samples, samplerate) -> PitchTrack:
        return yin_pitch_track(samples, samplerate)
