"""The page's own script (choral/app.html), where it can be run by itself: the reckoning that needs no browser.

Each function is taken out of the page as it is written there and run with node where there is one (GitHub's
machines have it) or with the Mac's own JavaScript (osascript); where there is neither, these are skipped.  What
needs a browser - a click, a sound, a track playing - is tried by hand in a copy of the page."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

from choral import app

HTML = open(os.path.join(os.path.dirname(app.__file__), 'app.html'), encoding='utf-8').read()


def source(name):
    """One of the page's functions, as text: from "function name(" to the brace that closes it."""
    start = HTML.index('function ' + name + '(')
    depth, i = 0, HTML.index('{', start)
    while True:
        depth += {'{': 1, '}': -1}.get(HTML[i], 0)
        if depth == 0:
            return HTML[start:i + 1]
        i += 1


def js(expression, *functions, consts=()):
    """The value of a JavaScript expression that uses the page's functions (and its constants) named."""
    lines = [next(ln for ln in HTML.splitlines() if ln.startswith('const ' + c + ' =')) for c in consts] + [source(f) for f in functions]
    value = 'JSON.stringify(' + expression + ')'
    if shutil.which('node'):                             # as a file: nothing of it has to survive a command line
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, 'page.js')
            with open(f, 'w', encoding='utf-8') as o:
                o.write('\n'.join(lines) + '\nconsole.log(' + value + ')\n')
            r = subprocess.run([shutil.which('node'), f], capture_output=True, text=True, encoding='utf-8', timeout=60)
    elif sys.platform == 'darwin' and shutil.which('osascript'):
        r = subprocess.run(['osascript', '-l', 'JavaScript', '-e', '\n'.join(lines) + '\n' + value], capture_output=True, text=True, encoding='utf-8', timeout=60)
    else:
        pytest.skip('nothing on this computer runs JavaScript by itself')
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# when each measure begins in a track: [seconds, the measure's number], in the order played
PLAIN = [[1.0, 0], [1.6, 1], [4.0, 2], [6.4, 3], [8.8, 4]]              # an upbeat, then four measures
TWICE = [[0, 1], [2, 2], [4, 1], [6, 2], [8, 3]]                         # measures 1 and 2 are repeated


# ---- the measure being heard
@pytest.mark.parametrize('seconds, measure', [(0, 0), (1.2, 0), (1.56, 1), (3.9, 1), (4.0, 2), (99, 4)])
def test_the_measure_at_a_moment(seconds, measure):
    assert js(f'measureAt({{timeline: {PLAIN}}}, {seconds})', 'measureAt') == measure


def test_a_track_that_does_not_know_its_measures_has_none():
    assert js('measureAt({}, 3)', 'measureAt') is None


@pytest.mark.parametrize('measures, said', [([7], 'measure 7'), ([0, 1, 2, 3, 4, 7, 9], 'measures 0\u20134, 7 and 9'), ([3, 4], 'measures 3\u20134'), ([2, 5], 'measures 2 and 5')])
def test_measures_said_in_words(measures, said):
    assert js(f'runs({measures})', 'runs') == said


# ---- a passage to repeat: from the beginning of one measure to the end of another
def stretch(tl, a, b):
    return js(f'stretch({tl}, {a}, {b})', 'stretch')


def test_a_passage_runs_from_the_start_of_its_first_measure_to_the_end_of_its_last():
    assert stretch(PLAIN, 1, 2) == {'from': 1.6, 'to': 6.4}
    assert stretch(PLAIN, 3, 3) == {'from': 6.4, 'to': 8.8}             # one measure, over and over
    assert stretch(PLAIN, 0, 1) == {'from': 1.0, 'to': 4.0}             # from the pickup


def test_a_passage_to_the_last_measure_runs_to_the_end_of_the_track():
    assert stretch(PLAIN, 3, 4) == {'from': 6.4, 'to': None}


def test_measures_given_the_wrong_way_round_are_taken_the_right_way():
    assert stretch(PLAIN, 3, 1) == stretch(PLAIN, 1, 3) == {'from': 1.6, 'to': 8.8}


def test_a_measure_the_piece_has_not_is_named():
    assert stretch(PLAIN, 2, 9) == {'missing': 9}
    assert stretch(PLAIN, 7, 2) == {'missing': 7}


def test_in_a_piece_with_a_repeat_the_passage_is_the_shortest_that_fits():
    assert stretch(TWICE, 1, 2) == {'from': 0, 'to': 4}                 # the first time through
    assert stretch(TWICE, 2, 3) == {'from': 6, 'to': None}              # the 2 that leads on to 3: the second
    assert stretch(TWICE, 2, 1) == {'from': 2, 'to': 6}                 # over the repeat itself: 2, and back to 1


# ---- slower, for learning
@pytest.mark.parametrize('kept, speed', [('0.7', .7), ('1', 1), ('0.5', .5), (None, 1), ('', 1), ('3', 1), ('fast', 1), ('0.71', 1)])
def test_only_the_speeds_offered_are_ever_used(kept, speed):
    assert js(f'speedOf({json.dumps(kept)})', 'speedOf', consts=['SPEEDS']) == speed


def test_the_speeds_offered_begin_with_the_tempo_as_written_and_only_go_slower():
    speeds = js('SPEEDS.map(s => s[0])', consts=['SPEEDS'])
    assert speeds[0] == 1 and speeds == sorted(speeds, reverse=True) and min(speeds) >= .5
