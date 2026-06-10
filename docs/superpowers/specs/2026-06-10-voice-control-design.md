# Voice Control — Design Spec

**Date:** 2026-06-10
**Status:** Approved (Phase 1)
**Author:** brainstormed with Claude

## Goal

Drive the AmazingHand's four existing poses by spoken Chinese command,
offline, with low latency. Mirror the architecture already used by
`amazing_hand_camera.py` (recognizer front-end → shared `apply_pose` backend).

## Phased Rollout

The feature ships in stages. Each stage must be working and user-verified
before the next is designed.

- **Phase 1 (this spec):** offline STT (Vosk) + fuzzy keyword match → one of
  four poses. Push-to-talk (hold key). Standalone script.
- **Phase 2 (future, not yet designed):** optional local-LLM intent layer as a
  fallback for utterances fuzzy match can't resolve.
- **Phase 3 (future, not yet designed):** multi-command in one utterance
  (e.g. "先张开然后握拳" → ordered sequence), enabled by the LLM layer.

This document covers **Phase 1 only**. Phases 2–3 are recorded for context so
Phase 1 boundaries (pure `match_command`, swappable recognizer) leave room for
them.

## Decisions (locked)

| Decision | Choice | Why |
|----------|--------|-----|
| STT engine | Vosk small zh | Lightweight (~50MB), streaming, low latency, offline, enough for fixed words |
| Trigger | Push-to-talk, hold key | Zero false triggers, deterministic, simplest to test each stage |
| Location | Standalone `amazing_hand_audio.py` | Matches camera-script pattern, isolated, no GUI coupling yet |
| Recognition | Fuzzy keyword match (no LLM) | 4 fixed commands — string/edit-distance match beats LLM on latency, cost, offline |
| Key capture | `pynput` global SPACE | Works on macOS without terminal raw mode; `keyboard` lib needs root |

## Architecture / Data Flow

```
hold SPACE ─► record mic frames (16kHz mono, sounddevice)
release    ─► feed frames to Vosk KaldiRecognizer ─► zh text
text       ─► normalize ─► match_command() ─► pose name | None
pose       ─► apply_pose(ctrl, positions, speeds)   # reused from amazing_hand_cmd
```

Backend reuse: `connect`, `load_config`, `apply_pose` from `amazing_hand_cmd`
— identical to how `amazing_hand_camera.py` sends a pose. The voice script only
adds a new recognizer front-end.

## Modules / Interfaces

Each unit has one purpose and is understandable/testable in isolation.

- **`match_command(text: str) -> str | None`** — pure function. Chinese text →
  pose name (`"open" | "close" | "ok" | "victory"`) or `None`. No mic, no
  hardware. The heart of recognition; fully unit-testable. Mirrors the pure
  `classify()` in the camera script.
- **`listen_once() -> str`** — capture mic frames while key held, run Vosk,
  return recognized text. Hardware-touching; manual testing only.
- **key-hold input** — `pynput` listener: SPACE press starts capture, release
  ends it and triggers recognition.
- **`main()`** — argparse + glue loop. Reuses camera-script conventions
  (`--no-hand`, `--serial-port`, `--baudrate`, `--speed`).

## Vocabulary (match_command)

| pose | primary | synonyms (fuzzy) |
|------|---------|------------------|
| open | 张开 | 打开 / 张手 / 摊开 / open |
| close | 握拳 | 握 / 攥 / 拳 / 抓紧 / close |
| ok | 抓取 | 抓 / 捏 / OK / 好的 |
| victory | 胜利 | 胜利手势 / 剪刀 / 耶 / victory |

Match strategy:
1. Keyword / substring hit against primary + synonyms → that pose.
2. Else edit-distance (`rapidfuzz`, fallback stdlib `difflib`) above a
   confidence threshold → best pose.
3. Tie between two poses, or all below threshold → `None` (reject).

## Error Handling

- **Reject path:** `match_command` returns `None` → no movement, print "没听清"
  (or similar), keep listening. Never fire a random pose on low confidence —
  a wrong move on the robot is worse than no move.
- Mic and serial errors are caught per-iteration; they log and continue, they
  do not crash the loop.
- `--no-hand` dry-run: print the recognized pose, skip the serial connection
  (mirrors camera's vision-only mode) — lets STT + matching be verified with no
  hardware.

## Testing

- **`match_command`** — unit tests: sample Chinese command strings and synonyms
  assert the right pose; junk/ambiguous strings assert `None`. This mirrors the
  existing pure-function tests for the camera `classify()`.
- Mic + Vosk capture and `pynput` key handling are hardware/OS-dependent →
  manual verification, not unit-tested.

## New Dependencies

- `vosk`, `sounddevice`, `pynput`, `rapidfuzz` (or stdlib `difflib`)
- Vosk small Chinese model (~50MB) downloaded into `models/` (alongside the
  existing `models/hand_landmarker.task`).

## Out of Scope (Phase 1)

- LLM intent classification (Phase 2)
- Multi-command sequences in one utterance (Phase 3)
- Always-listening / VAD / wake word (push-to-talk chosen instead)
- GUI integration (standalone script chosen instead)
