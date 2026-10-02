from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.pitch.notes import NOTE_NAMES, hz_to_midi, midi_to_note_name
from vocal_ai_studio.ui import theme

RULER_H = 20
_WHITE_KEYS = {0, 2, 4, 5, 7, 9, 11}  # C D E F G A B


def _color_for_cents(cents: float) -> QColor:
    dev = abs(cents)
    if dev <= 15:
        return QColor(theme.OK)
    if dev <= 35:
        return QColor(theme.WARN)
    return QColor(theme.REC)


class PitchView(QWidget):
    seeked = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self._track: PitchTrack | None = None
        self._duration = 0.0
        self._position = 0.0
        self._view_start = 0.0
        self._zoom = 1.0
        self._midi_lo = 57.0   # A3, rango por defecto cuando no hay datos
        self._midi_hi = 72.0   # C5
        self._live_time: float | None = None
        self._live_freq: float | None = None

    # --- datos ---
    def set_track(self, track: PitchTrack | None, duration: float = 0.0) -> None:
        self._track = track
        self._duration = duration
        if track is not None and len(track.f0):
            voiced = track.f0[~np.isnan(track.f0)]
            if voiced.size:
                midi = hz_to_midi(voiced)
                self._midi_lo = float(np.floor(np.nanmin(midi))) - 2
                self._midi_hi = float(np.ceil(np.nanmax(midi))) + 2
        self._clamp_view()
        self.update()

    def set_position(self, seconds: float) -> None:
        if abs(seconds - self._position) > 1e-4:
            self._position = seconds
            self._follow_playhead()
            self.update()

    def set_live_pitch(self, time: float | None, freq: float | None) -> None:
        self._live_time = time
        self._live_freq = freq if freq and not np.isnan(freq) else None
        if time is not None:
            self._duration = max(self._duration, time + 0.5)
            self._follow_playhead_to(time)
        self.update()

    def _follow_playhead_to(self, t: float) -> None:
        span = self._visible_span()
        if t < self._view_start or t > self._view_start + span:
            self._view_start = max(0.0, t - span * 0.85)
            self._clamp_view()

    def set_zoom(self, zoom: float) -> None:
        center = self._view_start + self._visible_span() / 2
        self._zoom = max(1.0, min(200.0, zoom))
        self._view_start = center - self._visible_span() / 2
        self._clamp_view()
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    def _visible_span(self) -> float:
        return (self._duration / self._zoom) if self._duration else 1.0

    def _clamp_view(self) -> None:
        self._view_start = max(0.0, min(self._view_start, max(0.0, self._duration - self._visible_span())))

    def _follow_playhead(self) -> None:
        span = self._visible_span()
        if self._position < self._view_start or self._position > self._view_start + span:
            self._view_start = max(0.0, self._position - span * 0.25)
            self._clamp_view()

    # --- interacción ---
    def _x_to_time(self, x: float) -> float:
        return self._view_start + (x / self.width()) * self._visible_span() if self.width() else 0.0

    def _time_to_x(self, t: float) -> float:
        span = self._visible_span()
        return (t - self._view_start) / span * self.width() if span else 0.0

    def _midi_to_y(self, midi: float) -> float:
        h = self.height() - RULER_H
        span = max(1e-6, self._midi_hi - self._midi_lo)
        frac = (midi - self._midi_lo) / span
        return RULER_H + h * (1.0 - frac)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._duration > 0:
            self.seeked.emit(max(0.0, min(self._duration, self._x_to_time(event.position().x()))))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._duration > 0:
            self.seeked.emit(max(0.0, min(self._duration, self._x_to_time(event.position().x()))))
        super().mouseMoveEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self._zoom * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2))
        else:
            self._view_start -= event.angleDelta().y() / 120 * self._visible_span() * 0.1
            self._clamp_view()
            self.update()
        event.accept()

    # --- dibujo ---
    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(theme.BG_PANEL))
        w, h = self.width(), self.height()

        self._draw_note_grid(p, w, h)
        self._draw_ruler(p, w)
        if self._track is not None and self._duration > 0:
            self._draw_curve(p, w, h)
            x = self._time_to_x(self._position)
            if -1 <= x <= w + 1:
                p.setPen(QPen(QColor(theme.PLAYHEAD), 2))
                p.drawLine(QPointF(x, RULER_H), QPointF(x, h))
        elif self._live_time is None:
            p.setPen(QPen(QColor(theme.TEXT_DIM)))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Pulsa Analizar para ver aquí la curva de afinación")
        self._draw_live_marker(p, w)
        p.end()

    def _draw_live_marker(self, p: QPainter, w: int) -> None:
        if self._live_time is None or self._live_freq is None or self.width() <= 0:
            return
        x = self._time_to_x(self._live_time)
        if x < -10 or x > w + 10:
            return
        midi = hz_to_midi(self._live_freq)
        y = self._midi_to_y(midi)
        cents = (midi - round(midi)) * 100.0
        color = QColor(theme.ACCENT)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(color)
        p.drawEllipse(QPointF(x, y), 6, 6)
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        label = f"{midi_to_note_name(round(midi))}  {cents:+.0f}¢"
        p.setPen(QPen(QColor(theme.TEXT)))
        p.drawText(QRectF(x + 10, y - 20, 120, 18), Qt.AlignmentFlag.AlignLeft, label)

    def _draw_ruler(self, p: QPainter, w: int) -> None:
        p.fillRect(QRectF(0, 0, w, RULER_H), QColor(theme.BG_INPUT))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawLine(QPointF(0, RULER_H), QPointF(w, RULER_H))
        if self._duration <= 0:
            return
        span = self._visible_span()
        step = next((s for s in (0.1, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300) if span / s <= 12), 600)
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        t = int(self._view_start / step) * step
        while t <= self._view_start + span:
            x = self._time_to_x(t)
            p.setPen(QPen(QColor(theme.TEXT_DIM)))
            m, s = divmod(max(0.0, t), 60)
            p.drawText(QRectF(x + 3, 2, 60, 14), Qt.AlignmentFlag.AlignLeft, f"{int(m)}:{s:04.1f}")
            t += step

    def _draw_note_grid(self, p: QPainter, w: int, h: int) -> None:
        lo, hi = int(np.floor(self._midi_lo)), int(np.ceil(self._midi_hi))
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        for midi in range(lo, hi + 1):
            y = self._midi_to_y(midi)
            is_c = midi % 12 == 0
            is_white = (midi % 12) in _WHITE_KEYS
            p.setPen(QPen(QColor(theme.GRID), 1.3 if is_c else 0.7))
            p.drawLine(QPointF(0, y), QPointF(w, y))
            if is_white:
                p.setPen(QPen(QColor(theme.TEXT) if is_c else QColor(theme.TEXT_DIM)))
                p.drawText(QRectF(2, y - 12, 44, 12), Qt.AlignmentFlag.AlignLeft, midi_to_note_name(midi))

    def _draw_curve(self, p: QPainter, w: int, h: int) -> None:
        track = self._track
        span = self._visible_span()
        start_t, end_t = self._view_start, self._view_start + span
        times, f0 = track.times, track.f0
        if len(times) == 0:
            return
        lo = int(np.searchsorted(times, start_t) - 1)
        hi = int(np.searchsorted(times, end_t) + 1)
        lo, hi = max(0, lo), min(len(times), hi)

        pen = QPen()
        pen.setWidth(2)
        last_point: QPointF | None = None
        for i in range(lo, hi):
            freq = f0[i]
            if np.isnan(freq):
                last_point = None
                continue
            midi = hz_to_midi(freq)
            cents = (midi - round(midi)) * 100.0
            x, y = self._time_to_x(times[i]), self._midi_to_y(midi)
            point = QPointF(x, y)
            pen.setColor(_color_for_cents(cents))
            p.setPen(pen)
            if last_point is not None:
                p.drawLine(last_point, point)
            else:
                p.drawPoint(point)
            last_point = point


def legend_text() -> str:
    return "Verde: afinado (±15 cents) · Amarillo: ligera desviación · Rojo: desviación notable"
