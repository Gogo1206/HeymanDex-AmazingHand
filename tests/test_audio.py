"""Unit tests for the pure command matcher in amazing_hand_audio.

Mic capture, Vosk, and pynput key handling are hardware/OS dependent and are
verified manually — only the pure match_command function is unit-tested here.
"""
from amazing_hand.amazing_hand_audio import match_command


def test_primary_words_map_to_poses():
    assert match_command("张开") == "open"
    assert match_command("握拳") == "close"
    assert match_command("抓取") == "ok"
    assert match_command("胜利") == "victory"


def test_synonyms_map_to_poses():
    assert match_command("打开") == "open"
    assert match_command("抓紧") == "close"
    assert match_command("拿取") == "ok"
    assert match_command("剪刀") == "victory"


def test_english_words_are_not_matched():
    # English was removed from the vocab: the Chinese Vosk model can't hear it,
    # so the matcher must not claim a pose for English text.
    assert match_command("open") is None
    assert match_command("ok") is None
    assert match_command("victory") is None


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
