"""The funny on-screen character: a draggable, always-on-top, click-through-transparent blob."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QImage, QPixmap, QColor, QCursor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
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
        self._head, self._meta = _load_head()
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
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._head is not None:
            self._paint_avatar(p, s)
            p.end()
            return
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


    # ------------------------------------------------- photo-based avatar
    def _paint_avatar(self, p: QPainter, s: int) -> None:
        t, state = self._t, self.state
        amp = {IDLE: 0.015, LISTENING: 0.04, THINKING: 0.02, SPEAKING: 0.05}[state]
        speed = {IDLE: 2.0, LISTENING: 5.0, THINKING: 2.5, SPEAKING: 9.0}[state]
        wob = math.sin(t * speed)
        bounce = -abs(math.sin(t * speed * 0.5)) * s * amp * 1.6
        sx, sy = 1 + amp * wob, 1 - amp * wob

        cx = s / 2
        ground = s * 0.965

        # ground shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QPointF(cx, ground), s * 0.26 * (1 + bounce / s), s * 0.035)

        # listening ring / thinking stars / speaking waves
        if state == LISTENING:
            ph = (t * 1.6) % 1
            p.setPen(QPen(QColor(0, 220, 255, int(200 * (1 - ph))), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = s * (0.30 + 0.22 * ph)
            p.drawEllipse(QPointF(cx, s * 0.42 + bounce), r, r)

        # --- body: tiny funny torso + feet ---
        body_top = s * 0.66 + bounce
        bw, bh = s * 0.22 * sx, s * 0.17 * sy
        grad = QLinearGradient(cx - bw, body_top, cx + bw, body_top + bh * 2)
        grad.setColorAt(0, QColor(120, 100, 255))
        grad.setColorAt(1, QColor(60, 180, 220))
        p.setPen(QPen(QColor(50, 35, 90), 3))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(cx - bw, body_top, bw * 2, bh * 1.6), bw * 0.7, bw * 0.7)
        # belly shine
        shine = QRadialGradient(QPointF(cx - bw * 0.4, body_top + bh * 0.3), bw)
        shine.setColorAt(0, QColor(255, 255, 255, 120))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(shine))
        p.drawRoundedRect(QRectF(cx - bw, body_top, bw * 2, bh * 1.6), bw * 0.7, bw * 0.7)
        # feet
        p.setPen(QPen(QColor(50, 35, 90), 2))
        p.setBrush(QColor(255, 255, 255))
        for fx in (-0.5, 0.5):
            p.drawEllipse(QPointF(cx + bw * fx, body_top + bh * 1.62), s * 0.07, s * 0.032)
        # arms: wave when speaking, hands-up when listening, scratch-head when thinking
        arm_len = s * 0.14
        for side in (-1, 1):
            sh = QPointF(cx + side * bw * 0.95, body_top + bh * 0.45)
            if state == SPEAKING:
                ang = math.radians(-50 - 25 * math.sin(t * 10 + (0 if side > 0 else 1.6)))
            elif state == LISTENING:
                ang = math.radians(-100 + 10 * math.sin(t * 6))
            elif state == THINKING and side > 0:
                ang = math.radians(-125 + 8 * math.sin(t * 8))
            else:
                ang = math.radians(40 + 6 * math.sin(t * 2 + side))
            dx, dy = math.cos(ang) * side, math.sin(ang)
            hand = QPointF(sh.x() + dx * arm_len, sh.y() + dy * arm_len)
            p.setPen(QPen(QColor(50, 35, 90), s * 0.05, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(sh, hand)
            p.setPen(QPen(QColor(255, 220, 190), s * 0.035, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(sh, hand)

        # --- head: big bobblehead that tilts on the neck ---
        head = self._head
        hw = s * 0.56 * sx
        hh = hw * head.height() / head.width() * sy
        neck = QPointF(cx, body_top + s * 0.02)
        tilt = {IDLE: 4, LISTENING: 7, THINKING: 10, SPEAKING: 6}[state] * math.sin(t * speed * 0.5)
        if state == THINKING:
            tilt += 8
        p.save()
        p.translate(neck)
        p.rotate(tilt)
        rect = QRectF(-hw / 2, -hh * 0.93, hw, hh)
        p.drawPixmap(rect, head, QRectF(head.rect()))
        self._head_overlays(p, rect)
        p.restore()

        # --- floating status icons (drawn unrotated) ---
        if state == THINKING:
            p.setPen(QPen(QColor(50, 35, 90), 2))
            for i in range(3):
                a = t * 4 + i * 2.09
                p.setBrush(QColor(255, 200, 60))
                p.drawEllipse(QPointF(cx + math.cos(a) * s * 0.3, s * 0.08 + math.sin(a) * s * 0.05), s * 0.03, s * 0.03)

    def _head_overlays(self, p: QPainter, rect: QRectF) -> None:
        """Mouth / eyelids drawn on top of the photo head (rect = where the head is drawn)."""
        meta = self._meta
        w, h = rect.width(), rect.height()

        def at(fx, fy):
            return QPointF(rect.x() + fx * w, rect.y() + fy * h)

        # eyelids for blinking (only if both eyes were located reliably)
        if meta.get("eyes_ok") and self._blink > 0.2:
            skin = QColor(*meta.get("skin", (225, 170, 140)))
            p.setPen(QPen(skin.darker(150), 1))
            p.setBrush(skin)
            for ex, ey, er in meta["eyes"]:
                c = at(ex, ey)
                p.drawEllipse(c, er * w * 1.25, er * w * 0.7 * self._blink)

        mx, my, mr = meta["mouth"]
        c = at(mx, my)
        if self.state == SPEAKING:
            open_ = 0.25 + 0.75 * abs(math.sin(self._t * 13))
            p.setPen(QPen(QColor(60, 15, 30), 2))
            p.setBrush(QColor(110, 20, 40))
            p.drawEllipse(c, mr * w * 0.55, mr * w * 0.42 * open_)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(240, 110, 130))
            p.drawEllipse(QPointF(c.x(), c.y() + mr * w * 0.25 * open_), mr * w * 0.3, mr * w * 0.14 * open_)
        elif self.state == LISTENING:
            p.setPen(QPen(QColor(60, 15, 30), 2))
            p.setBrush(QColor(110, 20, 40))
            p.drawEllipse(c, mr * w * 0.2, mr * w * 0.26)  # surprised "o"
        elif self.state == IDLE and int(self._t * 10) % 90 < 6:
            # cheeky tongue-out every few seconds
            p.setPen(QPen(QColor(120, 30, 50), 2))
            p.setBrush(QColor(240, 110, 130))
            p.drawEllipse(QPointF(c.x() + mr * w * 0.1, c.y() + mr * w * 0.45), mr * w * 0.22, mr * w * 0.3)

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



def _load_head() -> tuple[QPixmap | None, dict]:
    """Load assets/head.png (made by `python -m buddy --make-avatar photo.jpg`), with 3D-style lighting."""
    from .avatar import ASSETS

    png, meta_file = ASSETS / "head.png", ASSETS / "head.json"
    if not png.exists() or not meta_file.exists():
        return None, {}
    img = QImage(str(png)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if img.isNull():
        return None, {}
    try:
        meta = json.loads(meta_file.read_text())
    except ValueError:
        return None, {}

    # bake soft lighting: highlight from the top-left, shadow on the bottom-right rim
    w, h = img.width(), img.height()
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    hi = QRadialGradient(QPointF(w * 0.30, h * 0.22), w * 0.55)
    hi.setColorAt(0, QColor(255, 255, 255, 70))
    hi.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(img.rect(), hi)
    sh = QRadialGradient(QPointF(w * 0.40, h * 0.40), w * 0.85)
    sh.setColorAt(0.6, QColor(20, 0, 50, 0))
    sh.setColorAt(1, QColor(20, 0, 50, 110))
    p.fillRect(img.rect(), sh)
    p.end()
    return QPixmap.fromImage(img), meta


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
