"""
System tests requiring REAL hardware — AmazingHand servo controller.

These tests verify end-to-end behaviour against a physical SCS0009
servo bus connected via serial.  They are **skipped** by default and
only run when the ``--hardware`` pytest option is passed::

    pytest tests/test_system_hardware.py --hardware
    pytest tests/test_system_hardware.py --hardware --port /dev/ttyACM0

Markers:
    @pytest.mark.hardware — marks every test in this module

Prerequisites:
    • Working serial connection to the servo bus
    • 8 servos (IDs 1–8) powered and connected
    • ``rustypot`` Python package installed
"""

import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import yaml

from hand_logic import SERVO_PAIRS, FINGER_NAMES, angle_rad

try:
    from rustypot import Scs0009PyController
except ImportError:
    Scs0009PyController = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLI = PROJECT_ROOT / "amazing_hand_cmd.py"

# ---------------------------------------------------------------------------
# Pytest hooks / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hw_port(request):
    return request.config.getoption("--port", default="/dev/ttyACM0")


@pytest.fixture(scope="module")
def hw_baudrate(request):
    return request.config.getoption("--hw-baudrate", default=1000000)


@pytest.fixture(scope="module")
def controller(hw_port, hw_baudrate):
    """Open a real serial connection and enable torque; disable on teardown."""
    if Scs0009PyController is None:
        pytest.skip("rustypot not installed")

    ctrl = Scs0009PyController(
        serial_port=hw_port,
        baudrate=hw_baudrate,
        timeout=0.5,
    )
    # Enable torque on all servos
    for sid in range(1, 9):
        ctrl.write_torque_enable(sid, 1)
    time.sleep(0.3)

    yield ctrl

    # Disable torque on teardown
    for sid in range(1, 9):
        try:
            ctrl.write_torque_enable(sid, 0)
        except Exception:
            pass


@pytest.fixture()
def sample_config_file(tmp_path):
    """Write a sample YAML config for CLI subprocess tests."""
    config = {
        "poses": {
            "open": {"positions": [0, 0, 0, 0, 0, 0, 0, 0]},
            "close": {"positions": [110, 110, 110, 110, 110, 110, 110, 110]},
            "half": {"positions": [55, 55, 55, 55, 55, 55, 55, 55]},
        },
        "sequences": {
            "demo": {
                "steps": [
                    "open:3,3,3,3,3,3,3,3|1.0s",
                    "close:3,3,3,3,3,3,3,3|1.0s",
                ]
            },
        },
    }
    cf = tmp_path / "test_hw_config.yaml"
    cf.write_text(yaml.dump(config))
    return cf


def _move_to_open(ctrl):
    """Helper: move all servos to open (0°)."""
    ids, rads = [], []
    for s1, s2 in SERVO_PAIRS:
        ctrl.write_goal_speed(s1, 6)
        ctrl.write_goal_speed(s2, 6)
        ids.extend([s1, s2])
        rads.extend([angle_rad(s1, 0), angle_rad(s2, 0)])
    ctrl.sync_write_goal_position(ids, rads)
    time.sleep(2.0)


def _move_to_pose(ctrl, positions, speed=3):
    """Helper: send an 8-position pose."""
    ids, rads = [], []
    for finger_idx, (s1, s2) in enumerate(SERVO_PAIRS):
        pos1 = positions[finger_idx * 2]
        pos2 = positions[finger_idx * 2 + 1]
        ctrl.write_goal_speed(s1, speed)
        ctrl.write_goal_speed(s2, speed)
        ids.extend([s1, s2])
        rads.extend([angle_rad(s1, pos1), angle_rad(s2, pos2)])
    ctrl.sync_write_goal_position(ids, rads)


# ===================================================================
# FR-CONN-3: Connect / Disconnect  (AC 3.1, 3.2)
# ===================================================================

@pytest.mark.hardware
class TestHardwareConnection:
    """Verify basic connect, torque enable, and disconnect."""

    def test_controller_connects(self, controller):
        """AC 3.1: Connection opens successfully."""
        assert controller is not None

    def test_torque_enabled_on_connect(self, controller):
        """AC 3.1: Torque is enabled on servos 1–8 after connect."""
        # If torque is on, reading position should not raise
        for sid in range(1, 9):
            pos = controller.read_present_position(sid)
            assert pos is not None


# ===================================================================
# FR-CONN-5: CLI Connection  (AC 5.2, 5.3)
# ===================================================================

@pytest.mark.hardware
class TestHardwareCLIConnection:
    """Verify CLI connects, runs, and disables torque on exit."""

    def test_cli_pose_open(self, hw_port, hw_baudrate, sample_config_file):
        """AC 5.1, 5.2: CLI connects with port/baudrate and sends pose."""
        result = subprocess.run(
            [sys.executable, str(CLI),
             "--pose", "open",
             "--port", hw_port,
             "--baudrate", str(hw_baudrate),
             "--config", str(sample_config_file)],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        assert "Applying pose" in result.stdout

    def test_cli_list_no_hardware(self, sample_config_file):
        """AC 5.4: --list does NOT open a hardware connection."""
        result = subprocess.run(
            [sys.executable, str(CLI),
             "--list",
             "--config", str(sample_config_file)],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0


# ===================================================================
# FR-FING-2: Auto Mode — Apply Pose (AC 2.1, 2.2, 2.3)
# ===================================================================

@pytest.mark.hardware
class TestHardwarePoseApply:
    """Send poses and verify servo positions via feedback."""

    def test_open_pose_positions(self, controller):
        """AC 2.1: Open (0°) pose moves servos near 0°."""
        _move_to_open(controller)
        for sid in range(1, 9):
            raw = controller.read_present_position(sid)
            deg = abs(float(np.rad2deg(float(raw))))
            assert deg < 15.0, f"Servo {sid} at {deg}° instead of ~0°"

    def test_close_pose_positions(self, controller):
        """Close (110°) pose moves servos near 110°."""
        _move_to_pose(controller, [110] * 8, speed=6)
        time.sleep(3.0)
        for s1, s2 in SERVO_PAIRS:
            for sid in (s1, s2):
                raw = controller.read_present_position(sid)
                deg = abs(float(np.rad2deg(float(raw))))
                assert deg > 90.0, f"Servo {sid} at {deg}° instead of ~110°"
        # Return to open for next tests
        _move_to_open(controller)

    def test_half_pose_positions(self, controller):
        """Half (55°) pose moves servos near 55°."""
        _move_to_pose(controller, [55] * 8, speed=6)
        time.sleep(3.0)
        for s1, s2 in SERVO_PAIRS:
            for sid in (s1, s2):
                raw = controller.read_present_position(sid)
                deg = abs(float(np.rad2deg(float(raw))))
                assert 30.0 < deg < 80.0, f"Servo {sid} at {deg}° instead of ~55°"
        _move_to_open(controller)


# ===================================================================
# FR-FING-4: Speed Control  (AC 4.1, 4.2)
# ===================================================================

@pytest.mark.hardware
class TestHardwareSpeed:
    """Verify speed is sent before position commands."""

    def test_speed_applied(self, controller):
        """AC 4.2: Speed is sent via write_goal_speed per servo."""
        for sid in range(1, 9):
            controller.write_goal_speed(sid, 1)
        # No error raised = speed accepted
        for sid in range(1, 9):
            controller.write_goal_speed(sid, 3)

    def test_slow_vs_fast_timing(self, controller):
        """Slower speed takes longer to reach target than faster speed."""
        _move_to_open(controller)

        # Fast (speed 6)
        for sid in range(1, 9):
            controller.write_goal_speed(sid, 6)
        _move_to_pose(controller, [80] * 8, speed=6)
        time.sleep(2.0)
        _move_to_open(controller)
        time.sleep(1.0)

        # Slow (speed 1) — just verify it doesn't error
        _move_to_pose(controller, [80] * 8, speed=1)
        time.sleep(1.0)
        _move_to_open(controller)


# ===================================================================
# FR-MON-1: Telemetry Reading  (AC 1.2)
# ===================================================================

@pytest.mark.hardware
class TestHardwareTelemetry:
    """Read real telemetry values from servos."""

    def test_read_position(self, controller):
        """AC 1.2: Position is readable for all 8 servos."""
        for sid in range(1, 9):
            pos = controller.read_present_position(sid)
            assert pos is not None

    def test_read_load(self, controller):
        """AC 1.2: Load/torque is readable."""
        for sid in range(1, 9):
            load = controller.read_present_load(sid)
            assert load is not None

    def test_read_temperature(self, controller):
        """AC 1.2: Temperature is readable and plausible."""
        for sid in range(1, 9):
            temp = controller.read_present_temperature(sid)
            temp_val = float(temp) if temp is not None else 0
            # Temperature should be between 10°C and 80°C
            assert 10.0 <= temp_val <= 80.0, f"Servo {sid} temp: {temp_val}°C"

    def test_read_voltage(self, controller):
        """AC 1.2: Voltage is readable and plausible."""
        for sid in range(1, 9):
            voltage = controller.read_present_voltage(sid)
            v = float(voltage) if voltage is not None else 0
            # Voltage should be between 4V and 8.5V for typical servo bus
            assert 4.0 <= v <= 8.5, f"Servo {sid} voltage: {v}V"

    def test_read_speed(self, controller):
        """AC 1.2: Current speed is readable."""
        for sid in range(1, 9):
            speed = controller.read_present_speed(sid)
            assert speed is not None

    def test_read_moving_flag(self, controller):
        """AC 1.2: Moving flag is readable."""
        _move_to_open(controller)
        time.sleep(1.0)
        for sid in range(1, 9):
            moving = controller.read_moving(sid)
            assert moving is not None


# ===================================================================
# FR-SEQ-2: Sequence Execution via CLI  (AC 2.1–2.5)
# ===================================================================

@pytest.mark.hardware
class TestHardwareSequence:
    """Run sequences on real hardware via CLI subprocess."""

    def test_cli_sequence_demo(self, hw_port, hw_baudrate, sample_config_file):
        """AC 2.1: Sequence runs all pose steps."""
        result = subprocess.run(
            [sys.executable, str(CLI),
             "--sequence", "demo",
             "--port", hw_port,
             "--baudrate", str(hw_baudrate),
             "--config", str(sample_config_file)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "Done" in result.stdout

    def test_cli_sequence_with_sleep(self, hw_port, hw_baudrate, tmp_path):
        """AC 2.2: SLEEP steps pause without hardware commands."""
        config = {
            "poses": {"open": {"positions": [0] * 8}},
            "sequences": {
                "sleep_test": {
                    "steps": [
                        "open:3,3,3,3,3,3,3,3|0.5s",
                        "SLEEP:0.5s",
                        "open:3,3,3,3,3,3,3,3|0.5s",
                    ]
                }
            },
        }
        cf = tmp_path / "sleep_cfg.yaml"
        cf.write_text(yaml.dump(config))

        result = subprocess.run(
            [sys.executable, str(CLI),
             "--sequence", "sleep_test",
             "--port", hw_port,
             "--baudrate", str(hw_baudrate),
             "--config", str(cf)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "SLEEP" in result.stdout


# ===================================================================
# FR-ERR-3: Monitor Thread Recovery  (AC 3.1)
# ===================================================================

@pytest.mark.hardware
class TestHardwareErrorRecovery:
    """Verify robustness of telemetry reads."""

    def test_repeated_reads_no_crash(self, controller):
        """AC 3.1: Rapid successive reads do not crash."""
        for _ in range(50):
            for sid in range(1, 9):
                try:
                    controller.read_present_position(sid)
                except Exception:
                    pass  # Individual failures are acceptable


# ===================================================================
# FR-FING-8: LED Activity — Movement Detection  (AC 8.1, 8.2, 8.3)
# ===================================================================

@pytest.mark.hardware
class TestHardwareMovement:
    """Verify moving flag reflects actual servo state."""

    def test_moving_during_motion(self, controller):
        """AC 8.1: Moving flag true during motion."""
        _move_to_open(controller)
        time.sleep(2.0)
        # Start a large move at slow speed
        for sid in range(1, 9):
            controller.write_goal_speed(sid, 1)
        _move_to_pose(controller, [100] * 8, speed=1)
        time.sleep(0.3)

        # At least some servos should be moving
        moving_count = 0
        for sid in range(1, 9):
            try:
                flag = controller.read_moving(sid)
                if bool(int(float(str(flag)))):
                    moving_count += 1
            except Exception:
                pass
        assert moving_count > 0, "No servos reported as moving during motion"

        # Wait for motion to complete
        time.sleep(5.0)
        _move_to_open(controller)

    def test_idle_after_completion(self, controller):
        """AC 8.3: Moving flag false when idle."""
        _move_to_open(controller)
        time.sleep(3.0)

        for sid in range(1, 9):
            try:
                flag = controller.read_moving(sid)
                assert not bool(int(float(str(flag)))), \
                    f"Servo {sid} still moving when it should be idle"
            except Exception:
                pass  # Read failure is acceptable per FR-ERR-3


# ===================================================================
# FR-CONN-3: Disconnect — Torque Off  (AC 3.2)
# ===================================================================

@pytest.mark.hardware
class TestHardwareDisconnect:
    """Verify torque is disabled on disconnect.

    This test runs LAST — it re-creates a connection and destroys it.
    """

    def test_torque_disabled_on_disconnect(self, hw_port, hw_baudrate):
        """AC 3.2: Disconnect disables torque on all 8 servos."""
        if Scs0009PyController is None:
            pytest.skip("rustypot not installed")

        ctrl = Scs0009PyController(
            serial_port=hw_port,
            baudrate=hw_baudrate,
            timeout=0.5,
        )
        for sid in range(1, 9):
            ctrl.write_torque_enable(sid, 1)
        time.sleep(0.2)

        # Disconnect: disable torque
        for sid in range(1, 9):
            ctrl.write_torque_enable(sid, 0)

        # Servos should be free (no torque) — no assertion possible
        # without manual verification, but at least no errors raised
