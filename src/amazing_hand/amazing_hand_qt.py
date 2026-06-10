#!/usr/bin/env python3
"""
AmazingHand native control panel — PyQt6.

Native macOS/Windows port of the RE50 web button panel (web/index.html):
4 candy buttons (A=open B=ok C=close D=victory), a rotary speed knob, a CRT-style
status panel and gesture preview.  Visuals match the web design via custom
QPainter widgets (Qt QSS can't do the gloss/3D/shadows on its own).

Run:
    python amazing_hand_qt.py
"""
from __future__ import annotations

import math
import sys
import threading
from datetime import datetime

from PyQt6.QtCore import (
    Qt, QTimer, QRectF, QPointF, pyqtSignal, QObject, QSize,
)
from PyQt6.QtGui import (
    QColor, QPainter, QLinearGradient, QRadialGradient, QPen, QBrush, QFont,
    QPainterPath, QFontMetrics,
)
from PyQt6.QtWidgets import (
    QApplication, QAbstractButton, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QVBoxLayout, QWidget, QFrame,
)

from amazing_hand.hand_logic import CONFIG_FILE, DEFAULT_BAUDRATE, default_serial_port
from amazing_hand.amazing_hand_cmd import connect, load_config, apply_pose

# ── palette (from web :root) ─────────────────────────────────────────
TERRA_100 = "#F5E6D8"
TERRA_300 = "#D4B08C"
TERRA_400 = "#B87A5A"
TERRA_500 = "#9C6340"
TERRA_600 = "#7A4D30"
TERRA_700 = "#5C3A24"
PANEL_BG = "#2C2420"
PANEL_SURFACE = "#3A322C"
STATUS_BG = "#1A1714"
PREVIEW_BG = "#201A17"   # gesture-preview bar (≈ black 0.28 over PANEL_BG)
TEXT_PRIMARY = "#F5E6D8"
TEXT_SECONDARY = "#B89E88"
TEXT_MUTED = "#7A6A5C"
LED_GREEN = "#4CAF50"
LED_RED = "#F44336"

# button id → (emoji, label, pose, light, base, dark, glow)
BUTTONS = {
    "A": ("🖐", "四指张开", "open",    "#6DD5FA", "#4FC3F7", "#015F92"),
    "B": ("🤏", "抓取",    "ok",      "#FFB088", "#FF8A65", "#B13500"),
    "C": ("✊", "握拳",    "close",   "#D89CE4", "#BA68C8", "#5A1578"),
    "D": ("✌", "胜利",    "victory", "#A8E6A3", "#81C784", "#1B5E20"),
}


def _speed(pct: int) -> int:
    return max(1, min(6, round(pct / 100 * 6)))


# ── candy button (custom-painted, matches web .action-btn) ───────────
class CandyButton(QAbstractButton):
    activated = pyqtSignal(str)

    def __init__(self, bid, emoji, label, light, base, dark, parent=None):
        super().__init__(parent)
        self.bid = bid
        self.emoji = emoji
        self.label = label
        self.light = QColor(light)
        self.base = QColor(base)
        self.dark = QColor(dark)
        self._hover = False
        self._active = False
        self.setFixedSize(150, 150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: self.activated.emit(self.bid))

    def setActive(self, on: bool):
        self._active = on
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self):
        return QSize(150, 150)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pressed = self.isDown()
        # circle geometry — leave room for raised base ring + shadow
        d = 132
        cx = (w - d) / 2
        cy = (h - d) / 2 - 4 + (4 if pressed else 0)

        # drop shadow
        shadow = QColor(0, 0, 0, 110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(QRectF(cx, cy + (4 if pressed else 8), d, d))

        # raised base ring (3D edge)
        p.setBrush(self.dark)
        p.drawEllipse(QRectF(cx, cy + (3 if pressed else 6), d, d))

        # active glow ring
        if self._active or self._hover:
            glow = QColor(self.base)
            glow.setAlpha(90 if self._active else 55)
            p.setPen(QPen(glow, 6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - 3, cy - 3, d + 6, d + 6))

        face = QRectF(cx, cy, d, d)
        # main face gradient (145deg light→base)
        grad = QLinearGradient(face.topLeft(), face.bottomRight())
        grad.setColorAt(0, self.light)
        grad.setColorAt(1, self.base)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(face)

        # glossy top highlight
        gloss = QRectF(cx + 14, cy + 8, d - 28, d * 0.5)
        gg = QLinearGradient(gloss.topLeft(), gloss.bottomLeft())
        gg.setColorAt(0, QColor(255, 255, 255, 90))
        gg.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(gg)
        p.drawEllipse(gloss)

        # emoji + letter
        p.setPen(QColor(255, 255, 255, 235))
        ef = QFont()
        ef.setPointSize(30)
        p.setFont(ef)
        p.drawText(face.adjusted(0, 6, 0, -34),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                   self.emoji)
        lf = QFont("Helvetica", 16, QFont.Weight.Bold)
        p.setFont(lf)
        p.drawText(face.adjusted(0, 30, 0, -14),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                   self.bid)
        p.end()


# ── speed knob (custom-painted, matches web .knob) ────────────────────
class SpeedKnob(QWidget):
    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 50          # 0..100
        self._dragging = False
        self.setFixedSize(170, 170)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def value(self):
        return self._value

    def setValue(self, v):
        v = max(0, min(100, int(v)))
        if v != self._value:
            self._value = v
            self.valueChanged.emit(v)
            self.update()

    def _angle_from_pos(self, pos):
        c = QPointF(self.width() / 2, self.height() / 2)
        ang = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x())) + 90
        if ang < 0:
            ang += 360
        ang -= 45
        if ang < 0:
            ang += 360
        if ang > 315:
            ang = 0
        if ang > 270:
            ang = 270
        return int(ang / 270 * 100)

    def mousePressEvent(self, e):
        self._dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.setValue(self._angle_from_pos(e.position()))

    def mouseMoveEvent(self, e):
        if self._dragging:
            self.setValue(self._angle_from_pos(e.position()))

    def mouseReleaseEvent(self, e):
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = 75

        # tick marks (24)
        p.setPen(QPen(QColor(TERRA_500), 2))
        for i in range(24):
            a = math.radians(i * 15)
            x1 = cx + (r + 6) * math.sin(a)
            y1 = cy - (r + 6) * math.cos(a)
            x2 = cx + (r + 12) * math.sin(a)
            y2 = cy - (r + 12) * math.cos(a)
            pen = QPen(QColor(TERRA_500))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # outer ring
        p.setPen(QPen(QColor(TERRA_600), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # body gradient
        body = QRectF(cx - r + 12, cy - r + 12, 2 * (r - 12), 2 * (r - 12))
        grad = QLinearGradient(body.topLeft(), body.bottomRight())
        grad.setColorAt(0, QColor(TERRA_300))
        grad.setColorAt(1, QColor(TERRA_500))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(body)

        # indicator line (rotates 0%→-135°, 100%→+135°)
        rot = math.radians(self._value / 100 * 270 - 135)
        ir = r - 18
        ix = cx + ir * math.sin(rot)
        iy = cy - ir * math.cos(rot)
        pen = QPen(QColor(TERRA_100), 4, cap=Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(cx, cy), QPointF(ix, iy))

        # center cap
        cap = QRadialGradient(QPointF(cx, cy), 13)
        cap.setColorAt(0, QColor(TERRA_600))
        cap.setColorAt(1, QColor(TERRA_700))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cap)
        p.drawEllipse(QPointF(cx, cy), 13, 13)
        p.end()


# ── small styled pieces ──────────────────────────────────────────────
def _section_title(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{TEXT_MUTED}; font-size:11px; font-weight:700; letter-spacing:3px;"
    )
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


_card_seq = 0


class Card(QFrame):
    """Rounded surface card (matches web panels).

    The stylesheet is scoped by objectName so it does NOT cascade to child
    widgets — QLabel subclasses QFrame, so an unscoped ``QFrame{border:…}``
    would draw a box around every label inside the card.
    """
    def __init__(self, bg, border, radius=14, parent=None):
        super().__init__(parent)
        global _card_seq
        _card_seq += 1
        name = f"card{_card_seq}"
        self.setObjectName(name)
        self.setStyleSheet(
            f"QFrame#{name}{{background:{bg}; border:{border}; border-radius:{radius}px;}}"
        )


# ── worker signal bridge ──────────────────────────────────────────────
class _Signals(QObject):
    log = pyqtSignal(str)
    connected = pyqtSignal(bool, str)
    pose_done = pyqtSignal(str)


# ── main window ───────────────────────────────────────────────────────
class HandController(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RE50 灵巧手控制台")
        self.setMinimumSize(860, 580)
        self.resize(960, 640)
        # disable macOS fullscreen (green button maximizes, no fullscreen space)
        self.setWindowFlag(Qt.WindowType.WindowFullscreenButtonHint, False)

        self._lock = threading.Lock()
        self._ctrl = None
        self._connected = False
        self._sig = _Signals()
        self._buttons = {}
        self._config = load_config(CONFIG_FILE)   # parsed once, reused per press

        self._build()
        self._sig.log.connect(self._append_log)
        self._sig.connected.connect(self._on_connected)
        self._sig.pose_done.connect(self._on_pose_done)

        QTimer.singleShot(200, self._try_connect)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(2000)

    # ── layout ──────────────────────────────────────────────────────
    def _build(self):
        central = QWidget()
        central.setStyleSheet(f"background:{PANEL_BG};")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(22)

        # ── LEFT: button panel ──
        left_card = Card("transparent", "none", 16)
        left = QVBoxLayout(left_card)
        left.setContentsMargins(28, 26, 28, 22)
        left.setSpacing(10)
        left.addWidget(_section_title("手势控制"))
        left.addSpacing(18)

        grid = QGridLayout()
        grid.setSpacing(26)
        grid.setContentsMargins(0, 0, 0, 0)
        for i, (bid, (emoji, label, pose, light, base, dark)) in enumerate(BUTTONS.items()):
            wrap = QVBoxLayout()
            wrap.setSpacing(10)
            btn = CandyButton(bid, emoji, label, light, base, dark)
            btn.activated.connect(self._on_button)
            self._buttons[bid] = btn
            wrap.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
            cap = QLabel(label)
            cap.setStyleSheet(
                f"color:{TEXT_SECONDARY}; font-size:12px; font-weight:700;"
            )
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wrap.addWidget(cap)
            row, col = divmod(i, 2)
            holder = QWidget()
            holder.setLayout(wrap)
            grid.addWidget(holder, row, col, alignment=Qt.AlignmentFlag.AlignCenter)
        left.addLayout(grid)
        left.addStretch()
        left.addWidget(self._build_preview())

        root.addWidget(left_card, 1)

        # ── RIGHT: status + knob ──
        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self._build_status())
        right.addWidget(self._build_knob(), 1)

        rw = QWidget()
        rw.setFixedWidth(280)
        rw.setLayout(right)
        root.addWidget(rw)

    def _build_preview(self):
        # solid dark color (≈ rgba black 0.28 over PANEL_BG) so the box and the
        # labels inside it share one uniform background, no lighter patches.
        bg = PREVIEW_BG
        card = Card(bg, "none", 12)
        self._prev_card = card
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)
        self._prev_emoji = QLabel("🤖")
        self._prev_emoji.setStyleSheet(f"font-size:38px; background:{bg};")
        lay.addWidget(self._prev_emoji)
        info = QVBoxLayout()
        info.setSpacing(2)
        self._prev_name = QLabel("RE50 灵巧手待命中")
        self._prev_name.setStyleSheet(
            f"color:{TEXT_PRIMARY}; font-size:18px; font-weight:600; background:{bg};"
        )
        self._prev_desc = QLabel("点击任意按钮开始控制 · 8自由度仿生手")
        self._prev_desc.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px; background:{bg};")
        info.addWidget(self._prev_name)
        info.addWidget(self._prev_desc)
        lay.addLayout(info, 1)
        self._prev_time = QLabel("--:--:--")
        self._prev_time.setStyleSheet(f"color:{TEXT_MUTED}; font-size:10px; background:{bg};")
        lay.addWidget(self._prev_time, alignment=Qt.AlignmentFlag.AlignTop)
        self._clock = QTimer(self)
        self._clock.timeout.connect(
            lambda: self._prev_time.setText(datetime.now().strftime("%H:%M:%S"))
        )
        self._clock.start(1000)
        return card

    def _build_status(self):
        card = Card("transparent", f"2px solid {TERRA_600}", 14)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        # header
        head = QHBoxLayout()
        t = QLabel("实时状态")
        t.setStyleSheet(
            f"color:{TERRA_400}; font-size:10px; font-weight:700; letter-spacing:2px;"
        )
        head.addWidget(t)
        head.addStretch()
        self._badge = QFrame()
        self._badge_lay = QHBoxLayout(self._badge)
        self._badge_lay.setContentsMargins(8, 3, 10, 3)
        self._badge_lay.setSpacing(6)
        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color:{LED_RED}; font-size:9px;")
        self._conn_text = QLabel("连接中…")
        self._conn_text.setStyleSheet(f"color:{LED_RED}; font-size:9px; font-weight:600;")
        self._badge_lay.addWidget(self._dot)
        self._badge_lay.addWidget(self._conn_text)
        self._set_badge(False)
        head.addWidget(self._badge)
        lay.addLayout(head)

        # rows
        self._gesture_val = self._status_row(lay, "当前手势", "待命中", big=True)
        self._port_val = self._status_row(lay, "串口", "—")
        self._speed_val = self._status_row(lay, "速度档位", "50%")

        # log (single last line, transparent)
        self._log = QLabel("控制面板已就绪")
        self._log.setStyleSheet(
            f"color:{TEXT_MUTED}; font-family:Monaco,monospace; font-size:10px;"
            f"background:transparent; border:none;"
        )
        lay.addWidget(self._log)
        return card

    def _status_row(self, parent, key, val, big=False):
        row = QHBoxLayout()
        k = QLabel(key)
        k.setStyleSheet(f"color:{TEXT_MUTED}; font-size:12px; font-weight:600;")
        v = QLabel(val)
        size = 15 if big else 13
        v.setStyleSheet(
            f"color:{TEXT_PRIMARY}; font-size:{size}px; font-weight:600;"
            f"font-family:Monaco,monospace;"
        )
        row.addWidget(k)
        row.addStretch()
        row.addWidget(v)
        parent.addLayout(row)
        return v

    def _build_knob(self):
        card = Card("transparent", "none", 14)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(8)
        lay.addStretch()
        lay.addWidget(_section_title("速度控制"))
        lay.addSpacing(6)
        self._knob = SpeedKnob()
        self._knob.valueChanged.connect(self._on_knob)
        lay.addWidget(self._knob, alignment=Qt.AlignmentFlag.AlignCenter)
        self._knob_val = QLabel("50%")
        self._knob_val.setStyleSheet(
            f"color:{TEXT_PRIMARY}; font-size:24px; font-weight:700;"
            f"font-family:Monaco,monospace;"
        )
        self._knob_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(14)
        lay.addWidget(self._knob_val)
        kl = QLabel("速度")
        kl.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px; font-weight:700; letter-spacing:1px;")
        kl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(kl)
        lay.addStretch()
        return card

    # ── connection state ────────────────────────────────────────────
    def _set_badge(self, ok):
        color = LED_GREEN if ok else LED_RED
        bg = "rgba(76,175,80,0.12)" if ok else "rgba(244,67,54,0.12)"
        bd = "rgba(76,175,80,0.30)" if ok else "rgba(244,67,54,0.30)"
        self._badge.setStyleSheet(
            f"QFrame{{background:{bg}; border:1px solid {bd}; border-radius:11px;}}"
        )
        self._dot.setStyleSheet(f"color:{color}; font-size:9px; border:none;")
        self._conn_text.setStyleSheet(
            f"color:{color}; font-size:9px; font-weight:600; border:none;"
        )
        self._conn_text.setText("已连接" if ok else "未连接")

    def _try_connect(self):
        port = default_serial_port()
        self._port_val.setText(port.rsplit("/", 1)[-1])
        self._append_log(f"连接 {port} …")

        def _conn():
            try:
                ctrl = connect(port, DEFAULT_BAUDRATE)
                with self._lock:
                    self._ctrl = ctrl
                self._sig.connected.emit(True, port)
            except SystemExit:
                self._sig.connected.emit(False, f"端口 {port} 无法打开")
            except Exception as exc:
                self._sig.connected.emit(False, str(exc))

        threading.Thread(target=_conn, daemon=True).start()

    def _on_connected(self, ok, detail):
        self._connected = ok
        self._set_badge(ok)
        self._append_log("已连接" if ok else f"连接失败: {detail}")

    def _poll(self):
        if not self._connected:
            return
        try:
            with self._lock:
                if self._ctrl is None:
                    return
                self._ctrl.read_present_position(1)
        except Exception:
            self._connected = False
            self._set_badge(False)
            self._append_log("连接断开")

    # ── actions ─────────────────────────────────────────────────────
    def _on_button(self, bid):
        if not self._connected:
            self._append_log("未连接，忽略操作")
            return
        emoji, label, pose, light, base, dark = BUTTONS[bid]
        for b in self._buttons.values():
            b.setActive(b.bid == bid)
        speed = _speed(self._knob.value())
        self._gesture_val.setText(label)
        self._gesture_val.setStyleSheet(
            f"color:{base}; font-size:15px; font-weight:600; font-family:Monaco,monospace;"
        )
        # tint the whole preview bar (box + all labels) to a dark shade of the
        # gesture color so the background changes per gesture and stays uniform
        tint = QColor(base).darker(460).name()
        self._tint_preview(tint, emoji, label, light)
        self._append_log(f"→ {label} (speed {speed})")

        def _run():
            try:
                positions = self._config["poses"][pose]["positions"]
                with self._lock:
                    if self._ctrl is not None:
                        apply_pose(self._ctrl, positions, [speed] * 8)
                self._sig.pose_done.emit(bid)
            except Exception as exc:
                self._sig.log.emit(f"错误: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def _on_pose_done(self, bid):
        self._append_log(f"✓ {BUTTONS[bid][1]}")

    def _tint_preview(self, bg, emoji, name, name_color):
        cn = self._prev_card.objectName()
        self._prev_card.setStyleSheet(
            f"QFrame#{cn}{{background:{bg}; border:none; border-radius:12px;}}"
        )
        self._prev_emoji.setText(emoji)
        self._prev_emoji.setStyleSheet(f"font-size:38px; background:{bg};")
        self._prev_name.setText(name)
        self._prev_name.setStyleSheet(
            f"color:{name_color}; font-size:18px; font-weight:600; background:{bg};"
        )
        self._prev_desc.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px; background:{bg};")
        self._prev_time.setStyleSheet(f"color:{TEXT_MUTED}; font-size:10px; background:{bg};")

    def _on_knob(self, val):
        self._knob_val.setText(f"{val}%")
        self._speed_val.setText(f"{val}%")

    def _append_log(self, msg):
        self._log.setText(f"[{datetime.now():%H:%M:%S}] {msg}")

    def closeEvent(self, e):
        self._poll_timer.stop()
        with self._lock:
            self._ctrl = None
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RE50 Hand Controller")
    win = HandController()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
