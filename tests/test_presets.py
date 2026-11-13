"""choral/presets.py: the estimates made from the score alone, and the release curve on a synthetic signal."""
import numpy as np
import pytest

from choral import presets, score


def quiet(*a):
    pass


def test_quick_syllable_is_the_15th_percentile():
    # at 120 a minute: eighths 0.25 s, a half 1 s, a quarter 0.5 s
    sc = score.parse('tempo: 120\n== 1\nT1: c4/e=la c4/e=la c4/h=la c4/q=la\n', warn=quiet)
    assert presets.quick_syllable(sc) == pytest.approx(np.percentile([.25, .25, 1., .5], 15))


def test_quick_syllable_ignores_held_notes():
    # a slurred note ("_") is not a syllable of its own
    sc = score.parse('tempo: 60\n== 1\nT1: c4/h=la d4/e=_ e4/e=_ c4/q=lo\n', warn=quiet)
    assert presets.quick_syllable(sc) == pytest.approx(np.percentile([2., 1.], 15))


def test_quick_syllable_with_no_voices():
    sc = score.parse('== 1\nRH: c4/w\n', warn=quiet)
    assert presets.quick_syllable(sc) == 1.


def test_quick_syllable_follows_tempo_changes():
    sc = score.parse('tempo: 60\n== 1\nT1: c4/w=la\ntempo: 240\n== 2\nT1: c4/q=la c4/q=la c4/q=la c4/q=la\n', warn=quiet)
    assert presets.quick_syllable(sc) == pytest.approx(.25)


@pytest.mark.parametrize('tempo,durs,rung', [
    (120, 'c4/e=la c4/e=la c4/h=la c4/q=la', 2),     # 0.25 s: interp 2.17 -> rung 2
    (200, 'c4/e=la c4/e=la c4/e=la c4/e=la c4/h=la', 2),   # 0.15 s: clipped to the dry end of the rule
    (100, 'c4/e=la c4/e=la c4/e=la c4/e=la c4/h=la', 3),   # 0.30 s
    (40, 'c4/w=la', 4),                               # 6 s: clipped to the wet end of the rule
])
def test_from_score_picks_a_rung_from_text_speed(tempo, durs, rung):
    sc = score.parse(f'tempo: {tempo}\n== 1\nT1: {durs}\n', warn=quiet)
    got = presets.from_score(sc)
    q = presets.quick_syllable(sc)
    assert got == dict(presets.LADDER[rung], quick_syllable=round(q, 3))


def test_from_score_demo(demo_score):
    got = presets.from_score(score.load(demo_score))
    assert got == {'hall': .28, 'spot': 1.0, 'quick_syllable': .455}


def test_ladder_runs_from_dry_and_close_to_wet_and_blended():
    halls = [r['hall'] for r in presets.LADDER]
    spots = [r['spot'] for r in presets.LADDER]
    assert halls == sorted(halls) and spots == sorted(spots, reverse=True)
    xs, rungs = presets.QUICK_TO_RUNG
    assert all(0 <= r < len(presets.LADDER) for r in rungs)


def _releases(n, db_per_s, sr=44100):
    t = np.arange(int(1.5 * sr)) / sr
    seg = []
    for _ in range(n):
        seg += [.3 * np.sin(2 * np.pi * 220 * t), .3 * np.sin(2 * np.pi * 220 * (t + 1.5)) * 10 ** (-db_per_s * t / 20)]
    return np.concatenate(seg)


def test_release_curve_measures_the_decay():
    curve, n = presets.release_curve(_releases(4, 60.))
    assert n == 4
    assert len(curve) == 120                         # 1.2 s in 10 ms steps
    assert curve[0] == pytest.approx(0., abs=1.)
    assert curve[25] == pytest.approx(-15., abs=1.5)  # 60 dB/s
    assert curve[50] == pytest.approx(-30., abs=1.5)
    assert curve.min() == -32.                       # floored


def test_release_curve_stereo_is_averaged():
    x = _releases(4, 60.)
    c1, n1 = presets.release_curve(x)
    c2, n2 = presets.release_curve(np.stack([x, x], 1))
    assert n1 == n2 and np.allclose(c1, c2)


def test_release_curve_needs_three_releases():
    assert presets.release_curve(_releases(2, 60.)) == (None, 2)
    noise = np.random.default_rng(0).standard_normal(44100 * 3) * .3
    assert presets.release_curve(noise) == (None, 0)
