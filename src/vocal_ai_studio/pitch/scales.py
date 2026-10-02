from __future__ import annotations

SCALES: dict[str, list[int]] = {
    "Cromática": list(range(12)),
    "Mayor": [0, 2, 4, 5, 7, 9, 11],
    "Menor natural": [0, 2, 3, 5, 7, 8, 10],
    "Menor armónica": [0, 2, 3, 5, 7, 8, 11],
    "Pentatónica mayor": [0, 2, 4, 7, 9],
    "Pentatónica menor": [0, 3, 5, 7, 10],
}

KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def nearest_scale_midi(midi: float, key: str, scale_name: str) -> int:
    root = KEYS.index(key) if key in KEYS else 0
    intervals = SCALES.get(scale_name, SCALES["Cromática"])
    allowed = {(root + i) % 12 for i in intervals}
    base = int(round(midi))
    best, best_dist = base, 1e9
    for candidate in range(base - 12, base + 13):
        if candidate % 12 in allowed:
            dist = abs(candidate - midi)
            if dist < best_dist:
                best_dist, best = dist, candidate
    return best
