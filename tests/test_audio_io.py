from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.audio.io import AudioData, conform_channels, load_audio, resample, save_audio
from vocal_ai_studio.core.errors import AppError
from tests.conftest import tone


def test_audiodata_shapes_and_duration():
    a = AudioData(np.zeros(44100, np.float32), 44100)
    assert a.channels == 1 and a.frames == 44100 and a.duration == pytest.approx(1.0)
    assert tone(0.5, channels=2).channels == 2


def test_conform_channels_roundtrip():
    stereo = np.stack([np.ones(10), np.zeros(10)], axis=1).astype(np.float32)
    assert conform_channels(stereo, 1).shape == (10, 1)
    assert conform_channels(stereo, 1)[0, 0] == pytest.approx(0.5)
    assert conform_channels(np.ones((10, 1), np.float32), 2).shape == (10, 2)


def test_resample_changes_length_and_keeps_frequency():
    a = tone(1.0, 440.0, sr=44100, channels=1)
    out = resample(a.samples, 44100, 22050)
    assert out.shape[0] == pytest.approx(22050, abs=10)
    spec = np.abs(np.fft.rfft(out[:, 0]))
    peak_hz = np.fft.rfftfreq(out.shape[0], 1 / 22050)[int(np.argmax(spec))]
    assert peak_hz == pytest.approx(440, abs=5)


@pytest.mark.parametrize("fmt", ["wav", "flac", "mp3"])
def test_save_and_load_roundtrip(tmp_path, fmt):
    src = tone(0.5, 440.0, channels=2)
    path = save_audio(tmp_path / f"out.{fmt}", src)
    assert path.exists() and path.stat().st_size > 0
    back = load_audio(path, samplerate=src.samplerate, channels=2)
    assert back.duration == pytest.approx(src.duration, abs=0.1)  # mp3 añade padding
    assert float(np.max(np.abs(back.to_mono()))) > 0.2


def test_load_missing_file_gives_helpful_error(tmp_path):
    with pytest.raises(AppError) as err:
        load_audio(tmp_path / "nope.wav")
    assert "Cómo solucionarlo" in err.value.user_message()


def test_load_rejects_unsupported_format(tmp_path):
    bogus = tmp_path / "fake.mp3"
    bogus.write_bytes(b"this is not audio")
    with pytest.raises(AppError):
        load_audio(bogus)


def test_save_unsupported_format_raises(tmp_path):
    with pytest.raises(AppError):
        save_audio(tmp_path / "x.aac", tone(0.1), "aac")


def test_load_converts_samplerate_and_channels(tmp_path):
    save_audio(tmp_path / "a.wav", tone(0.3, 440, sr=48000, channels=2))
    out = load_audio(tmp_path / "a.wav", samplerate=44100, channels=1)
    assert out.samplerate == 44100 and out.channels == 1
    assert out.duration == pytest.approx(0.3, abs=0.01)
