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

from hand_logic import CONFIG_FILE, DEFAULT_BAUDRATE, default_serial_port
from amazing_hand_cmd import connect, load_config, apply_pose

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

# Drop .wav recordings here to test recognition without a live mic. Name each
# file after the pose it should trigger (e.g. open_1.wav, close_loud.wav) so the
# test suite can check it — see tests/test_audio_files.py.
AUDIO_SAMPLES_DIR = Path(__file__).resolve().parent / "audio_samples"

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


def _read_wav_16k_mono(path: Path) -> bytes:
    """Read a 16-bit PCM WAV and return int16 bytes as 16 kHz mono.

    Stereo is downmixed; any sample rate is linearly resampled to SAMPLE_RATE,
    so recordings don't have to be pre-converted. Raises ValueError on non
    16-bit-PCM input (which Vosk can't consume).
    """
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError(
                f"{path.name}: need 16-bit PCM WAV "
                f"(got sample width {wf.getsampwidth() * 8}-bit)"
            )
        channels = wf.getnchannels()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if rate != SAMPLE_RATE:
        n_out = int(round(len(audio) * SAMPLE_RATE / rate))
        x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        audio = np.interp(x_new, x_old, audio).astype(np.int16)
    return audio.tobytes()


def recognize_file(path, model=None) -> str:
    """Recognize a WAV file offline with Vosk and return the text.

    ``model`` lets a caller reuse one loaded Vosk Model across many files (it is
    expensive to construct). When omitted, the model at MODEL_PATH is loaded.
    """
    from vosk import KaldiRecognizer, Model

    if model is None:
        if not MODEL_PATH.is_dir():
            raise FileNotFoundError(f"Vosk model not found at {MODEL_PATH}")
        model = Model(str(MODEL_PATH))
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    rec.AcceptWaveform(_read_wav_16k_mono(Path(path)))
    return json.loads(rec.FinalResult()).get("text", "")


def _audio_mode(path: Path) -> None:
    """Recognize a WAV file (or every .wav in a directory) and print the match.

    Recognition only — never opens the serial port. Used to test the
    speech→pose pipeline from recordings instead of a live mic.
    """
    from vosk import Model

    if not MODEL_PATH.is_dir():
        print(f"ERROR: Vosk model not found at {MODEL_PATH}")
        sys.exit(1)
    if not path.exists():
        print(f"ERROR: no such file or directory: {path}")
        sys.exit(1)

    files = sorted(path.glob("*.wav")) if path.is_dir() else [path]
    if not files:
        print(f"No .wav files found in {path}")
        return

    model = Model(str(MODEL_PATH))
    for wav in files:
        try:
            text = recognize_file(wav, model)
        except Exception as exc:  # noqa: BLE001
            print(f"{wav.name}: ERROR {exc}")
            continue
        print(f"{wav.name}: heard {text!r} → pose {match_command(text)}")


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
    ap.add_argument("--audio", metavar="PATH",
                    help="recognize a WAV file or a directory of WAVs instead of "
                         "the live mic, print the matched pose, and exit")
    args = ap.parse_args()
    if args.audio:
        _audio_mode(Path(args.audio))
        return
    run(args)


if __name__ == "__main__":
    main()
