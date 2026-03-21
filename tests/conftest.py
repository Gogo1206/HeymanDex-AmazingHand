"""
Shared pytest configuration.

Adds the project root to sys.path so test modules can import
amazing_hand_gui and amazing_hand_cmd directly, regardless of
how pytest is invoked.
"""
import sys
from pathlib import Path

# Project root is one level above this file
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
