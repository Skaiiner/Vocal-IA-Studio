from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt, windows

from vocal_ai_studio.effects.chain import VoiceLabSettings
from vocal_ai_studio.effects.eq import _high_shelf_sos, _low_shelf_sos, _peak_sos
from vocal_ai_studio.effects.reverb import (
    _ALLPASS_DELAYS_44,
    _ALLPASS_GAIN,
    _COMB_DECAYS,
    _COMB_DELAYS_44,
)


def _build_eq_sos(sr: int, bands: list[dict]) -> np.ndarray:
    sos_list = []
    for band in bands:
        t = band.get("type", "peak")
        freq = float(np.clip(band.get("freq", 1000.0), 20.0, sr / 2.0 - 1))
        gain_db = float(band.get("gain_db", 0.0))
        q = float(band.get("q", 1.0))
        if t == "low_shelf":
            sos_list.append(_low_shelf_sos(freq, gain_db, sr))
        elif t == "high_shelf":
            sos_list.append(_high_shelf_sos(freq, gain_db, sr))
        else:
            sos_list.append(_peak_sos(freq, gain_db, q, sr))
    return np.vstack(sos_list)


class StreamingEq:
    def __init__(self) -> None:
        self._sos: np.ndarray | None = None
        self._zi: np.ndarray | None = None

    def reset(self) -> None:
        self._sos = None
        self._zi = None

    def process(self, block: np.ndarray, sr: int, bands: list[dict]) -> np.ndarray:
        if not bands:
            return block
        sos = _build_eq_sos(sr, bands)
        if self._zi is None or self._sos is None or self._sos.shape != sos.shape:
            self._zi = np.zeros((sos.shape[0], 2), dtype=np.float64)
        self._sos = sos
        out, self._zi = sosfilt(self._sos, block.astype(np.float64), zi=self._zi)
        return out.astype(np.float32)


class StreamingDeEsser:
    def __init__(self) -> None:
        self._sos_bp: np.ndarray | None = None
        self._sos_hp: np.ndarray | None = None
        self._sos_lp: np.ndarray | None = None
        self._zi_bp: np.ndarray | None = None
        self._zi_hp: np.ndarray | None = None
        self._zi_lp: np.ndarray | None = None
        self._key: tuple | None = None
        self._gain = 1.0

    def reset(self) -> None:
        self._zi_bp = self._zi_hp = self._zi_lp = None
        self._key = None
        self._gain = 1.0

    def process(self, block: np.ndarray, sr: int, threshold_db: float,
                freq_hz: float, bandwidth: float) -> np.ndarray:
        low = max(20.0, freq_hz - bandwidth / 2.0)
        high = min(sr / 2.0 - 1.0, freq_hz + bandwidth / 2.0)
        if low >= high:
            return block

        key = (sr, round(low, 3), round(high, 3))
        if key != self._key:
            self._sos_bp = butter(2, [low / (sr / 2.0), high / (sr / 2.0)], btype="band", output="sos")
            self._sos_hp = butter(1, low / (sr / 2.0), btype="high", output="sos")
            self._sos_lp = butter(1, high / (sr / 2.0), btype="low", output="sos")
            self._zi_bp = np.zeros((self._sos_bp.shape[0], 2), dtype=np.float64)
            self._zi_hp = np.zeros((self._sos_hp.shape[0], 2), dtype=np.float64)
            self._zi_lp = np.zeros((self._sos_lp.shape[0], 2), dtype=np.float64)
            self._key = key

        x = block.astype(np.float64)
        detect, self._zi_bp = sosfilt(self._sos_bp, x, zi=self._zi_bp)
        rms = max(float(np.sqrt(np.mean(detect ** 2) + 1e-12)), 1e-9)
        rms_db = 20.0 * np.log10(rms)
        target_gain = 1.0
        if rms_db > threshold_db:
            target_gain = 10.0 ** (-(rms_db - threshold_db) * 0.5 / 20.0)
        # suavizado bloque a bloque: evita saltos de ganancia entre callbacks
        self._gain += 0.3 * (target_gain - self._gain)

        hp, self._zi_hp = sosfilt(self._sos_hp, x, zi=self._zi_hp)
        lp, self._zi_lp = sosfilt(self._sos_lp, x, zi=self._zi_lp)
        return (lp + hp * self._gain).astype(np.float32)


class StreamingCompressor:
    def __init__(self) -> None:
        self._env_db = -120.0

    def reset(self) -> None:
        self._env_db = -120.0

    def process(self, block: np.ndarray, sr: int, threshold_db: float, ratio: float,
                attack_ms: float, release_ms: float, makeup_db: float) -> np.ndarray:
        attack_coef = float(np.exp(-1.0 / (max(0.001, attack_ms / 1000.0) * sr)))
        release_coef = float(np.exp(-1.0 / (max(0.001, release_ms / 1000.0) * sr)))
        x = block.astype(np.float64)
        level_db = 20.0 * np.log10(np.maximum(np.abs(x), 1e-9))
        env_db = self._env_db
        gain_db = np.empty_like(x)
        for i in range(len(x)):
            lvl = level_db[i]
            coef = attack_coef if lvl > env_db else release_coef
            env_db = coef * env_db + (1.0 - coef) * lvl
            gr = (env_db - threshold_db) * (1.0 - 1.0 / max(1.0, ratio)) if env_db > threshold_db else 0.0
            gain_db[i] = makeup_db - gr
        self._env_db = env_db
        return (x * 10.0 ** (gain_db / 20.0)).astype(np.float32)


class StreamingReverb:
    def __init__(self) -> None:
        self._comb_delays: list[int] | None = None
        self._decays: list[float] | None = None
        self._comb_bufs: list[np.ndarray] | None = None
        self._comb_pos: list[int] | None = None
        self._allpass_delays: list[int] | None = None
        self._allpass_bufs: list[np.ndarray] | None = None
        self._allpass_pos: list[int] | None = None
        self._key: tuple | None = None

    def reset(self) -> None:
        self._comb_bufs = self._allpass_bufs = None
        self._key = None

    def _ensure(self, sr: int, room_size: float) -> None:
        room = float(np.clip(room_size, 0.0, 1.0))
        key = (sr, round(room, 3))
        if key == self._key and self._comb_bufs is not None:
            return
        scale = sr / 44100.0
        self._comb_delays = [max(2, int(d * scale)) for d in _COMB_DELAYS_44]
        self._decays = [d * (0.6 + 0.35 * room) for d in _COMB_DECAYS]
        self._comb_bufs = [np.zeros(d, dtype=np.float64) for d in self._comb_delays]
        self._comb_pos = [0] * len(self._comb_delays)
        self._allpass_delays = [max(2, int(d * scale)) for d in _ALLPASS_DELAYS_44]
        self._allpass_bufs = [np.zeros(d, dtype=np.float64) for d in self._allpass_delays]
        self._allpass_pos = [0] * len(self._allpass_delays)
        self._key = key

    def _comb_block(self, x: np.ndarray, idx: int) -> np.ndarray:
        delay = self._comb_delays[idx]
        decay = self._decays[idx]
        buf = self._comb_bufs[idx]
        pos = self._comb_pos[idx]
        out = np.empty_like(x)
        for i in range(len(x)):
            out[i] = x[i] + buf[pos] * decay
            buf[pos] = out[i]
            pos = (pos + 1) % delay
        self._comb_pos[idx] = pos
        return out

    def _allpass_block(self, x: np.ndarray, idx: int) -> np.ndarray:
        delay = self._allpass_delays[idx]
        buf = self._allpass_bufs[idx]
        pos = self._allpass_pos[idx]
        out = np.empty_like(x)
        for i in range(len(x)):
            delayed = buf[pos]
            v = x[i] + _ALLPASS_GAIN * delayed
            out[i] = -_ALLPASS_GAIN * v + delayed
            buf[pos] = v
            pos = (pos + 1) % delay
        self._allpass_pos[idx] = pos
        return out

    def process(self, block: np.ndarray, sr: int, room_size: float, wet: float) -> np.ndarray:
        if wet <= 0.001:
            return block
        self._ensure(sr, room_size)
        x = block.astype(np.float64)
        wet_sig = np.zeros_like(x)
        for idx in range(len(self._comb_delays)):
            wet_sig += self._comb_block(x, idx)
        wet_sig /= len(self._comb_delays)
        for idx in range(len(self._allpass_delays)):
            wet_sig = self._allpass_block(wet_sig, idx)
        # red con feedback/decay < 1 ya está acotada; un soft-clip cubre picos puntuales
        wet_sig = np.clip(wet_sig, -1.0, 1.0)
        wet = float(np.clip(wet, 0.0, 1.0))
        return (x * (1 - wet) + wet_sig * wet).astype(np.float32)


class StreamingDelay:
    def __init__(self) -> None:
        self._buf: np.ndarray | None = None
        self._pos = 0
        self._delay_samples: int | None = None

    def reset(self) -> None:
        self._buf = None
        self._pos = 0
        self._delay_samples = None

    def _ensure(self, sr: int, time_ms: float) -> None:
        delay_samples = max(1, int(time_ms * sr / 1000.0))
        if self._buf is None or self._delay_samples != delay_samples:
            self._buf = np.zeros(delay_samples, dtype=np.float64)
            self._pos = 0
            self._delay_samples = delay_samples

    def process(self, block: np.ndarray, sr: int, time_ms: float, feedback: float, wet: float) -> np.ndarray:
        if wet <= 0.001:
            return block
        self._ensure(sr, time_ms)
        feedback = float(np.clip(feedback, 0.0, 0.95))
        wet = float(np.clip(wet, 0.0, 1.0))
        x = block.astype(np.float64)
        buf = self._buf
        delay = self._delay_samples
        pos = self._pos
        out = np.empty_like(x)
        for i in range(len(x)):
            delayed = buf[pos]
            out[i] = delayed
            buf[pos] = x[i] + delayed * feedback
            pos = (pos + 1) % delay
        self._pos = pos
        out = np.clip(out, -1.0, 1.0)
        return (x * (1 - wet) + out * wet).astype(np.float32)


class StreamingFormantShifter:
    def __init__(self, hop_ms: float = 5.0, win_ms: float = 25.0) -> None:
        self._hop_ms = hop_ms
        self._win_ms = win_ms
        self._sr: int | None = None
        self._hop = 0
        self._n_fft = 0
        self._window: np.ndarray | None = None
        self._freqs: np.ndarray | None = None
        self._in_buf: np.ndarray | None = None
        self._out_buf: np.ndarray | None = None
        self._norm_buf: np.ndarray | None = None
        self._pending_in = np.zeros(0, dtype=np.float64)
        self._ready_out = np.zeros(0, dtype=np.float64)
        self._in_rms = 1e-6
        self._out_rms = 1e-6
        self._hops_done = 0
        self._warmup_hops = 0

    def reset(self) -> None:
        self._sr = None

    def _setup(self, sr: int) -> None:
        if self._sr == sr:
            return
        self._sr = sr
        self._hop = max(1, int(self._hop_ms * sr / 1000.0))
        win_size = max(self._hop * 2, int(self._win_ms * sr / 1000.0))
        n_fft = 1
        while n_fft < win_size:
            n_fft <<= 1
        self._n_fft = n_fft
        self._window = windows.hann(n_fft, sym=False).astype(np.float64)
        self._freqs = np.arange(n_fft // 2 + 1, dtype=np.float64)
        self._in_buf = np.zeros(n_fft, dtype=np.float64)
        self._out_buf = np.zeros(n_fft, dtype=np.float64)
        self._norm_buf = np.zeros(n_fft, dtype=np.float64)
        self._pending_in = np.zeros(0, dtype=np.float64)
        self._ready_out = np.zeros(0, dtype=np.float64)
        self._in_rms = 1e-6
        self._out_rms = 1e-6
        self._hops_done = 0
        # hasta que suficientes ventanas se solapen, la normalización de Hann
        # divide por valores de ventana casi nulos en los bordes y dispara el resultado
        self._warmup_hops = -(-self._n_fft // self._hop)

    def _process_hop(self, hop_chunk: np.ndarray, semitones: float) -> np.ndarray:
        factor = 2.0 ** (semitones / 12.0)
        hop = self._hop
        n_fft = self._n_fft
        self._in_buf = np.concatenate([self._in_buf[hop:], hop_chunk])
        frame = self._in_buf * self._window
        spec = np.fft.rfft(frame)
        mag = np.abs(spec)
        phase = np.angle(spec)
        src_freqs = np.clip(self._freqs * factor, 0, n_fft // 2)
        mag_new = np.interp(self._freqs, src_freqs, mag)
        frame_out = np.fft.irfft(mag_new * np.exp(1j * phase), n_fft)

        self._out_buf = np.concatenate([self._out_buf[hop:], np.zeros(hop)])
        self._norm_buf = np.concatenate([self._norm_buf[hop:], np.zeros(hop)])
        self._out_buf += frame_out * self._window
        self._norm_buf += self._window ** 2
        self._hops_done += 1
        if self._hops_done <= self._warmup_hops:
            return np.zeros(hop, dtype=np.float64)
        return self._out_buf[:hop] / np.maximum(self._norm_buf[:hop], 1e-8)

    def process(self, block: np.ndarray, sr: int, semitones: float) -> np.ndarray:
        if abs(semitones) < 0.01:
            return block
        self._setup(sr)
        x = block.astype(np.float64)
        n = len(x)

        in_block_rms = float(np.sqrt(np.mean(x ** 2) + 1e-12))
        self._in_rms = 0.95 * self._in_rms + 0.05 * in_block_rms

        self._pending_in = np.concatenate([self._pending_in, x])
        while len(self._pending_in) >= self._hop:
            hop_chunk = self._pending_in[:self._hop]
            self._pending_in = self._pending_in[self._hop:]
            ready = self._process_hop(hop_chunk, semitones)
            self._ready_out = np.concatenate([self._ready_out, ready])

        if len(self._ready_out) >= n:
            out = self._ready_out[:n]
            self._ready_out = self._ready_out[n:]
        else:
            # latencia inherente del vocoder de fase: arranca con silencio hasta llenar la ventana
            out = np.concatenate([self._ready_out, np.zeros(n - len(self._ready_out))])
            self._ready_out = np.zeros(0, dtype=np.float64)

        out_block_rms = float(np.sqrt(np.mean(out ** 2) + 1e-12))
        self._out_rms = 0.95 * self._out_rms + 0.05 * out_block_rms
        if self._out_rms > 1e-8:
            # acotado: al salir del silencio inicial del vocoder, _out_rms aún no se
            # ha estabilizado y el cociente puede dispararse por unos bloques
            ratio = float(np.clip(self._in_rms / self._out_rms, 0.25, 4.0))
            out = out * ratio
        return out.astype(np.float32)


class StreamingChain:
    def __init__(self, sr: int) -> None:
        self.sr = sr
        self.formants = StreamingFormantShifter()
        self.eq = StreamingEq()
        self.de_esser = StreamingDeEsser()
        self.compressor = StreamingCompressor()
        self.reverb = StreamingReverb()
        self.delay = StreamingDelay()

    def reset(self) -> None:
        self.formants.reset()
        self.eq.reset()
        self.de_esser.reset()
        self.compressor.reset()
        self.reverb.reset()
        self.delay.reset()

    def process(self, block: np.ndarray, settings: VoiceLabSettings) -> np.ndarray:
        sr = self.sr
        out = block.astype(np.float32)

        if abs(settings.formant_shift) > 0.01:
            out = self.formants.process(out, sr, settings.formant_shift)

        eq_active = any(abs(b.get("gain_db", 0.0)) > 0.01 for b in settings.eq_bands)
        if eq_active:
            out = self.eq.process(out, sr, settings.eq_bands)

        if settings.de_esser.enabled:
            de = settings.de_esser
            out = self.de_esser.process(out, sr, de.threshold_db, de.freq_hz, de.bandwidth)

        if settings.compressor.enabled:
            c = settings.compressor
            out = self.compressor.process(out, sr, c.threshold_db, c.ratio, c.attack_ms, c.release_ms, c.makeup_db)

        if settings.reverb.enabled:
            out = self.reverb.process(out, sr, settings.reverb.room_size, settings.reverb.wet)

        if settings.delay.enabled:
            d = settings.delay
            out = self.delay.process(out, sr, d.time_ms, d.feedback, d.wet)

        return out
