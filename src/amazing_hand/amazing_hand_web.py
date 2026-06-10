#!/usr/bin/env python3
"""
AmazingHand web control panel — backend.

Serves a button-panel page (web/index.html, styled after docs/RE50-按钮面板.html)
and exposes the four hand actions as a tiny HTTP/JSON API.  A browser cannot speak
the Feetech serial protocol, so this stdlib http.server process is the bridge: it
holds the serial connection and calls the existing command layer in
amazing_hand_cmd.py.

No third-party web dependencies — only the Python standard library plus the same
rustypot/PyYAML the CLI already needs.

Run:
    python amazing_hand_web.py [--port 8000] [--serial-port /dev/...] [--baudrate N]

Then open http://localhost:8000 in a browser.
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from amazing_hand.hand_logic import CONFIG_FILE, DEFAULT_BAUDRATE, default_serial_port
from amazing_hand.amazing_hand_cmd import (
    connect,
    load_config,
    apply_pose,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
WEB_DIR = BASE_DIR / "web"
INDEX_FILE = WEB_DIR / "index.html"

# Button → hand command. ("pose", name) applies a pose; ("sequence", name) toggles
# a sequence.  Names must exist in data/hand_config.yaml.
ACTION_MAP = {
    "A": ("pose", "open"),       # 四指张开
    "B": ("pose", "ok"),         # 抓取 (pinch)
    "C": ("pose", "close"),      # 握拳 (fist)
    "D": ("pose", "victory"),    # ✌️ victory
}


# ---------------------------------------------------------------------------
# Shared hardware state (one serial bus → serialize every access)
# ---------------------------------------------------------------------------

class HandService:
    """Owns the controller + config and serializes all hardware access."""

    def __init__(self, serial_port: str, baudrate: int, config_path: Path):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.config_path = config_path

        self.lock = threading.Lock()
        self.controller = None
        self.connected = False
        self.error = None
        self.gesture = None          # last activated button id (A/B/C/D)
        self.speed_pct = 50

        self.config = load_config(self.config_path)

    # --- connection -------------------------------------------------------

    def try_connect(self) -> bool:
        """(Re)open the serial connection. Never raises; records error instead."""
        with self.lock:
            self.error = None
            try:
                # connect() may sys.exit on a hard open failure; trap it so the
                # web server stays up and can report a disconnected state.
                self.controller = connect(self.serial_port, self.baudrate)
                self.connected = True
            except SystemExit:
                self.controller = None
                self.connected = False
                self.error = f"Could not open serial port {self.serial_port}"
            except Exception as exc:  # noqa: BLE001 - surface any open failure
                self.controller = None
                self.connected = False
                self.error = str(exc)
        return self.connected

    # --- status -----------------------------------------------------------

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "port": self.serial_port,
            "gesture": self.gesture,
            "speed_pct": self.speed_pct,
            "error": self.error,
        }

    # --- poses ------------------------------------------------------------

    def do_pose(self, name: str, speed: int) -> dict:
        poses = self.config.get("poses", {})
        if name not in poses:
            return {"ok": False, "error": f"Pose '{name}' not found"}
        positions = poses[name].get("positions", [0] * 8)
        with self.lock:
            if self.controller is None:
                return {"ok": False, "error": "Not connected"}
            try:
                apply_pose(self.controller, positions, [speed] * 8)
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                return {"ok": False, "error": str(exc)}
        return {"ok": True}

    # --- dispatch ---------------------------------------------------------

    def run_action(self, button_id: str, speed_pct: int) -> dict:
        if button_id not in ACTION_MAP:
            return {"ok": False, "error": f"Unknown action '{button_id}'"}
        try:
            self.speed_pct = max(0, min(100, int(speed_pct)))
        except (TypeError, ValueError):
            pass
        self.gesture = button_id
        speed = speed_from_pct(self.speed_pct)
        _, name = ACTION_MAP[button_id]
        result = self.do_pose(name, speed)
        result.setdefault("ok", True)
        return result


def speed_from_pct(pct: int) -> int:
    """Map a 0–100% knob value to a servo speed in 1–6 (1=slow, 6=fast)."""
    return max(1, min(6, round(pct / 100 * 6)))


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class PanelHandler(BaseHTTPRequestHandler):
    service: HandService = None  # set on the class before serving

    def log_message(self, fmt, *args):  # quieter logging
        pass

    # -- helpers --
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, "Not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    # -- routes --
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_file(INDEX_FILE, "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._send_json(self.service.status())
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        if self.path == "/api/action":
            body = self._read_json_body()
            result = self.service.run_action(
                body.get("id", ""), body.get("speed_pct", self.service.speed_pct)
            )
            result["status"] = self.service.status()
            self._send_json(result, status=200 if result.get("ok") else 400)
        elif self.path == "/api/reconnect":
            ok = self.service.try_connect()
            self._send_json({"ok": ok, "status": self.service.status()})
        else:
            self.send_error(404, "Not found")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AmazingHand web control panel")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default 8000)")
    parser.add_argument(
        "--serial-port", default=default_serial_port(),
        help="Serial port for the hand (default: auto-detected)",
    )
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    args = parser.parse_args()

    service = HandService(args.serial_port, args.baudrate, args.config)
    print(f"Connecting to hand on {args.serial_port} …")
    if service.try_connect():
        print("Hand connected.")
    else:
        print(f"WARNING: hand not connected ({service.error}). "
              f"Server will still start; use Reconnect in the UI.")

    PanelHandler.service = service
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), PanelHandler)
    print(f"Serving on http://localhost:{args.port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down …")
        httpd.shutdown()


if __name__ == "__main__":
    main()
