from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.core.errors import AppError, explain_exception


def panel(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(8)
    if title:
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
    return frame, layout


def hint(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(wrap)
    return label


class GainSlider(QWidget):
    muted_changed = Signal(bool)

    def __init__(self, label: str, value: float = 1.0, parent: QWidget | None = None,
                 with_mute: bool = False):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        name = QLabel(label)
        name.setMinimumWidth(68)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 150)
        self.slider.setValue(int(value * 100))
        self.value_label = QLabel(f"{int(value * 100)}%")
        self.value_label.setMinimumWidth(42)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider.valueChanged.connect(lambda v: self.value_label.setText(f"{v}%"))
        row.addWidget(name)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)
        self.btn_mute: QPushButton | None = None
        if with_mute:
            self.btn_mute = QPushButton("Escuchar")
            self.btn_mute.setCheckable(True)
            self.btn_mute.setFixedWidth(90)
            self.btn_mute.toggled.connect(self._on_mute_toggled)
            row.addWidget(self.btn_mute)

    def gain(self) -> float:
        return self.slider.value() / 100.0

    @property
    def muted(self) -> bool:
        return self.btn_mute.isChecked() if self.btn_mute else False

    def set_muted(self, muted: bool) -> None:
        if self.btn_mute is None:
            return
        self.btn_mute.blockSignals(True)
        self.btn_mute.setChecked(muted)
        self.btn_mute.setText("Silenciado" if muted else "Escuchar")
        self.btn_mute.blockSignals(False)

    def _on_mute_toggled(self, checked: bool) -> None:
        self.btn_mute.setText("Silenciado" if checked else "Escuchar")
        self.muted_changed.emit(checked)


def placeholder_tab(title: str, description: str, bullets: list[str]) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    heading = QLabel(title)
    heading.setObjectName("Title")
    layout.addWidget(heading)
    layout.addWidget(hint(description))
    layout.addSpacing(10)
    items = QLabel("\n".join(f"•  {b}" for b in bullets))
    items.setObjectName("Hint")
    layout.addWidget(items)
    layout.addStretch(1)
    return page


def show_error(parent: QWidget | None, exc: BaseException, context: str = "") -> None:
    err: AppError = exc if isinstance(exc, AppError) else explain_exception(exc, context)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Vocal AI Studio")
    box.setText(err.what)
    details = []
    if err.why:
        details.append(f"Posible causa: {err.why}")
    if err.fix:
        details.append(f"Cómo solucionarlo: {err.fix}")
    box.setInformativeText("\n\n".join(details))
    box.exec()
