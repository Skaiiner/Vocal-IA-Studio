from __future__ import annotations

import numpy as np
import pytest
import torch

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.voice_conversion.content_encoder import ContentEncoder
from vocal_ai_studio.voice_conversion.model import RVCVoiceConversionModel
from vocal_ai_studio.voice_conversion.synthesizer import Synthesizer

SR = 44100

TINY_CONFIG = [
    80,            # spec_channels (sin uso en inferencia)
    32,            # segment_size (sin uso en inferencia)
    8,             # inter_channels
    16,            # hidden_channels
    32,            # filter_channels
    2,             # n_heads
    1,             # n_layers
    3,             # kernel_size
    0.0,           # p_dropout
    "1",           # resblock
    [3],           # resblock_kernel_sizes
    [[1, 3, 5]],   # resblock_dilation_sizes
    [4, 4],        # upsample_rates (k - u debe ser par para que las longitudes cuadren exacto)
    16,            # upsample_initial_channel
    [8, 8],        # upsample_kernel_sizes
    1,             # spk_embed_dim
    8,             # gin_channels
    16000,         # sr
]


def build_tiny_checkpoint(path):
    torch.manual_seed(0)
    synth = Synthesizer(*TINY_CONFIG, is_half=False)
    synth.eval()
    torch.save(
        {"config": list(TINY_CONFIG), "weight": synth.state_dict(), "f0": 1, "version": "v2"},
        path,
    )
    return synth


def sine(freq=220.0, seconds=0.5, sr=SR, amp=0.4):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def fake_extract(self, samples_16k):
    n_frames = max(4, len(samples_16k) // 320)
    return np.random.randn(n_frames, 768).astype(np.float32)


def test_synthesizer_infer_produces_audio():
    synth = Synthesizer(*TINY_CONFIG, is_half=False)
    synth.eval()
    t = 20
    phone = torch.randn(1, t, 768)
    phone_lengths = torch.tensor([t])
    pitch = torch.randint(1, 255, (1, t))
    nsff0 = torch.rand(1, t) * 200.0
    sid = torch.zeros(1, dtype=torch.long)
    out, x_mask, _ = synth.infer(phone, phone_lengths, pitch, nsff0, sid)
    assert out.shape[0] == 1
    assert out.shape[1] == 1
    assert out.shape[2] == t * 16  # upp = prod(upsample_rates) = 4*4


def test_load_checkpoint_rejects_v1(tmp_path):
    from vocal_ai_studio.voice_conversion.checkpoint import load_checkpoint

    synth = Synthesizer(*TINY_CONFIG, is_half=False)
    path = tmp_path / "v1.pth"
    torch.save({"config": list(TINY_CONFIG), "weight": synth.state_dict(), "f0": 1, "version": "v1"}, path)
    with pytest.raises(AppError):
        load_checkpoint(str(path), "cpu")


def test_load_checkpoint_rejects_no_f0(tmp_path):
    from vocal_ai_studio.voice_conversion.checkpoint import load_checkpoint

    synth = Synthesizer(*TINY_CONFIG, is_half=False)
    path = tmp_path / "nof0.pth"
    torch.save({"config": list(TINY_CONFIG), "weight": synth.state_dict(), "f0": 0, "version": "v2"}, path)
    with pytest.raises(AppError):
        load_checkpoint(str(path), "cpu")


def test_load_checkpoint_builds_synthesizer(tmp_path):
    from vocal_ai_studio.voice_conversion.checkpoint import load_checkpoint

    path = tmp_path / "model.pth"
    build_tiny_checkpoint(path)
    cpt = load_checkpoint(str(path), "cpu")
    assert cpt.target_sr == 16000
    assert cpt.speaker_dim == 1
    assert isinstance(cpt.synthesizer, Synthesizer)


def test_convert_end_to_end_with_synthetic_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(ContentEncoder, "extract", fake_extract)

    path = tmp_path / "model.pth"
    build_tiny_checkpoint(path)

    model = RVCVoiceConversionModel()
    model.load("cpu")

    x = sine(seconds=0.5)
    progress_calls = []
    result = model.convert(
        x, SR,
        model_path=str(path),
        progress=progress_calls.append,
    )
    assert isinstance(result, np.ndarray)
    assert len(result) > 0
    assert np.isfinite(result).all()
    assert progress_calls[0] == pytest.approx(0.05)
    assert progress_calls[-1] == pytest.approx(1.0)


def test_convert_without_model_path_raises(monkeypatch):
    monkeypatch.setattr(ContentEncoder, "extract", fake_extract)
    model = RVCVoiceConversionModel()
    model.load("cpu")
    with pytest.raises(AppError):
        model.convert(sine(seconds=0.1), SR, model_path="")


def test_convert_cancelled_raises(tmp_path, monkeypatch):
    from vocal_ai_studio.voice_conversion.model import VoiceConversionCancelled

    monkeypatch.setattr(ContentEncoder, "extract", fake_extract)
    path = tmp_path / "model.pth"
    build_tiny_checkpoint(path)

    model = RVCVoiceConversionModel()
    model.load("cpu")
    with pytest.raises(VoiceConversionCancelled):
        model.convert(sine(seconds=0.2), SR, model_path=str(path), cancelled=lambda: True)


def test_convert_caches_checkpoint_across_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(ContentEncoder, "extract", fake_extract)
    path = tmp_path / "model.pth"
    build_tiny_checkpoint(path)

    model = RVCVoiceConversionModel()
    model.load("cpu")
    model.convert(sine(seconds=0.2), SR, model_path=str(path))
    cpt_first = model._checkpoints[str(path)]
    model.convert(sine(seconds=0.2), SR, model_path=str(path))
    cpt_second = model._checkpoints[str(path)]
    assert cpt_first is cpt_second


# --- session integration ---

def test_session_convert_voice_creates_take(backend, tmp_path, monkeypatch):
    import soundfile as sf

    import vocal_ai_studio.session as session_mod
    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    monkeypatch.setattr(ContentEncoder, "extract", fake_extract)
    monkeypatch.setattr(session_mod, "detect_hardware",
                         lambda: type("HW", (), {"recommended_device": "cpu"})())

    model_path = tmp_path / "model.pth"
    build_tiny_checkpoint(model_path)

    wav = tmp_path / "voz.wav"
    sf.write(str(wav), sine(seconds=0.3), SR)

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("VoiceConversion")
    s.import_vocal_as_take(wav)
    before = len(s.project.data.takes)

    take = s.convert_voice(model_path=str(model_path))
    assert "conversión de voz" in take.name
    assert len(s.project.data.takes) == before + 1
    s.close()


def test_session_convert_voice_without_vocal_raises(backend, tmp_path):
    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("NoVocal")
    with pytest.raises(AppError):
        s.convert_voice(model_path="irrelevant.pth")
    s.close()
