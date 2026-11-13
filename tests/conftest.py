"""Shared test setup: the repository root on the import path, the program's tools importable, and
nothing a test does reaching the user's own library, browser or the network.

How these tests are written (docs/how-it-works.md, "How a change is made"): the test comes first and is seen to
fail; it is seen to fail again with the mending taken out.  No sheet music, no words of a real song and no
recording goes in here - a test draws its own music and makes up its own words, and does not name the piece that
showed the fault.  A sound's note is told from its overtones or its period, never asked of a pitch tracker."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'tools')):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault('PALARE_NO_BROWSER', '1')
os.environ.setdefault('PALARE_NO_OPEN', '1')
os.environ.setdefault('PALARE_QUIET', '1')          # no sound from this computer when a test makes tracks

import pytest  # noqa: E402

DEMO = os.path.join(ROOT, 'scores', 'demo_shenandoah.score')


@pytest.fixture
def demo_score(tmp_path):
    """A private copy of the demo score, safe to change."""
    import shutil
    dst = tmp_path / 'demo.score'
    shutil.copy(DEMO, dst)
    return str(dst)
