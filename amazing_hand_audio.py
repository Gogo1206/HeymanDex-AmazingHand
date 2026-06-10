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
import sys

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
