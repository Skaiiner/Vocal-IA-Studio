from __future__ import annotations

import math

import numpy as np
import torch
from torch import nn
from torch.nn import Conv1d, ConvTranspose1d
from torch.nn import functional as F
from torch.nn.utils import weight_norm

from vocal_ai_studio.voice_conversion import attentions, commons, modules


class TextEncoder768(nn.Module):
    # Encoder del contenido lingüístico: toma características de 768 dimensiones (content-vec/HuBERT capa 12).
    def __init__(self, out_channels, hidden_channels, filter_channels, n_heads, n_layers,
                 kernel_size, p_dropout, f0=True):
        super().__init__()
        self.out_channels = out_channels
        self.hidden_channels = hidden_channels
        self.emb_phone = nn.Linear(768, hidden_channels)
        self.lrelu = nn.LeakyReLU(0.1, inplace=True)
        if f0:
            self.emb_pitch = nn.Embedding(256, hidden_channels)
        self.encoder = attentions.Encoder(hidden_channels, filter_channels, n_heads, n_layers,
                                          kernel_size, p_dropout)
        self.proj = nn.Conv1d(hidden_channels, out_channels * 2, 1)

    def forward(self, phone, pitch, lengths):
        if pitch is None:
            x = self.emb_phone(phone)
        else:
            x = self.emb_phone(phone) + self.emb_pitch(pitch)
        x = x * math.sqrt(self.hidden_channels)
        x = self.lrelu(x)
        x = torch.transpose(x, 1, -1)
        x_mask = torch.unsqueeze(commons.sequence_mask(lengths, x.size(2)), 1).to(x.dtype)
        x = self.encoder(x * x_mask, x_mask)
        stats = self.proj(x) * x_mask
        m, logs = torch.split(stats, self.out_channels, dim=1)
        return m, logs, x_mask


class ResidualCouplingBlock(nn.Module):
    def __init__(self, channels, hidden_channels, kernel_size, dilation_rate, n_layers,
                 n_flows=4, gin_channels=0):
        super().__init__()
        self.n_flows = n_flows
        self.flows = nn.ModuleList()
        for _ in range(n_flows):
            self.flows.append(modules.ResidualCouplingLayer(
                channels, hidden_channels, kernel_size, dilation_rate, n_layers,
                gin_channels=gin_channels, mean_only=True,
            ))
            self.flows.append(modules.Flip())

    def forward(self, x, x_mask, g=None, reverse=False):
        if not reverse:
            for flow in self.flows:
                x, _ = flow(x, x_mask, g=g, reverse=reverse)
        else:
            for flow in reversed(self.flows):
                x = flow(x, x_mask, g=g, reverse=reverse)
        return x

    def remove_weight_norm(self):
        for i in range(self.n_flows):
            self.flows[i * 2].remove_weight_norm()


class SineGen(torch.nn.Module):
    # Genera el armónico de la fundamental (NSF): sin(2*pi*f0*t) más ruido en tramos sordos.
    def __init__(self, samp_rate, harmonic_num=0, sine_amp=0.1, noise_std=0.003, voiced_threshold=0):
        super().__init__()
        self.sine_amp = sine_amp
        self.noise_std = noise_std
        self.harmonic_num = harmonic_num
        self.dim = harmonic_num + 1
        self.sampling_rate = samp_rate
        self.voiced_threshold = voiced_threshold

    def _f02uv(self, f0):
        return torch.ones_like(f0) * (f0 > self.voiced_threshold)

    def forward(self, f0, upp):
        with torch.no_grad():
            f0 = f0[:, None].transpose(1, 2)
            f0_buf = torch.zeros(f0.shape[0], f0.shape[1], self.dim, device=f0.device)
            f0_buf[:, :, 0] = f0[:, :, 0]
            for idx in np.arange(self.harmonic_num):
                f0_buf[:, :, idx + 1] = f0_buf[:, :, 0] * (idx + 2)
            rad_values = (f0_buf / self.sampling_rate) % 1
            rand_ini = torch.rand(f0_buf.shape[0], f0_buf.shape[2], device=f0_buf.device)
            rand_ini[:, 0] = 0
            rad_values[:, 0, :] = rad_values[:, 0, :] + rand_ini
            tmp_over_one = torch.cumsum(rad_values, 1)
            tmp_over_one *= upp
            tmp_over_one = F.interpolate(
                tmp_over_one.transpose(2, 1), scale_factor=float(upp), mode="linear", align_corners=True,
            ).transpose(2, 1)
            rad_values = F.interpolate(
                rad_values.transpose(2, 1), scale_factor=float(upp), mode="nearest",
            ).transpose(2, 1)
            tmp_over_one %= 1
            tmp_over_one_idx = (tmp_over_one[:, 1:, :] - tmp_over_one[:, :-1, :]) < 0
            cumsum_shift = torch.zeros_like(rad_values)
            cumsum_shift[:, 1:, :] = tmp_over_one_idx * -1.0
            sine_waves = torch.sin(torch.cumsum(rad_values + cumsum_shift, dim=1) * 2 * np.pi)
            sine_waves = sine_waves * self.sine_amp
            uv = self._f02uv(f0)
            uv = F.interpolate(uv.transpose(2, 1), scale_factor=float(upp), mode="nearest").transpose(2, 1)
            noise_amp = uv * self.noise_std + (1 - uv) * self.sine_amp / 3
            noise = noise_amp * torch.randn_like(sine_waves)
            sine_waves = sine_waves * uv + noise
        return sine_waves, uv, noise


class SourceModuleHnNSF(torch.nn.Module):
    def __init__(self, sampling_rate, harmonic_num=0, sine_amp=0.1, add_noise_std=0.003,
                 voiced_threshold=0, is_half=False):
        super().__init__()
        self.is_half = is_half
        self.l_sin_gen = SineGen(sampling_rate, harmonic_num, sine_amp, add_noise_std, voiced_threshold)
        self.l_linear = torch.nn.Linear(harmonic_num + 1, 1)
        self.l_tanh = torch.nn.Tanh()

    def forward(self, x, upp):
        sine_wavs, _uv, _ = self.l_sin_gen(x, upp)
        if self.is_half:
            sine_wavs = sine_wavs.half()
        sine_merge = self.l_tanh(self.l_linear(sine_wavs.to(dtype=self.l_linear.weight.dtype)))
        return sine_merge, None, None


class GeneratorNSF(torch.nn.Module):
    # Vocoder HiFi-GAN con excitación NSF: convierte (features latentes + F0) en forma de onda.
    def __init__(self, initial_channel, resblock, resblock_kernel_sizes, resblock_dilation_sizes,
                 upsample_rates, upsample_initial_channel, upsample_kernel_sizes, gin_channels, sr,
                 is_half=False):
        super().__init__()
        self.num_kernels = len(resblock_kernel_sizes)
        self.num_upsamples = len(upsample_rates)
        self.upp = int(np.prod(upsample_rates))

        self.m_source = SourceModuleHnNSF(sampling_rate=sr, harmonic_num=0, is_half=is_half)
        self.noise_convs = nn.ModuleList()
        self.conv_pre = Conv1d(initial_channel, upsample_initial_channel, 7, 1, padding=3)
        resblock_cls = modules.ResBlock1 if resblock == "1" else modules.ResBlock2

        self.ups = nn.ModuleList()
        c_cur = upsample_initial_channel
        for i, (u, k) in enumerate(zip(upsample_rates, upsample_kernel_sizes)):
            c_cur = upsample_initial_channel // (2 ** (i + 1))
            self.ups.append(weight_norm(ConvTranspose1d(
                upsample_initial_channel // (2**i), c_cur, k, u, padding=(k - u) // 2,
            )))
            if i + 1 < len(upsample_rates):
                stride_f0 = int(np.prod(upsample_rates[i + 1:]))
                self.noise_convs.append(Conv1d(1, c_cur, kernel_size=stride_f0 * 2, stride=stride_f0,
                                               padding=stride_f0 // 2))
            else:
                self.noise_convs.append(Conv1d(1, c_cur, kernel_size=1))

        self.resblocks = nn.ModuleList()
        for i in range(len(self.ups)):
            ch = upsample_initial_channel // (2 ** (i + 1))
            for k, d in zip(resblock_kernel_sizes, resblock_dilation_sizes):
                self.resblocks.append(resblock_cls(ch, k, d))

        self.conv_post = Conv1d(c_cur, 1, 7, 1, padding=3, bias=False)
        self.ups.apply(commons.init_weights)

        if gin_channels != 0:
            self.cond = nn.Conv1d(gin_channels, upsample_initial_channel, 1)

    def forward(self, x, f0, g=None):
        har_source, _, _ = self.m_source(f0, self.upp)
        har_source = har_source.transpose(1, 2)
        x = self.conv_pre(x)
        if g is not None:
            x = x + self.cond(g)
        for i in range(self.num_upsamples):
            x = F.leaky_relu(x, modules.LRELU_SLOPE)
            x = self.ups[i](x)
            x = x + self.noise_convs[i](har_source)
            xs = None
            for j in range(self.num_kernels):
                layer = self.resblocks[i * self.num_kernels + j](x)
                xs = layer if xs is None else xs + layer
            x = xs / self.num_kernels
        x = F.leaky_relu(x)
        x = self.conv_post(x)
        return torch.tanh(x)

    def remove_weight_norm(self):
        for l in self.ups:
            weight_norm.remove(l) if hasattr(weight_norm, "remove") else None
        for l in self.resblocks:
            l.remove_weight_norm()


class Synthesizer(nn.Module):
    # Equivalente, solo para inferencia, de SynthesizerTrnMs768NSFsid (v2, 768-dim, con pitch).
    # Sin PosteriorEncoder (enc_q) ni discriminadores: no hacen falta fuera de entrenamiento.
    def __init__(self, spec_channels, segment_size, inter_channels, hidden_channels, filter_channels,
                 n_heads, n_layers, kernel_size, p_dropout, resblock, resblock_kernel_sizes,
                 resblock_dilation_sizes, upsample_rates, upsample_initial_channel, upsample_kernel_sizes,
                 spk_embed_dim, gin_channels, sr, is_half=False, **kwargs):
        super().__init__()
        if isinstance(sr, str):
            sr = {"32k": 32000, "40k": 40000, "48k": 48000}[sr]
        self.spk_embed_dim = spk_embed_dim
        self.gin_channels = gin_channels

        self.enc_p = TextEncoder768(inter_channels, hidden_channels, filter_channels, n_heads,
                                    n_layers, kernel_size, p_dropout)
        self.dec = GeneratorNSF(inter_channels, resblock, resblock_kernel_sizes, resblock_dilation_sizes,
                                upsample_rates, upsample_initial_channel, upsample_kernel_sizes,
                                gin_channels=gin_channels, sr=sr, is_half=is_half)
        self.flow = ResidualCouplingBlock(inter_channels, hidden_channels, 5, 1, 3,
                                          gin_channels=gin_channels)
        self.emb_g = nn.Embedding(spk_embed_dim, gin_channels)

    @torch.no_grad()
    def infer(self, phone, phone_lengths, pitch, nsff0, sid, rate: float | None = None):
        g = self.emb_g(sid).unsqueeze(-1)
        m_p, logs_p, x_mask = self.enc_p(phone, pitch, phone_lengths)
        z_p = (m_p + torch.exp(logs_p) * torch.randn_like(m_p) * 0.66666) * x_mask
        if rate is not None:
            head = int(z_p.shape[2] * (1.0 - rate))
            z_p = z_p[:, :, head:]
            x_mask = x_mask[:, :, head:]
            nsff0 = nsff0[:, head:]
        z = self.flow(z_p, x_mask, g=g, reverse=True)
        o = self.dec((z * x_mask)[:, :, :nsff0.shape[1]], nsff0, g=g)
        return o, x_mask, (z, z_p, m_p, logs_p)
