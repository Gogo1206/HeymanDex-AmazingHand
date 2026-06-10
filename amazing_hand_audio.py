#!/usr/bin/env python3
"""
AmazingHand voice control (Phase 1).

Push-to-talk: hold SPACE, speak a Chinese command, release. Offline STT (Vosk)
turns it into text; match_command() maps the text to one of four poses and the
robot hand moves:

    张开 / 打开    → pose "open"     (A)
    握拳 / 抓紧    → pose "close"    (C)
    抓取 / 捏      → pose "ok"       (B)
    胜利 / 剪刀    → pose "victory"  (D)

No internet, no LLM. Low-confidence / ambiguous speech does nothing (it never
guesses a pose).

Run:
    python amazing_hand_audio.py                # drive the hand
    python amazing_hand_audio.py --no-hand      # recognize only (no serial)
"""
from __future__ import annotations

import argparse
import difflib
import json
import queue
import sys
from pathlib import Path

# pose name → spoken keywords (primary first, then synonyms). Keys must match
# pose names in data/hand_config.yaml: open / close / ok / victory.
POSE_VOCAB: dict[str, list[str]] = {
    "open":    ["张开", "打开", "张手", "摊开", "open"],
    "close":   ["握拳", "握", "攥", "拳", "抓紧", "close"],
    "ok":      ["抓取", "捏", "ok", "好的"],
    "victory": ["胜利", "胜利手势", "剪刀", "耶", "victory"],
}

# Minimum SequenceMatcher ratio for the fuzzy fallback to accept a match.
FUZZY_THRESHOLD = 0.6

MODEL_PATH = Path(__file__).resolve().parent / "models" / "vosk-model-small-cn-0.22"
SAMPLE_RATE = 16000

_PUNCT = " 　,，.。!！?？、~"


def _normalize(text: str) -> str:
    """Lowercase and strip spaces/punctuation so matching is forgiving."""
    text = text.lower()
    for ch in _PUNCT:
        text = text.replace(ch, "")
    return text


def match_command(text: str) -> str | None:
    """Map recognized Chinese (or English) text to a pose name, or None.

    Pure function — no mic, no hardware. Returns one of
    ``"open" | "close" | "ok" | "victory"`` or ``None`` when the input is empty,
    unrecognized, or ambiguous (matches two different poses).
    """
    if not text:
        return None
    norm = _normalize(text)
    if not norm:
        return None

    # 1. Substring keyword hit. Collect the distinct poses that matched.
    hits = {
        pose
        for pose, keywords in POSE_VOCAB.items()
        for kw in keywords
        if _normalize(kw) in norm
    }
    if len(hits) == 1:
        return hits.pop()
    if len(hits) > 1:
        return None  # ambiguous: two different poses named → reject (Phase 1)

    # 2. Fuzzy fallback for near-misses (mishearings) on short utterances.
    best_pose: str | None = None
    best_score = 0.0
    for pose, keywords in POSE_VOCAB.items():
        for kw in keywords:
            score = difflib.SequenceMatcher(None, norm, _normalize(kw)).ratio()
            if score > best_score:
                best_pose, best_score = pose, score
    return best_pose if best_score >= FUZZY_THRESHOLD else None


class VoiceListener:
    """Push-to-talk mic capture + offline Vosk recognition.

    A background sounddevice stream continuously pushes int16 frames into a
    queue. While ``recording`` is True the frames are kept; on stop they are fed
    to a fresh Vosk recognizer and the final text is returned.
    """

    def __init__(self) -> None:
        import sounddevice as sd  # local import: optional dep, only for live use
        from vosk import Model

        if not MODEL_PATH.is_dir():
            print(f"ERROR: Vosk model not found at {MODEL_PATH}")
            print("Download it (see plan Task 2) into models/.")
            sys.exit(1)

        self._model = Model(str(MODEL_PATH))
        self._frames: queue.Queue[bytes] = queue.Queue()
        self.recording = False
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=self._on_audio,
        )
        self._stream.start()

    def _on_audio(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if self.recording:
            self._frames.put(bytes(indata))

    def start(self) -> None:
        """Begin a fresh recording (drops any stale buffered frames)."""
        while not self._frames.empty():
            self._frames.get_nowait()
        self.recording = True

    def stop_and_recognize(self) -> str:
        """Stop recording and return the recognized text (possibly empty)."""
        from vosk import KaldiRecognizer

        self.recording = False
        rec = KaldiRecognizer(self._model, SAMPLE_RATE)
        while not self._frames.empty():
            rec.AcceptWaveform(self._frames.get_nowait())
        result = json.loads(rec.FinalResult())
        return result.get("text", "")

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
