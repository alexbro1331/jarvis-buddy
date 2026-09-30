"""The funny on-screen character: a draggable, always-on-top, click-through-transparent blob."""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
    QPen, QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QWidget

IDLE, LISTENING, THINKING, SPEAKING = "idle", "listening", "thinking", "speaking"
DRAG_THRESHOLD = 5  # pixels; below this a press+release counts as a tap


class Character(QWidget):
    tapped = pyqtSignal()
    moved = pyqtSignal(int, int)
    context_requested = pyqtSignal(object)  # global QPoint

    def __init__(self, size: int = 150):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # no taskbar entry
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFixedSize(size, size)
        self.setToolTip("Tap karo aur bolo!  (Drag = move, Right-click = menu)")

        self.state = IDLE
        self._t = 0.0
        self._blink = 0.0  # 0 open .. 1 closed
        self._next_blink = 2.0
        self._press_global: QPointF | None = None
        self._press_offset: QPointF | None = None
        self._dragging = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ------------------------------------------------------------------ state
    def set_state(self, state: str) -> None:
        self.state = state
        self.update()

    # -------------------------------------------------------------- animation
    def _tick(self) -> None:
        if not self.isVisible():
            return
        self._t += 0.033
        self._next_blink -= 0.033
        if self._next_blink <= 0:
            self._blink = 1.0
            self._next_blink = random.uniform(2.0, 5.0)
        if self._blink > 0:
            self._blink = max(0.0, self._blink - 0.15)
        self.update()

    # ----------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:  # noqa: N802
        s = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._t

        # bounce / squash-and-stretch; bigger when listening or speaking
        amp = {IDLE: 0.02, LISTENING: 0.06, THINKING: 0.03, SPEAKING: 0.05}[self.state]
        speed = {IDLE: 2.0, LISTENING: 6.0, THINKING: 3.0, SPEAKING: 8.0}[self.state]
        wob = math.sin(t * speed)
        sx, sy = 1 + amp * wob, 1 - amp * wob
        bounce = -abs(math.sin(t * speed * 0.5)) * s * amp * 1.5

        cx, cy = s / 2, s * 0.60 + bounce
        bw, bh = s * 0.34 * sx, s * 0.30 * sy

        # listening ring
        if self.state == LISTENING:
            r = s * 0.34 + (t * 60 % 28)
            ring = QColor(0, 220, 255, int(160 * (1 - (t * 60 % 28) / 28)))
            p.setPen(QPen(ring, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r * 0.9)

        # shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(QPointF(s / 2, s * 0.93), s * 0.26 * (1 + bounce / s), s * 0.04)

        # antenna
        ant_top = QPointF(cx + math.sin(t * 3) * 4, cy - bh - s * 0.12)
        p.setPen(QPen(QColor(90, 70, 140), 3))
        p.drawLine(QPointF(cx, cy - bh * 0.95), ant_top)
        glow = {IDLE: QColor(255, 200, 60), LISTENING: QColor(0, 230, 255),
                THINKING: QColor(255, 120, 200), SPEAKING: QColor(120, 255, 120)}[self.state]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        pulse = 1 + 0.25 * math.sin(t * 8)
        p.drawEllipse(ant_top, s * 0.045 * pulse, s * 0.045 * pulse)

        # body
        body = QRectF(cx - bw, cy - bh, bw * 2, bh * 2)
        grad = QLinearGradient(body.topLeft(), body.bottomRight())
        grad.setColorAt(0, QColor(130, 110, 255))
        grad.setColorAt(1, QColor(70, 190, 230))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(50, 40, 110), 3))
        p.drawEllipse(body)

        # belly shine
        shine = QRadialGradient(QPointF(cx - bw * 0.4, cy - bh * 0.5), bw * 0.6)
        shine.setColorAt(0, QColor(255, 255, 255, 110))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(shine))
        p.drawEllipse(body)

        # eyes (pupils follow the mouse cursor)
        eye_r = s * 0.085
        eye_y = cy - bh * 0.25
        cursor = self.mapFromGlobal(QCursor.pos())
        for ex in (cx - bw * 0.38, cx + bw * 0.38):
            self._eye(p, QPointF(ex, eye_y), eye_r, cursor)

        # cheeks
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 120, 150, 120))
        for ex in (cx - bw * 0.62, cx + bw * 0.62):
            p.drawEllipse(QPointF(ex, cy + bh * 0.15), s * 0.05, s * 0.03)

        self._mouth(p, cx, cy + bh * 0.4, s)

        # little feet
        p.setBrush(QColor(50, 40, 110))
        for fx in (cx - bw * 0.4, cx + bw * 0.4):
            p.drawEllipse(QPointF(fx, cy + bh + 2), s * 0.07, s * 0.035)
        p.end()

    def _eye(self, p: QPainter, c: QPointF, r: float, cursor) -> None:
        p.setPen(QPen(QColor(50, 40, 110), 2))
        p.setBrush(QColor(255, 255, 255))
        closed = self._blink
        p.drawEllipse(c, r, r * (1 - 0.92 * closed))
        if closed > 0.6:
            return
        # pupil direction
        if self.state == THINKING:
            a = self._t * 5
            dx, dy = math.cos(a), math.sin(a)
            dist = r * 0.45
        else:
            vx, vy = cursor.x() - c.x(), cursor.y() - c.y()
            d = math.hypot(vx, vy) or 1
            dx, dy = vx / d, vy / d
            dist = min(r * 0.5, d / 8)
        pupil = QPointF(c.x() + dx * dist, c.y() + dy * dist)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(25, 20, 60))
        p.drawEllipse(pupil, r * 0.5, r * 0.5)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(pupil.x() - r * 0.15, pupil.y() - r * 0.15), r * 0.14, r * 0.14)

    def _mouth(self, p: QPainter, x: float, y: float, s: float) -> None:
        dark = QColor(60, 20, 60)
        if self.state == SPEAKING:
            open_ = 0.4 + 0.6 * abs(math.sin(self._t * 14))
            p.setPen(QPen(dark, 2))
            p.setBrush(QColor(200, 60, 90))
            p.drawEllipse(QPointF(x, y), s * 0.09, s * 0.07 * open_)
        elif self.state == LISTENING:
            p.setPen(QPen(dark, 2))
            p.setBrush(QColor(200, 60, 90))
            p.drawEllipse(QPointF(x, y), s * 0.04, s * 0.05)  # "o"
        elif self.state == THINKING:
            p.setPen(QPen(dark, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            wave = QPainterPath(QPointF(x - s * 0.08, y))
            for i in range(1, 5):
                wave.lineTo(x - s * 0.08 + i * s * 0.04, y + (s * 0.015 if i % 2 else -s * 0.015))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(wave)
        else:
            p.setPen(QPen(dark, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(QPointF(x - s * 0.1, y - s * 0.02))
            path.quadTo(QPointF(x, y + s * 0.1), QPointF(x + s * 0.1, y - s * 0.02))
            p.drawPath(path)
            # cheeky tongue
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 110, 140))
            p.drawEllipse(QPointF(x + s * 0.04, y + s * 0.045), s * 0.028, s * 0.03)

    # ------------------------------------------------------------ interaction
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_global = e.globalPosition()
            self._press_offset = e.globalPosition() - QPointF(self.pos())
            self._dragging = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._press_global is None:
            return
        delta = e.globalPosition() - self._press_global
        if not self._dragging and math.hypot(delta.x(), delta.y()) > DRAG_THRESHOLD:
            self._dragging = True
        if self._dragging:
            target = e.globalPosition() - self._press_offset
            self.move(int(target.x()), int(target.y()))

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            return
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._dragging:
            self._clamp_to_screen()
            self.moved.emit(self.x(), self.y())
        else:
            self.tapped.emit()
        self._press_global = None
        self._dragging = False

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        self.context_requested.emit(e.globalPos())

    def _clamp_to_screen(self) -> None:
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        g = screen.availableGeometry()
        x = min(max(self.x(), g.left() - self.width() // 3), g.right() - self.width() * 2 // 3)
        y = min(max(self.y(), g.top()), g.bottom() - self.height() // 2)
        self.move(x, y)


class Bubble(QWidget):
    """Speech bubble shown next to the character. Ignores the mouse entirely."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._font = QFont("Segoe UI", 11)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_text(self, text: str, anchor: Character, seconds: float = 5.0) -> None:
        self._text = text
        max_w = 280
        fm = QFontMetrics(self._font)
        rect = fm.boundingRect(0, 0, max_w, 1000, int(Qt.TextFlag.TextWordWrap), text)
        self.resize(rect.width() + 28, rect.height() + 28 + 10)
        self._place(anchor)
        self.show()
        self.raise_()
        self.update()
        self._hide_timer.start(int(seconds * 1000 + len(text) * 40))

    def _place(self, anchor: Character) -> None:
        screen = QApplication.screenAt(anchor.geometry().center()) or QApplication.primaryScreen()
        g = screen.availableGeometry()
        x = anchor.x() + anchor.width() // 2 - self.width() // 2
        y = anchor.y() - self.height() + 6
        if y < g.top():  # no room above -> show below
            y = anchor.y() + anchor.height() - 6
        x = min(max(x, g.left() + 4), g.right() - self.width() - 4)
        self.move(x, y)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(2, 2, self.width() - 4, self.height() - 14)
        p.setPen(QPen(QColor(50, 40, 110), 2))
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawRoundedRect(body, 14, 14)
        # little tail
        tail = QPainterPath(QPointF(self.width() / 2 - 8, body.bottom() - 1))
        tail.lineTo(self.width() / 2, self.height() - 3)
        tail.lineTo(self.width() / 2 + 8, body.bottom() - 1)
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawPath(tail)
        p.setPen(QColor(30, 25, 70))
        p.setFont(self._font)
        p.drawText(body.adjusted(12, 8, -12, -8), int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignVCenter), self._text)
        p.end()
