from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.audio.mix import MixTrack, mix_tracks
from vocal_ai_studio.audio.waveform import PeakCache
from tests.conftest import tone


def test_peak_cache_bounds_match_signal():
    x = tone(2.0, 440, channels=1).to_mono()
    cache = PeakCache(x)
    mins, maxs = cache.get(0, cache.frames, 100)
    assert len(mins) == len(maxs) <= 100
    assert maxs.max() == pytest.approx(x.max(), abs=0.01)
    assert mins.min() == pytest.approx(x.min(), abs=0.01)
    assert np.all(mins <= maxs)


def test_peak_cache_zoomed_window():
    x = np.concatenate([np.zeros(44100, np.float32), np.ones(44100, np.float32)])
    cache = PeakCache(x)
    quiet_max = cache.get(0, 40000, 50)[1].max()
    loud_max = cache.get(50000, 88200, 50)[1].max()
    assert quiet_max == pytest.approx(0.0, abs=1e-6)
    assert loud_max == pytest.approx(1.0)


def test_peak_cache_empty_and_short():
    assert PeakCache(np.zeros(0, np.float32)).get(0, 10, 10)[0].size == 0
    assert PeakCache(np.ones(5, np.float32)).get(0, 5, 10)[1].max() == pytest.approx(1.0)


def test_mix_applies_offset_and_gain():
    song = tone(1.0, 220, channels=2, amp=0.4)
    vocal = tone(0.5, 440, channels=1, amp=0.4)
    out = mix_tracks([MixTrack(song, 1.0), MixTrack(vocal, 0.5, offset_sec=0.5)], 44100, 2)
    assert out.duration == pytest.approx(1.0, abs=0.01)
    first_half_peak = float(np.max(np.abs(out.samples[:22050])))
    second_half_peak = float(np.max(np.abs(out.samples[22050:])))
    assert second_half_peak > first_half_peak


def test_mix_extends_to_longest_track_and_avoids_clipping():
    out = mix_tracks([MixTrack(tone(0.2, 440, channels=2, amp=0.9)),
                      MixTrack(tone(1.0, 440, channels=2, amp=0.9))], 44100, 2)
    assert out.duration == pytest.approx(1.0, abs=0.01)
    assert float(np.max(np.abs(out.samples))) <= 1.0


def test_mix_empty_returns_silence():
    assert mix_tracks([], 44100).frames == 0


def test_mix_rejects_mismatched_samplerate():
    with pytest.raises(ValueError):
        mix_tracks([MixTrack(tone(0.1, sr=48000))], 44100)
