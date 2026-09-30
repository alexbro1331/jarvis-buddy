"""Launcher used for autostart (no console window on Windows)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from buddy.app import main  # noqa: E402

main()
