# Audio samples

Drop voice recordings here to test the speech → pose pipeline without a live
microphone.

## Format

Any format libsndfile reads: **WAV, MP3, FLAC, OGG/Opus**. Any sample rate,
mono or stereo — the loader downmixes to mono and resamples to 16 kHz
automatically. (No m4a/AAC — export to one of the above.)

## Naming convention

Name each file so its expected pose is known — either works:

1. **The spoken command word itself** — `张开.mp3`, `打开.mp3`, `握拳.mp3`,
   `胜利.mp3`, `好的.mp3`. Must be a word in `POSE_VOCAB`.
2. **A pose-name prefix** — `open_1.wav`, `close_loud.mp3`, `ok_fast.wav`,
   `victory_noisy.flac`.

A name matching neither is skipped by the test (you can still run it with
`--audio`).

## Recognition notes (small Chinese model)

- The model is **Chinese-only** — English words like "ok" are not recognized.
  Use **好的** for the OK/grab gesture.
- Use a **clear two-syllable word**, not a single short syllable. `抓` alone is
  too brief and ambiguous; record **抓取** or **好的** instead.
- Recognition is grammar-constrained to the command words, so close homophones
  (e.g. 握拳 vs 没钱) resolve correctly.

## Using them

Ad-hoc — print what each file is heard as and which pose it maps to:

```bash
python amazing_hand_audio.py --audio tests/fixtures/audio_samples/             # whole folder
python amazing_hand_audio.py --audio tests/fixtures/audio_samples/张开.mp3      # one file
```

As a regression test (auto-skips when this folder has no recordings):

```bash
pytest tests/test_audio_files.py -v
```

The recordings themselves are gitignored — only this README lives in the repo.
