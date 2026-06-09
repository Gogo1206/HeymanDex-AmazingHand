#!/usr/bin/env python3
"""
AmazingHand native control panel — PyQt6.

4-button layout (A=open B=ok C=close D=victory), speed dial, status panel,
and connection management.  Cross-platform: macOS + Windows.

Run:
    python amazing_hand_qt.py
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QDial,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hand_logic import CONFIG_FILE, DEFAULT_BAUDRATE, default_serial_port
from amazing_hand_cmd import connect, load_config, apply_pose

# ── button → pose map ────────────────────────────────────────────────
BUTTONS = {
    "A": ("🖐️", "四指张开", "open",     "#4FC3F7"),
    "B": ("🤏", "抓取",   "ok",       "#FF8A65"),
    "C": ("✊", "握拳",   "close",    "#BA68C8"),
    "D": ("✌️", "胜利",   "victory",  "#81C784"),
}


# ── helpers ───────────────────────────────────────────────────────────
def _speed(pct: int) -> int:
    return max(1, min(6, round(pct / 100 * 6)))


# ── worker signal bridge ──────────────────────────────────────────────
class _Signals(QObject):
    log = pyqtSignal(str)
    connected = pyqtSignal(bool, str)  # ok, detail
    pose_done = pyqtSignal(str)         # button_id


# ── main window ───────────────────────────────────────────────────────
class HandController(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RE50 灵巧手控制台")
        self.setMinimumSize(540, 680)
        self.resize(540, 700)

        self._lock = threading.Lock()
        self._ctrl = None
        self._connected = False
        self._port = ""
        self._sig = _Signals()

        self._setup_ui()
        self._setup_style()
        self._wire_signals()

        # auto-connect after UI paints
        QTimer.singleShot(200, self._try_connect)

        # liveness poll
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(2000)

    # ── UI construction ────────────────────────────────────────────
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(20)

        # ── LEFT ──
        left = QVBoxLayout()
        left.setSpacing(12)

        title = QLabel("手势控制")
        title.setObjectName("sectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(title)
        left.addSpacing(8)

        grid = QGridLayout()
        grid.setSpacing(24)
        for i, (bid, (emoji, label, pose, color)) in enumerate(BUTTONS.items()):
            btn = _CandyButton(bid, emoji, label, color)
            btn.clicked.connect(self._on_button)
            row, col = divmod(i, 2)
            grid.addWidget(btn, row, col)
        left.addLayout(grid)
        left.addSpacing(12)

        # status
        self._status_group = QGroupBox("实时状态")
        sg = QVBoxLayout(self._status_group)
        sg.setSpacing(6)
        self._conn_label = QLabel("连接中…")
        self._conn_label.setObjectName("connBadge")
        self._gesture_label = QLabel("待命中")
        self._port_label = QLabel("—")
        self._speed_label = QLabel("50%")
        for k, v in [("连接", self._conn_label), ("手势", self._gesture_label),
                      ("串口", self._port_label), ("速度", self._speed_label)]:
            row = QHBoxLayout()
            kl = QLabel(k)
            kl.setObjectName("statusKey")
            row.addWidget(kl)
            row.addStretch()
            row.addWidget(v)
            sg.addLayout(row)
        left.addWidget(self._status_group)

        # log
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(200)
        self._log.setFixedHeight(80)
        left.addWidget(self._log)

        root.addLayout(left, 1)

        # ── RIGHT ──
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addStretch()

        knob_title = QLabel("速度控制")
        knob_title.setObjectName("sectionTitle")
        knob_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(knob_title)

        self._dial = QDial()
        self._dial.setRange(0, 100)
        self._dial.setValue(50)
        self._dial.setNotchesVisible(True)
        self._dial.setFixedSize(160, 160)
        self._dial.valueChanged.connect(self._on_dial)
        right.addWidget(self._dial, alignment=Qt.AlignmentFlag.AlignCenter)

        self._dial_label = QLabel("50%")
        self._dial_label.setObjectName("dialValue")
        self._dial_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self._dial_label)

        kl = QLabel("速度")
        kl.setObjectName("knobLabel")
        kl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(kl)
        right.addStretch()

        root.addLayout(right)

        # statusbar
        self.statusBar().showMessage("启动中…")

    def _setup_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #2C2420; }
            QLabel { color: #F5E6D8; font-family: -apple-system, sans-serif; }
            QLabel#sectionTitle {
                color: #7A6A5C; font-size: 11px; font-weight: 700;
                letter-spacing: 3px; text-transform: uppercase;
            }
            QLabel#statusKey { color: #7A6A5C; font-size: 12px; font-weight: 600; }
            QLabel#connBadge { color: #4CAF50; font-size: 13px; font-weight: 600; }
            QLabel#dialValue {
                color: #F5E6D8; font-size: 22px; font-weight: 700;
            }
            QLabel#knobLabel {
                color: #7A6A5C; font-size: 11px; font-weight: 700;
                letter-spacing: 1px; text-transform: uppercase;
            }
            QGroupBox {
                color: #B87A5A; font-size: 10px; font-weight: 700;
                border: 2px solid #7A4D30; border-radius: 10px;
                margin-top: 8px; padding-top: 14px;
                background: #1A1714;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; }
            QPlainTextEdit {
                background: rgba(0,0,0,60); border: 1px solid #3A322C;
                border-radius: 8px; color: #7A6A5C;
                font-family: Monaco, monospace; font-size: 10px;
            }
            QDial {
                background: #3A322C; border-radius: 80px;
                border: 2px solid #7A4D30;
            }
            QStatusBar { color: #7A6A5C; font-size: 10px; background: #1A1512; }
        """)

    def _wire_signals(self):
        self._sig.log.connect(self._append_log)
        self._sig.connected.connect(self._on_connected)
        self._sig.pose_done.connect(self._on_pose_done)

    # ── connection ─────────────────────────────────────────────────
    def _try_connect(self):
        port = default_serial_port()
        self._port = port
        self._port_label.setText(port.rsplit("/", 1)[-1])
        self._append_log(f"连接 {port} …")

        def _conn():
            try:
                ctrl = connect(port, DEFAULT_BAUDRATE)
                with self._lock:
                    self._ctrl = ctrl
                    self._connected = True
                self._sig.connected.emit(True, port)
            except SystemExit:
                self._sig.connected.emit(False, f"端口 {port} 无法打开")
            except Exception as exc:
                self._sig.connected.emit(False, str(exc))

        threading.Thread(target=_conn, daemon=True).start()

    def _on_connected(self, ok, detail):
        if ok:
            self._connected = True
            self._conn_label.setText("已连接")
            self._conn_label.setStyleSheet("color: #4CAF50;")
            self.statusBar().showMessage(f"已连接 — {detail}")
            self._append_log("已连接")
        else:
            self._connected = False
            self._conn_label.setText("未连接")
            self._conn_label.setStyleSheet("color: #F44336;")
            self.statusBar().showMessage("未连接")
            self._append_log(f"连接失败: {detail}")

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
            self._conn_label.setText("未连接")
            self._conn_label.setStyleSheet("color: #F44336;")
            self.statusBar().showMessage("连接断开")
            self._append_log("连接断开")

    # ── actions ────────────────────────────────────────────────────
    def _on_button(self):
        btn = self.sender()
        if not isinstance(btn, _CandyButton) or not self._connected:
            return
        bid = btn._bid  # noqa: SLF001
        _, label, pose, _ = BUTTONS[bid]
        pct = self._dial.value()
        speed = _speed(pct)

        self._gesture_label.setText(label)
        self._append_log(f"→ {label} (speed {speed})")

        def _run():
            try:
                cfg = load_config(CONFIG_FILE)
                positions = cfg["poses"][pose]["positions"]
                with self._lock:
                    if self._ctrl is not None:
                        apply_pose(self._ctrl, positions, [speed] * 8)
                self._sig.pose_done.emit(bid)
            except Exception as exc:
                self._sig.log.emit(f"错误: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def _on_pose_done(self, bid):
        _, label, _, _ = BUTTONS[bid]
        self._append_log(f"✓ {label}")

    def _on_dial(self, val):
        self._dial_label.setText(f"{val}%")
        self._speed_label.setText(f"{val}%")

    def _append_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.appendPlainText(f"[{ts}] {msg}")

    def closeEvent(self, event):
        self._poll_timer.stop()
        with self._lock:
            self._ctrl = None
        event.accept()


# ── candy button widget ─────────────────────────────────────────────
class _CandyButton(QPushButton):
    def __init__(self, bid, emoji, label, color, parent=None):
        super().__init__(parent)
        self._bid = bid
        self.setFixedSize(140, 140)
        self.setText(f"{emoji}\n{bid}")
        self.setToolTip(label)
        self.setObjectName(f"btn{bid}")
        dark = QColor(color).darker(180).name()
        glow = QColor(color)
        glow.setAlpha(80)
        self.setStyleSheet(f"""
            QPushButton#{self.objectName()} {{
                background: qlineargradient(x1:0 y1:0, x2:1 y2:1,
                    stop:0 {QColor(color).lighter(130).name()}, stop:1 {color});
                border: none; border-radius: 70px;
                color: white; font-size: 30px; font-weight: 700;
            }}
            QPushButton#{self.objectName()}:hover {{
                border: 3px solid {glow.name()};
            }}
            QPushButton#{self.objectName()}:pressed {{
                background: qlineargradient(x1:0 y1:0, x2:1 y2:1,
                    stop:0 {color}, stop:1 {dark});
            }}
        """)


# ── entry ────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RE50 Hand Controller")

    # dark palette fallback
    p = app.palette()
    p.setColor(QPalette.ColorRole.Window, QColor("#2C2420"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#F5E6D8"))
    p.setColor(QPalette.ColorRole.Base, QColor("#1A1714"))
    p.setColor(QPalette.ColorRole.Text, QColor("#F5E6D8"))
    app.setPalette(p)

    win = HandController()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
