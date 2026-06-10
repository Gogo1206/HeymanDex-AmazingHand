# Audio samples

Drop voice recordings here to test the speech → pose pipeline without a live
microphone.

## Format

- **WAV**, 16-bit PCM. Any sample rate and mono/stereo is fine — the loader
  downmixes to mono and resamples to 16 kHz automatically.
- (No mp3/m4a — convert to WAV first, e.g. in QuickTime/Audacity, since ffmpeg
  isn't required by this project.)

## Naming convention

Start each filename with the pose it should trigger, so the test suite knows
what to expect:

| filename starts with | expected pose |
|----------------------|---------------|
| `open…`              | open          |
| `close…`             | close         |
| `ok…`                | ok            |
| `victory…`           | victory       |

Examples: `open_1.wav`, `close_loud.wav`, `ok_fast.wav`, `victory_noisy.wav`.

A filename that doesn't start with a pose name is skipped by the test (you can
still run it manually with `--audio`).

## Using them

Ad-hoc, print what each file is heard as and which pose it maps to:

```bash
python amazing_hand_audio.py --audio audio_samples/            # whole folder
python amazing_hand_audio.py --audio audio_samples/open_1.wav  # one file
```

As a regression test (auto-skips when this folder has no wavs):

```bash
pytest tests/test_audio_files.py -v
```

The `.wav` files themselves are gitignored — only this README and the naming
convention live in the repo.
