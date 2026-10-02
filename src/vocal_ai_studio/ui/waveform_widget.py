from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from vocal_ai_studio.audio.io import AudioData
from vocal_ai_studio.audio.waveform import PeakCache
from vocal_ai_studio.ui import theme

LANE_LABELS = ("Canción", "Voz")
RULER_H = 20


class WaveformView(QWidget):
    seeked = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self._caches: dict[str, PeakCache | None] = {"song": None, "vocal": None}
        self._offsets: dict[str, float] = {"song": 0.0, "vocal": 0.0}
        self._samplerate = 44100
        self._duration = 0.0
        self._position = 0.0
        self._view_start = 0.0
        self._zoom = 1.0
        self._record_time: float | None = None

    # --- datos ---
    def set_track(self, lane: str, audio: AudioData | None, offset_sec: float = 0.0) -> None:
        if audio is None or audio.frames == 0:
            self._caches[lane] = None
        else:
            self._samplerate = audio.samplerate
            self._caches[lane] = PeakCache(audio.to_mono())
        self._offsets[lane] = offset_sec
        self._recompute_duration()
        self.update()

    def _recompute_duration(self) -> None:
        ends = [self._offsets[k] + (c.frames / self._samplerate) for k, c in self._caches.items() if c]
        self._duration = max(ends, default=0.0)
        self._clamp_view()

    def set_position(self, seconds: float) -> None:
        if abs(seconds - self._position) > 1e-4:
            self._position = seconds
            self._follow_playhead()
            self.update()

    def set_recording_time(self, seconds: float | None) -> None:
        self._record_time = seconds
        self.update()

    def set_zoom(self, zoom: float) -> None:
        center = self._view_start + self._visible_span() / 2
        self._zoom = max(1.0, min(200.0, zoom))
        self._view_start = center - self._visible_span() / 2
        self._clamp_view()
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def duration(self) -> float:
        return self._duration

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
        if self.width() <= 0:
            return 0.0
        return self._view_start + (x / self.width()) * self._visible_span()

    def _time_to_x(self, t: float) -> float:
        span = self._visible_span()
        return (t - self._view_start) / span * self.width() if span else 0.0

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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), QColor(theme.BG_PANEL))
        w, h = self.width(), self.height()
        lane_h = (h - RULER_H) / 2

        self._draw_ruler(p, w)
        for i, (lane, color) in enumerate((("song", theme.WAVE_SONG), ("vocal", theme.WAVE_VOCAL))):
            top = RULER_H + i * lane_h
            rect = QRectF(0, top, w, lane_h)
            if i:
                p.setPen(QPen(QColor(theme.BORDER), 1))
                p.drawLine(QPointF(0, top), QPointF(w, top))
            self._draw_lane(p, rect, lane, QColor(color))
            p.setPen(QPen(QColor(theme.TEXT_DIM)))
            f = QFont()
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(QRectF(8, top + 3, 120, 14), Qt.AlignmentFlag.AlignLeft, LANE_LABELS[i])

        if self._duration > 0:
            x = self._time_to_x(self._position)
            if -1 <= x <= w + 1:
                p.setPen(QPen(QColor(theme.PLAYHEAD), 2))
                p.drawLine(QPointF(x, RULER_H), QPointF(x, h))
        if self._record_time is not None:
            x = self._time_to_x(self._record_time)
            p.setPen(QPen(QColor(theme.REC), 2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, RULER_H), QPointF(x, h))
        if self._duration == 0:
            p.setPen(QPen(QColor(theme.TEXT_DIM)))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Importa una canción o graba tu voz para ver la onda aquí")
        p.end()

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
        t = (int(self._view_start / step)) * step
        while t <= self._view_start + span:
            x = self._time_to_x(t)
            p.setPen(QPen(QColor(theme.GRID), 1))
            p.drawLine(QPointF(x, RULER_H), QPointF(x, self.height()))
            p.setPen(QPen(QColor(theme.TEXT_DIM)))
            p.drawText(QRectF(x + 3, 2, 60, 14), Qt.AlignmentFlag.AlignLeft, _fmt_time(t))
            t += step

    def _draw_lane(self, p: QPainter, rect: QRectF, lane: str, color: QColor) -> None:
        mid = rect.center().y()
        p.setPen(QPen(QColor(theme.GRID), 1))
        p.drawLine(QPointF(0, mid), QPointF(rect.width(), mid))
        cache = self._caches[lane]
        if cache is None or self._duration <= 0:
            return
        span = self._visible_span()
        offset = self._offsets[lane]
        sr = self._samplerate
        start_f = int((self._view_start - offset) * sr)
        end_f = int((self._view_start + span - offset) * sr)
        bins = max(1, int(rect.width()))
        mins, maxs = cache.get(start_f, end_f, bins)
        if mins.size == 0:
            return
        # x del primer bin: el bin 0 cubre max(start_f, 0)
        first_f = max(start_f, 0)
        px_per_frame = rect.width() / max(1e-9, (end_f - start_f))
        x0 = (first_f - start_f) * px_per_frame
        width_px = (min(end_f, cache.frames) - first_f) * px_per_frame
        half = rect.height() / 2 - 4
        p.setPen(QPen(color, 1))
        n = len(mins)
        for i in range(n):
            x = x0 + width_px * i / n
            top = mid - float(maxs[i]) * half
            bottom = mid - float(mins[i]) * half
            if abs(bottom - top) < 1:
                bottom = top + 1
            p.drawLine(QPointF(x, top), QPointF(x, bottom))


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}" if seconds < 600 else f"{int(m)}:{int(s):02d}"


def format_time(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m):02d}:{s:04.1f}"


class LevelMeter(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setMinimumWidth(120)
        self._level = 0.0
        self._peak = 0.0

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))
        self._peak = self._level if self._level > self._peak else self._peak * 0.94
        self.update()

    def reset(self) -> None:
        self._level = self._peak = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(theme.BG_INPUT))
        db_pos = _level_to_pos(self._level)
        if db_pos > 0:
            color = theme.OK if self._level < 0.7 else (theme.WARN if self._level < 0.98 else theme.REC)
            p.fillRect(QRectF(1, 1, (r.width() - 2) * db_pos, r.height() - 2), QColor(color))
        peak_pos = _level_to_pos(self._peak)
        if peak_pos > 0:
            p.setPen(QPen(QColor(theme.TEXT), 1))
            x = 1 + (r.width() - 2) * peak_pos
            p.drawLine(QPointF(x, 1), QPointF(x, r.height() - 1))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawRect(r.adjusted(0, 0, -1, -1))
        p.end()


def _level_to_pos(level: float) -> float:
    # escala logarítmica: -60 dB..0 dB → 0..1
    if level <= 1e-5:
        return 0.0
    db = 20 * np.log10(level)
    return float(max(0.0, min(1.0, (db + 60) / 60)))
