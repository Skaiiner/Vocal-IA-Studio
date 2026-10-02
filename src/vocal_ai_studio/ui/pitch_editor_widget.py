from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QWidget

from vocal_ai_studio.pitch.correction import NoteOverride
from vocal_ai_studio.pitch.notes import hz_to_midi
from vocal_ai_studio.ui import theme
from vocal_ai_studio.ui.pitch_view import PitchView, _color_for_cents

_DRAG_NONE, _DRAG_NOTE, _DRAG_SEEK = 0, 1, 2


class PitchEditorWidget(PitchView):
    changed = Signal()            # los overrides cambiaron (transportar, dividir, unir, excluir)
    selection_changed = Signal(object)   # NoteOverride seleccionado, o None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._overrides: list[NoteOverride] = []
        self._target_f0: np.ndarray | None = None
        self._selected: int | None = None
        self._drag_mode = _DRAG_NONE
        self._drag_start_y = 0.0
        self._drag_start_offset = 0

    # --- datos ---
    def set_overrides(self, overrides: list[NoteOverride]) -> None:
        self._overrides = overrides
        if self._selected is not None and self._selected >= len(overrides):
            self._selected = None
        self.update()

    def overrides(self) -> list[NoteOverride]:
        return self._overrides

    def set_target(self, target_f0: np.ndarray | None) -> None:
        self._target_f0 = target_f0
        self.update()

    def selected_override(self) -> NoteOverride | None:
        if self._selected is not None and 0 <= self._selected < len(self._overrides):
            return self._overrides[self._selected]
        return None

    # --- edición ---
    def transpose_selected(self, delta_semitones: int) -> None:
        ov = self.selected_override()
        if ov is not None:
            ov.semitone_offset += delta_semitones
            self.changed.emit()
            self.update()

    def toggle_bypass_selected(self) -> None:
        ov = self.selected_override()
        if ov is not None:
            ov.bypass = not ov.bypass
            self.changed.emit()
            self.update()

    def reset_selected(self) -> None:
        ov = self.selected_override()
        if ov is not None:
            ov.semitone_offset, ov.bypass = 0, False
            self.changed.emit()
            self.update()

    def split_selected_at(self, time: float) -> None:
        if self._selected is None:
            return
        ov = self._overrides[self._selected]
        if not (ov.start < time < ov.end):
            return
        second = NoteOverride(time, ov.end, ov.semitone_offset, ov.bypass)
        ov.end = time
        self._overrides.insert(self._selected + 1, second)
        self.changed.emit()
        self.update()

    def merge_selected_with_next(self) -> None:
        if self._selected is None or self._selected + 1 >= len(self._overrides):
            return
        current, nxt = self._overrides[self._selected], self._overrides[self._selected + 1]
        if abs(nxt.start - current.end) > 0.5:  # no están razonablemente adyacentes
            return
        current.end = nxt.end
        del self._overrides[self._selected + 1]
        self.changed.emit()
        self.update()

    def _select(self, index: int | None) -> None:
        self._selected = index
        self.selection_changed.emit(self.selected_override())
        self.update()

    def _note_at(self, time: float, midi: float) -> int | None:
        for i, ov in enumerate(self._overrides):
            if ov.start <= time < ov.end:
                center = self._override_midi(ov)
                if center is not None and abs(midi - center) <= 0.5:
                    return i
        return None

    def _override_midi(self, ov: NoteOverride) -> float | None:
        if self._track is None or self._target_f0 is None:
            return None
        mask = (self._track.times >= ov.start) & (self._track.times < ov.end) & ~np.isnan(self._target_f0)
        if not mask.any():
            return None
        return float(np.nanmean(hz_to_midi(self._target_f0[mask])))

    # --- interacción ---
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._duration <= 0:
            super().mousePressEvent(event)
            return
        pos = event.position()
        time = self._x_to_time(pos.x())
        midi = self._y_to_midi(pos.y())
        index = self._note_at(time, midi)
        if index is not None:
            self._select(index)
            self._drag_mode = _DRAG_NOTE
            self._drag_start_y = pos.y()
            self._drag_start_offset = self._overrides[index].semitone_offset
        else:
            self._drag_mode = _DRAG_SEEK
            self.seeked.emit(max(0.0, min(self._duration, time)))

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode == _DRAG_NOTE and self._selected is not None:
            px_per_semitone = (self.height() - 20) / max(1e-6, self._midi_hi - self._midi_lo)
            delta = round((self._drag_start_y - event.position().y()) / max(1.0, px_per_semitone))
            ov = self._overrides[self._selected]
            new_offset = self._drag_start_offset + int(delta)
            if new_offset != ov.semitone_offset:
                ov.semitone_offset = new_offset
                self.changed.emit()
                self.update()
        elif self._drag_mode == _DRAG_SEEK and self._duration > 0:
            self.seeked.emit(max(0.0, min(self._duration, self._x_to_time(event.position().x()))))
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_mode = _DRAG_NONE
        super().mouseReleaseEvent(event)

    def _y_to_midi(self, y: float) -> float:
        h = self.height() - 20
        span = max(1e-6, self._midi_hi - self._midi_lo)
        frac = 1.0 - (y - 20) / h if h else 0.0
        return self._midi_lo + frac * span

    # --- dibujo ---
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._track is None or self._duration <= 0:
            return
        from PySide6.QtGui import QPainter

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_target_curve(p)
        self._draw_notes(p)
        p.end()

    def _draw_target_curve(self, p) -> None:
        if self._target_f0 is None:
            return
        times = self._track.times
        span = self._visible_span()
        lo = max(0, int(np.searchsorted(times, self._view_start) - 1))
        hi = min(len(times), int(np.searchsorted(times, self._view_start + span) + 1))
        pen = QPen()
        pen.setWidth(3)
        last: QPointF | None = None
        for i in range(lo, hi):
            freq = self._target_f0[i]
            if np.isnan(freq):
                last = None
                continue
            midi = hz_to_midi(freq)
            cents = (midi - round(midi)) * 100.0
            point = QPointF(self._time_to_x(times[i]), self._midi_to_y(midi))
            pen.setColor(_color_for_cents(cents))
            p.setPen(pen)
            if last is not None:
                p.drawLine(last, point)
            last = point

    def _draw_notes(self, p) -> None:
        for i, ov in enumerate(self._overrides):
            midi = self._override_midi(ov)
            if midi is None:
                continue
            x0, x1 = self._time_to_x(ov.start), self._time_to_x(ov.end)
            if x1 < 0 or x0 > self.width():
                continue
            y = self._midi_to_y(midi)
            rect = QRectF(x0, y - 7, max(2.0, x1 - x0), 14)
            selected = i == self._selected
            color = QColor(theme.TEXT_DIM) if ov.bypass else QColor(theme.ACCENT)
            p.setPen(QPen(QColor(theme.PLAYHEAD) if selected else color, 2 if selected else 1))
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 70 if selected else 35))
            p.drawRoundedRect(rect, 4, 4)
