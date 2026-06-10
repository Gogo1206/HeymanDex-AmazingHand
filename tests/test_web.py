"""Hardware-free unit tests for the web control panel backend."""
import pytest
from pathlib import Path

from amazing_hand.amazing_hand_web import (
    ACTION_MAP,
    HandService,
    speed_from_pct,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# -------------------------------------------------------------------
# speed_from_pct
# -------------------------------------------------------------------

class TestSpeedFromPct:
    def test_minimum_clamps_to_1(self):
        assert speed_from_pct(0) == 1
        assert speed_from_pct(-10) == 1

    def test_maximum_clamps_to_6(self):
        assert speed_from_pct(100) == 6
        assert speed_from_pct(200) == 6

    def test_midpoints(self):
        assert speed_from_pct(50) == 3
        assert speed_from_pct(25) == 2
        actual = speed_from_pct(75)
        assert actual in (4, 5)


# -------------------------------------------------------------------
# ACTION_MAP
# -------------------------------------------------------------------

class TestActionMap:
    def test_all_four_keys(self):
        assert set(ACTION_MAP) == {"A", "B", "C", "D"}

    def test_poses_exist_in_config(self):
        """Every mapped pose name must exist in data/hand_config.yaml."""
        from amazing_hand.amazing_hand_cmd import load_config
        cfg = load_config(PROJECT_ROOT / "data" / "hand_config.yaml")

        for key in ("A", "B", "C", "D"):
            _, name = ACTION_MAP[key]
            assert name in cfg.get("poses", {}), f"pose '{name}' missing"


# -------------------------------------------------------------------
# HandService (no hardware)
# -------------------------------------------------------------------

class TestHandServiceNoHardware:
    def setup_method(self):
        self.cfg = PROJECT_ROOT / "data" / "hand_config.yaml"
        self.svc = HandService("/dev/null", 1000000, self.cfg)

    def test_status_disconnected(self):
        s = self.svc.status()
        assert s["connected"] is False
        assert s["port"] == "/dev/null"
        assert s["gesture"] is None
        assert s["speed_pct"] == 50

    def test_do_pose_not_connected(self):
        result = self.svc.do_pose("open", 3)
        assert result["ok"] is False
        assert "Not connected" in result["error"]

    def test_do_pose_unknown(self):
        result = self.svc.do_pose("nonexistent_pose_xyz", 3)
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_run_action_unknown_button(self):
        result = self.svc.run_action("X", 50)
        assert result["ok"] is False
        assert "Unknown" in result["error"]

    def test_run_action_updates_gesture_and_speed(self):
        self.svc.run_action("A", 75)
        assert self.svc.gesture == "A"
        assert self.svc.speed_pct == 75

    def test_run_action_clamps_speed(self):
        self.svc.run_action("B", 999)
        assert self.svc.speed_pct == 100


# -------------------------------------------------------------------
# Handler exists
# -------------------------------------------------------------------

class TestHandlerSmoke:
    def test_import_and_class_exists(self):
        from amazing_hand.amazing_hand_web import PanelHandler
        from http.server import BaseHTTPRequestHandler
        assert issubclass(PanelHandler, BaseHTTPRequestHandler)
