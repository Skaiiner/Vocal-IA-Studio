from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap

from vocal_ai_studio.ui import theme

_SIZE = 20


def _canvas() -> tuple[QPixmap, QPainter]:
    pix = QPixmap(_SIZE, _SIZE)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(theme.TEXT_DIM)
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    return pix, p


def _finish(pix: QPixmap, p: QPainter) -> QIcon:
    p.end()
    return QIcon(pix)


def _song() -> QIcon:
    pix, p = _canvas()
    p.drawEllipse(QPointF(7.5, 15.0), 2.6, 2.6)
    p.drawLine(QPointF(10.0, 15.0), QPointF(10.0, 4.5))
    p.drawLine(QPointF(10.0, 4.5), QPointF(15.5, 6.0))
    p.drawLine(QPointF(15.5, 6.0), QPointF(15.5, 10.0))
    return _finish(pix, p)


def _voice() -> QIcon:
    pix, p = _canvas()
    bars = [(4.5, 7), (8.0, 12), (11.5, 5), (15.0, 9)]
    for x, h in bars:
        p.drawLine(QPointF(x, 10 - h / 2 + 1), QPointF(x, 10 + h / 2 + 1))
    return _finish(pix, p)


def _pitch() -> QIcon:
    pix, p = _canvas()
    path = QPainterPath()
    path.moveTo(3, 14)
    path.cubicTo(7, 14, 7, 5, 10, 5)
    path.cubicTo(13, 5, 13, 15, 17, 15)
    p.drawPath(path)
    return _finish(pix, p)


def _voice_lab() -> QIcon:
    pix, p = _canvas()
    for x, dot_y in ((5.5, 7), (10.0, 13), (14.5, 9)):
        p.drawLine(QPointF(x, 3.5), QPointF(x, 16.5))
        p.setBrush(theme.ACCENT)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(x, dot_y), 2.0, 2.0)
        pen = QPen(theme.TEXT_DIM)
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
    return _finish(pix, p)


def _ai_coach() -> QIcon:
    pix, p = _canvas()
    path = QPainterPath()
    path.moveTo(10, 3)
    path.lineTo(12, 8)
    path.lineTo(17, 10)
    path.lineTo(12, 12)
    path.lineTo(10, 17)
    path.lineTo(8, 12)
    path.lineTo(3, 10)
    path.lineTo(8, 8)
    path.closeSubpath()
    p.setBrush(theme.ACCENT)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(path)
    return _finish(pix, p)


def _separation() -> QIcon:
    pix, p = _canvas()
    p.drawLine(QPointF(3.5, 6.5), QPointF(16.5, 6.5))
    pen = p.pen()
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawLine(QPointF(3.5, 13.5), QPointF(16.5, 13.5))
    return _finish(pix, p)


def _voice_conversion() -> QIcon:
    pix, p = _canvas()
    p.drawLine(QPointF(4, 7), QPointF(14, 7))
    p.drawLine(QPointF(11, 4), QPointF(14, 7))
    p.drawLine(QPointF(11, 10), QPointF(14, 7))
    p.drawLine(QPointF(16, 13), QPointF(6, 13))
    p.drawLine(QPointF(9, 10), QPointF(6, 13))
    p.drawLine(QPointF(9, 16), QPointF(6, 13))
    return _finish(pix, p)


def _live_voice() -> QIcon:
    pix, p = _canvas()
    p.setBrush(theme.REC)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(10, 10), 2.4, 2.4)
    pen = QPen(theme.TEXT_DIM)
    pen.setWidthF(1.4)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(4.5, 4.5, 11, 11), 0, 360 * 16)
    p.drawArc(QRectF(1.5, 1.5, 17, 17), 30 * 16, 120 * 16)
    p.drawArc(QRectF(1.5, 1.5, 17, 17), 210 * 16, 120 * 16)
    return _finish(pix, p)


def _settings() -> QIcon:
    import math

    pix, p = _canvas()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(10, 10), 3.0, 3.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.TEXT_DIM)
    for i in range(6):
        angle = math.radians(i * 60)
        cx, cy = 10 + 6.4 * math.cos(angle), 10 + 6.4 * math.sin(angle)
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(angle))
        p.drawRoundedRect(QRectF(-1.1, -1.9, 2.2, 3.8), 0.8, 0.8)
        p.restore()
    return _finish(pix, p)


_BUILDERS = {
    "song": _song,
    "voice": _voice,
    "pitch": _pitch,
    "voice_lab": _voice_lab,
    "ai_coach": _ai_coach,
    "separation": _separation,
    "voice_conversion": _voice_conversion,
    "live_voice": _live_voice,
    "settings": _settings,
}


def tab_icon(kind: str) -> QIcon:
    builder = _BUILDERS.get(kind)
    return builder() if builder else QIcon()
