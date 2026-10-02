from __future__ import annotations

import numpy as np


class PeakCache:
    def __init__(self, mono: np.ndarray, base_block: int = 64):
        x = np.asarray(mono, dtype=np.float32)
        self.frames = int(x.shape[0])
        self.base = base_block
        mins, maxs = self._reduce_blocks(x, base_block)
        self.levels: list[tuple[np.ndarray, np.ndarray]] = [(mins, maxs)]
        while len(self.levels[-1][0]) > 8:
            mn, mx = self.levels[-1]
            if len(mn) % 2:
                mn = np.append(mn, mn[-1])
                mx = np.append(mx, mx[-1])
            self.levels.append((mn.reshape(-1, 2).min(axis=1), mx.reshape(-1, 2).max(axis=1)))

    @staticmethod
    def _reduce_blocks(x: np.ndarray, block: int) -> tuple[np.ndarray, np.ndarray]:
        n = x.shape[0]
        if n == 0:
            return np.zeros(0, np.float32), np.zeros(0, np.float32)
        full = n // block
        mins = list(x[: full * block].reshape(full, block).min(axis=1)) if full else []
        maxs = list(x[: full * block].reshape(full, block).max(axis=1)) if full else []
        if n % block:
            tail = x[full * block:]
            mins.append(tail.min())
            maxs.append(tail.max())
        return np.asarray(mins, np.float32), np.asarray(maxs, np.float32)

    def get(self, start: int, end: int, bins: int) -> tuple[np.ndarray, np.ndarray]:
        start = max(0, int(start))
        end = min(self.frames, int(end))
        if end <= start or bins <= 0 or not self.levels[0][0].size:
            return np.zeros(0, np.float32), np.zeros(0, np.float32)
        target = (end - start) / bins
        level = 0
        while level + 1 < len(self.levels) and self.base * (2 ** (level + 1)) <= target:
            level += 1
        block = self.base * (2 ** level)
        mn, mx = self.levels[level]
        i0 = start // block
        i1 = min(len(mn), -(-end // block))
        mn, mx = mn[i0:i1], mx[i0:i1]
        if len(mn) <= bins:
            return mn, mx
        idx = np.linspace(0, len(mn), bins, endpoint=False).astype(np.intp)
        return np.minimum.reduceat(mn, idx), np.maximum.reduceat(mx, idx)
