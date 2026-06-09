"""Camera-free unit tests for the gesture classifier."""
import numpy as np
import pytest

from amazing_hand_camera import classify

# MediaPipe landmark indices used by the classifier
WRIST, THUMB_TIP, MIDDLE_MCP = 0, 4, 9
TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIPS = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}


def _hand(extended: dict, pinch: bool = False):
    """Build a synthetic 21×3 landmark array.

    y grows downward. PIP joints sit at y=0.5; an extended finger puts its tip
    above (y=0.2), a folded finger below (y=0.8). Wrist at y=1.0, middle-MCP at
    y=0.5 gives a hand size of ~0.5 so the pinch threshold (0.4·size=0.2) is sane.
    """
    pts = np.zeros((21, 3))
    pts[WRIST] = [0.5, 1.0, 0]
    pts[MIDDLE_MCP] = [0.5, 0.5, 0]
    for name, tip in TIPS.items():
        pip = PIPS[name]
        pts[pip] = [0.5, 0.5, 0]
        pts[tip] = [0.5, 0.2 if extended[name] else 0.8, 0]
    # thumb tip: far from index tip unless pinching
    idx_tip = pts[TIPS["index"]]
    pts[THUMB_TIP] = (idx_tip + [0.02, 0.02, 0]) if pinch else [0.9, 0.9, 0]
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


def test_ok_pinch():
    # pinch wins regardless of other fingers
    assert classify(_hand(ALL, pinch=True)) == "ok"


def test_ambiguous_returns_none():
    # only ring extended → not any defined gesture
    odd = {"index": False, "middle": False, "ring": True, "pinky": False}
    assert classify(_hand(odd)) is None


def test_short_array_none():
    assert classify(np.zeros((5, 3))) is None
