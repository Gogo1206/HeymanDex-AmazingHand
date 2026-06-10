#!/usr/bin/env python3
"""
AmazingHand camera gesture control.

Watches a webcam, recognizes one of four hand gestures with MediaPipe Hands
(Tasks API), and drives the robot hand to mirror it:

    open palm 🖐  → pose "open"     (A)
    pinch / OK 🤏 → pose "ok"       (B)
    fist ✊       → pose "close"    (C)
    victory ✌️    → pose "victory"  (D)

Hold a gesture steady for ~0.6 s to send it (debounced); it won't resend until
the gesture changes.

Run:
    python amazing_hand_camera.py                # drive the hand
    python amazing_hand_camera.py --no-hand      # vision only (no serial)
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

from amazing_hand.hand_logic import (
    CONFIG_FILE, DEFAULT_BAUDRATE, default_serial_port,
    SERVO_PAIRS_LEFT, SERVO_PAIRS_RIGHT,
)
from amazing_hand.amazing_hand_cmd import connect, load_config, apply_pose

MODEL_PATH = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"

# gesture id → (pose name, display label, BGR color)
GESTURES = {
    "open":    ("open",    "OPEN 四指张开", (247, 195, 79)),
    "ok":      ("ok",      "OK 抓取",       (101, 138, 255)),
    "fist":    ("close",   "FIST 握拳",     (200, 104, 186)),
    "victory": ("victory", "VICTORY 胜利",  (132, 199, 129)),
}

# MediaPipe hand landmark indices
WRIST = 0
THUMB_TIP = 4
THUMB_IP = 3
MIDDLE_MCP = 9
RING_MCP = 13
PINKY_MCP = 17
TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIPS = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}


def _dist(a, b) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def pairs_for_handedness(label: str, swap: bool = False):
    """Map a MediaPipe handedness label ('Left'/'Right') to a servo-pair set.

    With the mirrored frame this setup uses, MediaPipe's 'Right' label is the
    operator's left hand, so by default 'Right' → left hand (servo IDs 11-18)
    and 'Left' → right hand (IDs 1-8). Pass ``swap=True`` to invert this if a
    different camera/mirror setup labels the hands the other way.
    """
    is_left = (label == "Right")
    if swap:
        is_left = not is_left
    return SERVO_PAIRS_LEFT if is_left else SERVO_PAIRS_RIGHT


def classify(pts) -> str | None:
    """Classify a 21×(x,y[,z]) landmark array into a gesture id, or None.

    Pure function — no camera or hardware. ``pts`` is array-like shape (21, >=2)
    with normalized image coordinates (x right, y down).
    """
    pts = np.asarray(pts, dtype=float)
    if pts.shape[0] < 21:
        return None

    hand = _dist(pts[WRIST], pts[MIDDLE_MCP]) or 1e-6

    def extended(name: str) -> bool:
        # Orientation-invariant: an extended finger's tip is farther from the
        # wrist than its PIP joint; a folded finger curls the tip back toward
        # the palm. Uses radial distance, so it holds for any hand rotation
        # (pointing up/down/sideways) unlike an image-y comparison.
        return _dist(pts[TIPS[name]], pts[WRIST]) > _dist(pts[PIPS[name]], pts[WRIST])

    index, middle = extended("index"), extended("middle")
    ring, pinky = extended("ring"), extended("pinky")

    # Thumb tucked-in detection (for victory). In a real victory the thumb folds
    # across the palm and rests on the curled ring/pinky, so the radial rule
    # ("tip farther from wrist than IP") wrongly reads it as extended. Treat the
    # thumb as tucked if EITHER it is radially folded OR its tip lies near the
    # ring/pinky knuckles (i.e. resting across them). Both use hand-size scaling
    # so they hold at any orientation.
    radial_in = _dist(pts[THUMB_TIP], pts[WRIST]) <= _dist(pts[THUMB_IP], pts[WRIST])
    across = min(_dist(pts[THUMB_TIP], pts[RING_MCP]),
                 _dist(pts[THUMB_TIP], pts[PINKY_MCP])) < 0.9 * hand
    thumb_in = radial_in or across

    pinch = _dist(pts[THUMB_TIP], pts[TIPS["index"]]) < 0.4 * hand

    # OK 👌: thumb+index pinched AND the other three fingers held open
    if pinch and middle and ring and pinky:
        return "ok"
    # Victory ✌️: index + middle out, ring + pinky folded, thumb tucked in
    if index and middle and not ring and not pinky and thumb_in:
        return "victory"
    if index and middle and ring and pinky:
        return "open"
    if not (index or middle or ring or pinky):
        return "fist"
    return None


# ---------------------------------------------------------------------------
# Live capture (imports cv2/mediapipe lazily so classify() stays testable)
# ---------------------------------------------------------------------------

def _make_landmarker():
    from mediapipe.tasks.python.core.base_options import BaseOptions
    from mediapipe.tasks.python.vision import (
        HandLandmarker, HandLandmarkerOptions, RunningMode,
    )
    if not MODEL_PATH.exists():
        print(f"ERROR: model not found at {MODEL_PATH}\n"
              f"Download: curl -sSL -o {MODEL_PATH} "
              f"https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
              f"hand_landmarker/float16/1/hand_landmarker.task")
        sys.exit(1)
    opts = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.7,
        min_tracking_confidence=0.6,
    )
    return HandLandmarker.create_from_options(opts)


def run(args) -> None:
    import cv2
    import mediapipe as mp

    # hardware — enable both hands' servos on the shared bus (right 1-8, left 11-18)
    ctrl = None
    config = load_config(CONFIG_FILE)
    if not args.no_hand:
        ctrl = connect(args.serial_port, args.baudrate,
                       servo_ids=list(range(1, 9)) + list(range(11, 19)))

    landmarker = _make_landmarker()
    cap = cv2.VideoCapture(args.camera_index)
    if not cap.isOpened():
        print(f"ERROR: cannot open camera index {args.camera_index}")
        sys.exit(1)

    # Independent debounce/last-sent state per physical hand ("L" / "R")
    def _new_state():
        return {"stable": deque(maxlen=args.hold_frames), "last_sent": None, "flash": 0.0}
    sides = {"L": _new_state(), "R": _new_state()}

    prev_t = time.time()
    print("Camera gesture control running. Press q or ESC to quit.")
    if args.swap_hands:
        print("(--swap-hands active: handedness labels inverted)")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)  # mirror
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts = int(time.time() * 1000)
            result = landmarker.detect_for_video(mp_img, ts)

            seen = set()
            current = {"L": None, "R": None}  # gesture shown in HUD this frame
            if result.hand_landmarks:
                for i, lms in enumerate(result.hand_landmarks):
                    label = result.handedness[i][0].category_name
                    pairs = pairs_for_handedness(label, args.swap_hands)
                    side = "L" if pairs is SERVO_PAIRS_LEFT else "R"
                    seen.add(side)
                    pts = np.array([[lm.x, lm.y, lm.z] for lm in lms])
                    gesture = classify(pts)
                    current[side] = gesture
                    _draw_landmarks(cv2, frame, lms)

                    st = sides[side]
                    st["stable"].append(gesture)
                    confirmed = (
                        gesture is not None
                        and len(st["stable"]) == st["stable"].maxlen
                        and all(g == gesture for g in st["stable"])
                    )
                    if confirmed and gesture != st["last_sent"]:
                        pose = GESTURES[gesture][0]
                        positions = config["poses"][pose]["positions"]
                        if ctrl is not None:
                            try:
                                apply_pose(ctrl, positions, [args.speed] * 8,
                                           servo_pairs=pairs)
                            except Exception as exc:  # noqa: BLE001
                                print(f"send error: {exc}")
                        print(f"SENT [{side}] {gesture} → pose {pose}")
                        st["last_sent"] = gesture
                        st["flash"] = time.time()
                    elif gesture is None:
                        st["last_sent"] = None  # leaving a gesture re-arms it

            # hands that left the frame this round re-arm and clear their buffer
            for side in ("L", "R"):
                if side not in seen:
                    sides[side]["stable"].append(None)
                    sides[side]["last_sent"] = None

            now = time.time()
            fps = 1.0 / max(now - prev_t, 1e-6)
            prev_t = now
            _draw_hud(cv2, frame, current, sides, fps, args.no_hand)

            cv2.imshow("AmazingHand 摄像头手势控制", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        landmarker.close()


def _draw_landmarks(cv2, frame, lms):
    h, w = frame.shape[:2]
    for lm in lms:
        cv2.circle(frame, (int(lm.x * w), int(lm.y * h)), 3, (255, 255, 255), -1)


def _draw_hud(cv2, frame, current, sides, fps, no_hand):
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 60), (26, 21, 18), -1)

    # one label per physical hand, left-panel "L", right-panel "R"
    for col, side, name in ((0, "L", "LEFT 11-18"), (1, "R", "RIGHT 1-8")):
        gesture = current.get(side)
        label = GESTURES[gesture][1] if gesture else "—"
        color = GESTURES[gesture][2] if gesture else (120, 120, 120)
        x = 16 + col * (w // 2)
        cv2.putText(frame, f"{name}: {label}", (x, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if time.time() - sides[side]["flash"] < 0.6:
            cv2.putText(frame, "SENT", (x, 52),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 220, 80), 2)

    cv2.putText(frame, f"{fps:4.0f} fps", (w - 110, h - 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (122, 106, 92), 1)
    if no_hand:
        cv2.putText(frame, "VISION ONLY (--no-hand)", (16, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (122, 106, 92), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Camera hand-gesture control")
    ap.add_argument("--camera-index", type=int, default=0)
    ap.add_argument("--serial-port", default=default_serial_port())
    ap.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    ap.add_argument("--speed", type=int, default=3, help="servo speed 1-6")
    ap.add_argument("--hold-frames", type=int, default=12,
                    help="consecutive frames a gesture must hold before sending")
    ap.add_argument("--no-hand", action="store_true",
                    help="vision only; do not open the serial connection")
    ap.add_argument("--swap-hands", action="store_true",
                    help="invert left/right handedness if the camera labels "
                         "your hands backwards")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
