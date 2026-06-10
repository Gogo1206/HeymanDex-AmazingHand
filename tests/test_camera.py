"""Camera-free unit tests for the gesture classifier."""
import numpy as np
import pytest

from amazing_hand.amazing_hand_camera import classify, pairs_for_handedness
from amazing_hand.hand_logic import SERVO_PAIRS_LEFT, SERVO_PAIRS_RIGHT

# MediaPipe landmark indices used by the classifier
WRIST, THUMB_TIP, THUMB_IP, MIDDLE_MCP = 0, 4, 3, 9
RING_MCP, PINKY_MCP = 13, 17
TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIPS = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}


def _hand(extended: dict, pinch: bool = False, thumb_out: bool = False):
    """Build a synthetic 21×3 landmark array.

    y grows downward. PIP joints sit at y=0.5; an extended finger puts its tip
    above (y=0.2), a folded finger below (y=0.8). Wrist at y=1.0, middle-MCP at
    y=0.5 gives a hand size of ~0.5 so the pinch threshold (0.4·size=0.2) is sane.

    Ring/pinky knuckles sit just right of palm center. The thumb is on the left
    (thumb side). ``thumb_out`` extends it sideways-left, away from the fingers;
    otherwise it folds across the palm and rests on the ring/pinky knuckles (the
    real victory pose). ``pinch`` moves the tip onto the index tip regardless.
    """
    pts = np.zeros((21, 3))
    pts[WRIST] = [0.5, 1.0, 0]
    pts[MIDDLE_MCP] = [0.5, 0.5, 0]
    for name, tip in TIPS.items():
        pip = PIPS[name]
        pts[pip] = [0.5, 0.5, 0]
        pts[tip] = [0.5, 0.2 if extended[name] else 0.8, 0]
    pts[RING_MCP] = [0.55, 0.5, 0]
    pts[PINKY_MCP] = [0.6, 0.5, 0]
    pts[THUMB_IP] = [0.4, 0.6, 0]
    idx_tip = pts[TIPS["index"]]
    if pinch:
        pts[THUMB_TIP] = idx_tip + [0.02, 0.02, 0]
    elif thumb_out:
        pts[THUMB_TIP] = [0.05, 0.4, 0]   # extended out to the side
    else:
        pts[THUMB_TIP] = [0.55, 0.55, 0]  # folded across, on ring/pinky knuckles
    return pts


ALL = {"index": True, "middle": True, "ring": True, "pinky": True}
NONE = {"index": False, "middle": False, "ring": False, "pinky": False}
VICT = {"index": True, "middle": True, "ring": False, "pinky": False}


def test_open():
    assert classify(_hand(ALL)) == "open"


def test_fist():
    assert classify(_hand(NONE)) == "fist"


def test_victory():
    assert classify(_hand(VICT)) == "victory"


def test_victory_thumb_out_is_not_victory():
    # index+middle out but thumb also sticking out → not victory
    assert classify(_hand(VICT, thumb_out=True)) != "victory"


def test_ok_pinch():
    # OK 👌 = pinch with middle/ring/pinky open
    assert classify(_hand(ALL, pinch=True)) == "ok"


def test_pinch_without_open_fingers_is_not_ok():
    # thumb+index pinched but other fingers folded → not OK
    folded_others = {"index": True, "middle": False, "ring": False, "pinky": False}
    assert classify(_hand(folded_others, pinch=True)) != "ok"


def test_ambiguous_returns_none():
    # only ring extended → not any defined gesture
    odd = {"index": False, "middle": False, "ring": True, "pinky": False}
    assert classify(_hand(odd)) is None


def test_short_array_none():
    assert classify(np.zeros((5, 3))) is None


def _rotate(pts, deg, center=(0.5, 1.0)):
    """Rotate all landmarks about a center (defaults to the wrist)."""
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    out = pts.copy()
    cx, cy = center
    for i in range(len(out)):
        x, y = out[i, 0] - cx, out[i, 1] - cy
        out[i, 0] = cx + x * c - y * s
        out[i, 1] = cy + x * s + y * c
    return out


@pytest.mark.parametrize("deg", [0, 45, 90, 135, 180, -45, -90])
def test_orientation_invariant(deg):
    # same gesture must classify identically at any hand rotation
    assert classify(_rotate(_hand(ALL), deg)) == "open"
    assert classify(_rotate(_hand(NONE), deg)) == "fist"
    assert classify(_rotate(_hand(VICT), deg)) == "victory"
    assert classify(_rotate(_hand(ALL, pinch=True), deg)) == "ok"


# ---------------------------------------------------------------------------
# Two-hand routing: handedness → servo-pair set
# ---------------------------------------------------------------------------

def test_left_pairs_are_right_plus_ten():
    # left hand servos are the right-hand IDs offset by +10, preserving the
    # odd/even parity that angle_rad() relies on for inversion
    assert SERVO_PAIRS_LEFT == [(s1 + 10, s2 + 10) for s1, s2 in SERVO_PAIRS_RIGHT]
    for (rs1, rs2), (ls1, ls2) in zip(SERVO_PAIRS_RIGHT, SERVO_PAIRS_LEFT):
        assert ls1 % 2 == rs1 % 2
        assert ls2 % 2 == rs2 % 2


def test_left_servo_ids_are_11_to_18():
    ids = sorted(sid for pair in SERVO_PAIRS_LEFT for sid in pair)
    assert ids == list(range(11, 19))


def test_handedness_routes_mirrored_default():
    # mirrored frame: MediaPipe 'Right' is the operator's left hand
    assert pairs_for_handedness("Right") == SERVO_PAIRS_LEFT
    assert pairs_for_handedness("Left") == SERVO_PAIRS_RIGHT


def test_swap_inverts_routing():
    assert pairs_for_handedness("Right", swap=True) == SERVO_PAIRS_RIGHT
    assert pairs_for_handedness("Left", swap=True) == SERVO_PAIRS_LEFT
