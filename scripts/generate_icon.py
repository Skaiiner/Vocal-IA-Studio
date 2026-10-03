"""Regenera src/vocal_ai_studio/assets/icon.ico e icon.png.

Uso:  .\\.venv\\Scripts\\python.exe scripts\\generate_icon.py
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

ACCENT = QColor("#5b8cff")
ACCENT_HOVER = QColor("#7aa2ff")
REC = QColor("#ff5160")

ASSETS_DIR = Path(__file__).resolve().parent.parent / "src" / "vocal_ai_studio" / "assets"


def draw_icon(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    margin = size * 0.06
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    radius = size * 0.22
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#1b1f28"))
    grad.setColorAt(1.0, QColor("#0e1016"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawPath(path)

    p.setPen(QColor(47, 53, 65, 220))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    # barras tipo ecualizador, centradas
    n = 5
    bar_w = size * 0.085
    gap = size * 0.05
    total_w = n * bar_w + (n - 1) * gap
    start_x = (size - total_w) / 2
    heights = [0.34, 0.58, 0.82, 0.58, 0.34]
    colors = [ACCENT, ACCENT_HOVER, REC, ACCENT_HOVER, ACCENT]
    base_y = size * 0.78
    for i, (h_frac, col) in enumerate(zip(heights, colors)):
        bar_h = size * h_frac * 0.6
        x = start_x + i * (bar_w + gap)
        bar_rect = QRectF(x, base_y - bar_h, bar_w, bar_h)
        bp = QPainterPath()
        bp.addRoundedRect(bar_rect, bar_w * 0.4, bar_w * 0.4)
        p.setBrush(col)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(bp)

    p.end()
    return img


def _png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: Path, sizes: list[int]) -> None:
    images = [_png_bytes(draw_icon(s)) for s in sizes]
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(sizes)))
        offset = 6 + 16 * len(sizes)
        for s, data in zip(sizes, images):
            side = 0 if s >= 256 else s  # 0 significa 256 en el formato ICO
            f.write(struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset))
            offset += len(data)
        for data in images:
            f.write(data)


def main() -> None:
    app = QApplication([])
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    write_ico(ASSETS_DIR / "icon.ico", [16, 32, 48, 64, 128, 256])
    draw_icon(256).save(str(ASSETS_DIR / "icon.png"), "PNG")
    print(f"Icono regenerado en {ASSETS_DIR}")


if __name__ == "__main__":
    main()
