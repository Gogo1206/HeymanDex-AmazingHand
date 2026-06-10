"""Recognition tests driven by recordings in audio_samples/.

These run Vosk on real .wav files, so they need vosk installed and the model
downloaded. The whole module auto-skips when no samples are present, so the
default test run (no recordings committed) stays green and hardware-free.

Name a sample after the pose it should trigger — e.g. ``open_1.wav`` — and it
is checked here. See audio_samples/README.md.
"""
from amazing_hand_audio import AUDIO_SAMPLES_DIR, POSE_VOCAB, match_command

import pytest


def _wav_files():
    if not AUDIO_SAMPLES_DIR.is_dir():
        return []
    return sorted(AUDIO_SAMPLES_DIR.glob("*.wav"))


def _expected_pose(stem: str) -> str | None:
    low = stem.lower()
    for pose in POSE_VOCAB:
        if low.startswith(pose):
            return pose
    return None


_WAVS = _wav_files()

pytestmark = pytest.mark.skipif(
    not _WAVS, reason="no recordings in audio_samples/ (drop some .wav files to enable)"
)


@pytest.mark.parametrize("wav", _WAVS, ids=[p.name for p in _WAVS])
def test_sample_maps_to_expected_pose(wav):
    expected = _expected_pose(wav.stem)
    if expected is None:
        pytest.skip(
            f"{wav.name}: filename must start with a pose "
            f"(open/close/ok/victory) to be checked"
        )
    # Import here so collection doesn't require vosk when the module is skipped.
    from amazing_hand_audio import recognize_file

    text = recognize_file(wav)
    assert match_command(text) == expected, f"{wav.name}: heard {text!r}"
