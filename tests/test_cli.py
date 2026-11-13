"""choral/__main__.py: the command line, `python -m choral MUSIC ...`."""
import json
import os
import subprocess
import sys
import wave

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TINY = """title: Tiny test
tempo: 120
time: 2/4
== 1
TEN: !mf c4/q=la d4/q=la
LOW: c3/h=la
RH: c4+e4+g4/h
LH: c2/h
== 2
TEN: e4/h=la
LOW: g2/h=la
RH: c4+e4+g4/h
LH: c2/h
"""


def run(*args, timeout=300):
    env = dict(os.environ, CHORAL_WORKERS='2', PALARE_NO_BROWSER='1', PALARE_NO_OPEN='1')
    return subprocess.run([sys.executable, '-m', 'choral', *map(str, args)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout)


def read_wav(path):
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, 44100)
        n = w.getnframes()
        x = np.frombuffer(w.readframes(n), '<i2').reshape(-1, 2) / 32767
    return x


@pytest.fixture
def tiny(tmp_path):
    p = tmp_path / 'tiny.score'
    p.write_text(TINY)
    return p


# ---------------------------------------------------------------- argument parsing, quick runs ----
def test_help():
    r = run('--help')
    assert r.returncode == 0
    for flag in ('--part', '--singers', '--out', '--only', '--measures', '--read', '--accompaniment'):
        assert flag in r.stdout


def test_music_is_required():
    r = run()
    assert r.returncode == 2
    assert 'music' in r.stderr


def test_singers_must_be_a_number(tiny):
    r = run(tiny, '--singers', 'two')
    assert r.returncode == 2 and '--singers' in r.stderr


def test_read_says_what_was_found_and_stops(demo_score, tmp_path):
    out = tmp_path / 'o'
    r = run(demo_score, '--read', '--out', out)
    assert r.returncode == 0, r.stderr
    assert '5 measures, 68 sung notes, 38 piano notes' in r.stdout
    assert not out.exists()
    assert not os.path.exists(os.path.splitext(demo_score)[0] + '.preset.json')


def test_measures_flag(demo_score):
    r = run(demo_score, '--measures')
    assert r.returncode == 0, r.stderr
    line = next(l for l in r.stdout.splitlines() if l.startswith('measures: '))
    ms = json.loads(line[len('measures: '):])
    assert [m for _, m in ms] == [1, 2, 3, 4, 5]
    assert ms[0][0] == 1.0
    assert np.allclose(np.diff([s for s, _ in ms]), 4 * 60 / 66, atol=.011)


def test_measures_flag_tiny(tiny):
    r = run(tiny, '--measures')
    assert r.returncode == 0, r.stderr
    assert 'measures: [[1.0, 1], [2.0, 2]]' in r.stdout


def test_unknown_part_is_refused(tiny, tmp_path):
    r = run(tiny, '--part', 'soprano', '--out', tmp_path / 'o')
    assert r.returncode != 0
    assert '--part takes' in r.stderr and 'soprano' in r.stderr
    assert not (tmp_path / 'o').exists()


def test_part_missing_from_score_is_refused(tiny, tmp_path):
    r = run(tiny, '--part', 'solo', '--out', tmp_path / 'o')
    assert r.returncode != 0 and '--part takes' in r.stderr


def test_missing_voice_file_is_refused(tiny, tmp_path):
    r = run(tiny, '--voice', tmp_path / 'nobody.wav', '--out', tmp_path / 'o')
    assert r.returncode != 0 and 'there is no file' in r.stderr


def test_parts_table():
    from choral.__main__ import PARTS
    assert PARTS['tenor1'] == PARTS['t1'] == 'T1'
    assert PARTS['baritone'] == PARTS['bari'] == 'BR'
    assert PARTS['bass'] == 'BS' and PARTS['solo'] == 'SOLO'


# ---------------------------------------------------------------- end to end ------------------------
@pytest.mark.slow
def test_end_to_end_demo_part(demo_score, tmp_path):
    out = tmp_path / 'out'
    r = run(demo_score, '--singers', '2', '--part', 'baritone', '--out', out)
    assert r.returncode == 0, r.stdout + r.stderr
    stem = 'Shenandoah traditional - format demo - '
    names = ['voices only', 'balanced', 'Baritone predominant', 'Baritone muted', 'Baritone alone']
    files = sorted(os.listdir(out))
    assert files == sorted([stem + n + '.wav' for n in names] + ['measures.json'])
    lengths = set()
    for n in names:
        x = read_wav(out / (stem + n + '.wav'))
        lengths.add(len(x))
        assert np.abs(x).max() <= .94                    # mastered at 0.93 of full scale
        assert np.sqrt((x ** 2).mean()) > .01            # not silent
    assert len(lengths) == 1                             # every version lines up with the others
    assert lengths.pop() / 44100 > 15.55                 # past the start of the last measure
    ms = json.load(open(out / 'measures.json'))
    assert [m for _, m in ms] == [1, 2, 3, 4, 5]
    preset = os.path.splitext(demo_score)[0] + '.preset.json'
    assert json.load(open(preset))['singers'] == 2       # what was chosen for this piece is saved beside it


@pytest.mark.slow
def test_end_to_end_tiny_three_part_only(tmp_path):
    # LOW has one note, so baritones and basses sing one line: "--part bass" is both of them, "Bass".
    # Unaccompanied, so that what is left when the basses are muted is the tenors alone.
    tiny = tmp_path / 'tiny.score'
    tiny.write_text(''.join(l + '\n' for l in TINY.splitlines() if not l.startswith(('RH', 'LH'))))
    out = tmp_path / 'out'
    r = run(tiny, '--singers', '1', '--part', 'bass', '--only', 'Bass muted', '--out', out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(os.listdir(out)) == ['Tiny test - Bass muted.wav', 'measures.json']
    x = read_wav(out / 'Tiny test - Bass muted.wav')
    assert np.isfinite(x).all() and np.abs(x).max() <= .94
    from choral import pitch
    t, m = pitch.yin(x.mean(1), 44100)
    sung = m[(t > 1.1) & (t < 3.8)]
    assert np.nanmedian(sung) > 55                       # only the tenors' C4-E4 is left


@pytest.mark.slow
def test_end_to_end_no_part_writes_voices_and_balanced(tiny, tmp_path):
    out = tmp_path / 'out'
    r = run(tiny, '--singers', '1', '--out', out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(os.listdir(out)) == ['Tiny test - balanced.wav', 'Tiny test - voices only.wav', 'measures.json']
    for f in ('balanced', 'voices only'):
        x = read_wav(out / f'Tiny test - {f}.wav')
        assert len(x) / 44100 == pytest.approx(1. + 2. + 4., abs=.05)   # lead-in, 4 beats at 120, 4 s of tail
