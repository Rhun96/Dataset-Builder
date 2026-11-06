"""Кольцевая диаграмма долей: трек + сегменты + подпись в центре."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

PALETTE = ["#4F8CFF", "#34C38F", "#F6B73C", "#EE6B6B", "#9B7EDE", "#38BDF8"]
TRACK_LIGHT = "#E8EDF3"
TRACK_DARK = "#3A3F45"


class DonutWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parts: list[tuple[str, float]] = []  # (color, frac)
        self._tips: list[str] = []
        self._center = ""
        self._dark = False
        self.setMinimumSize(120, 120)
        self.setMouseTracking(True)

    def set_parts(self, parts: list[tuple[str, float]], center: str = "",
                  dark: bool = False, tips: list[str] | None = None) -> None:
        self._parts = [(c, max(0.0, min(1.0, f))) for c, f in parts]
        self._tips = list(tips) if tips else []
        self._center = center
        self._dark = dark
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 24
        x = (self.width() - side) / 2
        y = (self.height() - side) / 2
        rect = (int(x), int(y), int(side), int(side))
        track = TRACK_DARK if self._dark else TRACK_LIGHT
        p.setPen(QPen(QColor(track), 16, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(*rect, 0, 360 * 16)
        start = 90 * 16
        for color, frac in self._parts:
            if frac <= 0:
                continue
            p.setPen(QPen(QColor(color), 16, Qt.SolidLine, Qt.RoundCap))
            span = -int(round(frac * 360 * 16))
            p.drawArc(*rect, start, span)
            start += span
        if self._center:
            p.setPen(QColor("#F2F2F2" if self._dark else "#1B1B1B"))
            p.drawText(self.rect(), Qt.AlignCenter, self._center)

    def _tip_at(self, x: float, y: float) -> str:
        import math
        side = min(self.width(), self.height()) - 24
        if side <= 0:
            return ""
        cx, cy = self.width() / 2, self.height() / 2
        dist = math.hypot(x - cx, y - cy)
        outer, inner = side / 2, side / 2 - 16
        if not (inner - 6 <= dist <= outer + 6):
            return ""
        theta = math.degrees(math.atan2(cy - y, x - cx)) % 360
        pos = ((90 - theta) % 360) / 360
        cum = 0.0
        for (_c, frac), tip in zip(self._parts, self._tips, strict=False):
            cum += frac
            if pos < cum:
                return tip
        if self._parts and self._tips:
            return self._tips[-1]
        return ""

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        tip = self._tip_at(event.position().x(), event.position().y())
        if tip:
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        QToolTip.hideText()
