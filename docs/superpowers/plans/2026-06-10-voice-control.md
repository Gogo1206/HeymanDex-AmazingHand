# Voice Control (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the AmazingHand's four poses (open / close / ok / victory) by spoken Chinese command, offline, via a push-to-talk standalone script.

**Architecture:** New `amazing_hand_audio.py` mirrors `amazing_hand_camera.py`. A pure `match_command(text)` maps recognized Chinese text to a pose name. Vosk (offline STT) turns held-key mic audio into text; the same `connect` / `load_config` / `apply_pose` backend from `amazing_hand_cmd` moves the hand. No LLM in Phase 1.

**Tech Stack:** Python, Vosk (offline zh STT), sounddevice (PortAudio mic), pynput (global key hold), stdlib `difflib` for fuzzy match, existing SCS0009 serial backend.

Spec: `docs/superpowers/specs/2026-06-10-voice-control-design.md`

---

## File Structure

- **Create `amazing_hand_audio.py`** — the whole Phase 1 feature: vocab, `match_command` (pure), `listen_once` (mic+Vosk), push-to-talk loop, `main()` + argparse. Mirrors the single-file shape of `amazing_hand_camera.py`.
- **Create `tests/test_audio.py`** — unit tests for `match_command` only (pure function; mic/Vosk/key handling are hardware/OS-dependent → manual verify).
- **Modify `requirements.txt`** — add `vosk`, `sounddevice`, `pynput`.
- **Models** — download Vosk small zh model into `models/` (not committed; gitignored alongside `models/hand_landmarker.task`).

Reused without modification (import only): `amazing_hand_cmd.connect`, `amazing_hand_cmd.load_config`, `amazing_hand_cmd.apply_pose`, `hand_logic.CONFIG_FILE`, `hand_logic.DEFAULT_BAUDRATE`, `hand_logic.default_serial_port`.

---

## Task 1: Pure command matcher (`match_command`)

The heart of recognition. No deps beyond stdlib, fully unit-testable. Build it first with TDD.

**Files:**
- Create: `amazing_hand_audio.py`
- Test: `tests/test_audio.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audio.py`:

```python
"""Unit tests for the pure command matcher in amazing_hand_audio.

Mic capture, Vosk, and pynput key handling are hardware/OS dependent and are
verified manually — only the pure match_command function is unit-tested here.
"""
from amazing_hand_audio import match_command


def test_primary_words_map_to_poses():
    assert match_command("张开") == "open"
    assert match_command("握拳") == "close"
    assert match_command("抓取") == "ok"
    assert match_command("胜利") == "victory"


def test_synonyms_map_to_poses():
    assert match_command("打开") == "open"
    assert match_command("抓紧") == "close"
    assert match_command("捏") == "ok"
    assert match_command("剪刀") == "victory"


def test_english_words_map_to_poses():
    assert match_command("open") == "open"
    assert match_command("OK") == "ok"
    assert match_command("Victory") == "victory"


def test_keyword_inside_a_sentence():
    assert match_command("帮我把手张开吧") == "open"
    assert match_command("现在握拳") == "close"


def test_empty_or_whitespace_is_rejected():
    assert match_command("") is None
    assert match_command("   ") is None


def test_unrelated_speech_is_rejected():
    assert match_command("今天天气不错") is None


def test_two_distinct_commands_in_one_utterance_is_rejected():
    # Phase 1 is single-command only; ambiguous multi-pose input must reject,
    # not guess. (Multi-command is a future phase.)
    assert match_command("先张开然后握拳") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_audio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'amazing_hand_audio'` (or `ImportError` for `match_command`).

- [ ] **Step 3: Write the minimal implementation**

Create `amazing_hand_audio.py` with exactly this (header + vocab + matcher; the rest is added in later tasks):

```python
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
    "ok":      ["抓取", "抓", "捏", "ok", "好的"],
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_audio.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add amazing_hand_audio.py tests/test_audio.py
git commit -m "feat: pure Chinese command matcher for voice control"
```

---

## Task 2: Dependencies and Vosk model

Install runtime deps and download the offline Chinese model. No code; no unit test (environment setup). Verified by import + model-on-disk checks.

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add deps to `requirements.txt`**

Append these three lines to `requirements.txt` (keep existing contents):

```
vosk
sounddevice
pynput
```

- [ ] **Step 2: Install them**

Run: `pip install vosk sounddevice pynput`
Expected: installs succeed. On macOS, `sounddevice` pulls in PortAudio via its wheel; if it complains about PortAudio, run `brew install portaudio` then retry.

- [ ] **Step 3: Download the Vosk small Chinese model into `models/`**

Run:

```bash
cd models
curl -L -O https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
unzip -q vosk-model-small-cn-0.22.zip
rm vosk-model-small-cn-0.22.zip
cd ..
```

Expected: directory `models/vosk-model-small-cn-0.22/` exists.

- [ ] **Step 4: Verify import + model path**

Run:

```bash
python -c "import vosk, sounddevice, pynput; from pathlib import Path; assert Path('models/vosk-model-small-cn-0.22').is_dir(); print('deps + model OK')"
```

Expected: prints `deps + model OK`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "build: add vosk/sounddevice/pynput deps for voice control"
```

(The model directory under `models/` is gitignored — do not commit it.)

---

## Task 3: Offline speech-to-text (`VoiceListener`)

Capture mic audio into a buffer and run Vosk on it. Hardware-dependent → manual verification.

**Files:**
- Modify: `amazing_hand_audio.py`

- [ ] **Step 1: Add imports and the Vosk/mic config**

In `amazing_hand_audio.py`, replace the existing top imports block:

```python
from __future__ import annotations

import argparse
import difflib
import sys
```

with:

```python
from __future__ import annotations

import argparse
import difflib
import json
import queue
import sys
from pathlib import Path
```

Then, immediately after the `FUZZY_THRESHOLD = 0.6` line, add:

```python
MODEL_PATH = Path(__file__).resolve().parent / "models" / "vosk-model-small-cn-0.22"
SAMPLE_RATE = 16000
```

- [ ] **Step 2: Add the recorder/recognizer (after `match_command`)**

Append this class to `amazing_hand_audio.py`:

```python
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
```

- [ ] **Step 3: Manual verification (mic required)**

Run this throwaway check (records ~3 s, prints what Vosk heard):

```bash
python -c "
import time
from amazing_hand_audio import VoiceListener, match_command
vl = VoiceListener()
print('Speak a command now (recording 3s)...')
vl.start(); time.sleep(3); text = vl.stop_and_recognize(); vl.close()
print('heard:', repr(text), '-> pose:', match_command(text))
"
```

Expected: speaking "张开" prints something like `heard: '张 开' -> pose: open`. (Vosk inserts spaces between tokens; `_normalize` strips them.)

- [ ] **Step 4: Commit**

```bash
git add amazing_hand_audio.py
git commit -m "feat: offline Vosk mic capture for voice control"
```

---

## Task 4: Push-to-talk loop, wiring, and CLI (`main`)

Tie it together: hold SPACE → record → recognize → match → `apply_pose`. Reuses the camera script's argparse conventions and `--no-hand` dry-run.

**Files:**
- Modify: `amazing_hand_audio.py`

- [ ] **Step 1: Add the backend imports**

Add these two import lines at the end of the top imports block in `amazing_hand_audio.py` (just below `from pathlib import Path`):

```python
from hand_logic import CONFIG_FILE, DEFAULT_BAUDRATE, default_serial_port
from amazing_hand_cmd import connect, load_config, apply_pose
```

- [ ] **Step 2: Add `run()` and `main()`**

Append to `amazing_hand_audio.py`:

```python
def run(args) -> None:
    from pynput import keyboard

    config = load_config(CONFIG_FILE)
    ctrl = None if args.no_hand else connect(args.serial_port, args.baudrate)

    listener = VoiceListener()
    speeds = [args.speed] * 8

    def fire(text: str) -> None:
        pose = match_command(text)
        if pose is None:
            print(f"没听清 (heard {text!r}) — no action")
            return
        positions = config["poses"][pose]["positions"]
        if ctrl is not None:
            try:
                apply_pose(ctrl, positions, speeds)
            except Exception as exc:  # noqa: BLE001
                print(f"send error: {exc}")
        print(f"SENT {text!r} → pose {pose}")

    def on_press(key) -> None:  # noqa: ANN001
        if key == keyboard.Key.space and not listener.recording:
            print("● recording… (release SPACE to send)")
            listener.start()

    def on_release(key) -> bool | None:  # noqa: ANN001
        if key == keyboard.Key.esc:
            return False  # stop the listener → exit
        if key == keyboard.Key.space and listener.recording:
            text = listener.stop_and_recognize()
            fire(text)
        return None

    print("Voice control running. Hold SPACE to talk, release to send. ESC to quit.")
    try:
        with keyboard.Listener(on_press=on_press, on_release=on_release) as kl:
            kl.join()
    finally:
        listener.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Voice (Chinese) hand control")
    ap.add_argument("--serial-port", default=default_serial_port())
    ap.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    ap.add_argument("--speed", type=int, default=3, help="servo speed 1-6")
    ap.add_argument("--no-hand", action="store_true",
                    help="recognize only; do not open the serial connection")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Re-run the unit tests (guard against regressions)**

Run: `pytest tests/test_audio.py -v`
Expected: PASS (still 7 tests; the new code did not touch `match_command`).

- [ ] **Step 4: Manual verification — dry run (no hardware)**

Run: `python amazing_hand_audio.py --no-hand`
Then hold SPACE, say "张开", release.
Expected: prints `● recording…` then `SENT '张 开' → pose open`. Say something random → `没听清 … no action`. Press ESC to quit.

Note (macOS): the terminal/app running Python needs Accessibility + Input Monitoring permission for `pynput` to see the SPACE key (System Settings → Privacy & Security). Grant it if key presses aren't detected.

- [ ] **Step 5: Manual verification — with hand (hardware)**

Run: `python amazing_hand_audio.py`
Hold SPACE, say each of "张开 / 握拳 / 抓取 / 胜利", release after each.
Expected: hand moves to open / close / ok / victory respectively; `SENT … → pose …` printed each time.

- [ ] **Step 6: Commit**

```bash
git add amazing_hand_audio.py
git commit -m "feat: push-to-talk voice control loop and CLI"
```

---

## Task 5: Document the script

Add a short usage note so the script is discoverable next to the camera one.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Voice control section to `README.md`**

Find the section that documents `amazing_hand_camera.py` (camera gesture control). Immediately after it, add:

````markdown
### Voice control (Chinese, offline)

Hold **SPACE**, speak a command, release — the hand moves. Offline (Vosk), no LLM.

| say (Chinese)      | pose    |
|--------------------|---------|
| 张开 / 打开        | open    |
| 握拳 / 抓紧        | close   |
| 抓取 / 捏          | ok      |
| 胜利 / 剪刀        | victory |

```bash
python amazing_hand_audio.py            # drive the hand
python amazing_hand_audio.py --no-hand  # recognize only, no serial
```

One-time setup: `pip install vosk sounddevice pynput` and download the Vosk
small Chinese model into `models/vosk-model-small-cn-0.22/` (see
`docs/superpowers/plans/2026-06-10-voice-control.md`, Task 2). On macOS, grant
the terminal Input Monitoring permission so the SPACE key is detected.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README usage for voice control script"
```

---

## Done — Phase 1 complete

When all tasks pass: speaking the four commands moves the hand, unrecognized speech is safely ignored, and `match_command` is unit-tested. Stop here and verify with the user before designing Phase 2 (LLM fallback) or Phase 3 (multi-command sequences).
