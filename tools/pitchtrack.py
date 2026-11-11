"""Kept for the tools that import it; the tracker itself lives in choral/pitch.py."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from choral.pitch import yin  # noqa: F401
