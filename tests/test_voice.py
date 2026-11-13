"""choral/voice.py: one simulated singer at a time, on phrases a second or two long."""
import numpy as np
import pytest

from choral import voice, pitch

SR = voice.SR
# 120 beats a minute, the first beat one second in (the engine breathes in before a phrase, so a
# phrase on the very first sample would have nowhere to put its breath)
CLOCK = (np.array([0., 100.]), np.array([1., 51.]), 3.0)


@pytest.fixture(autouse=True)
def _keep_engine_state():
    """render_singer sets the global clock and may install settings: put them back after each test."""
    clock = {k: (v.copy() if hasattr(v, 'copy') else v) for k, v in voice.CLOCK.items()}
    tune = dict(voice.TUNE)
    yield
    voice.CLOCK.clear(); voice.CLOCK.update(clock)
    voice.TUNE.clear(); voice.TUNE.update(tune)


def sing(notes, sect='BR', idx=0, clock=CLOCK, with_pitch=False):
    args = (sect, idx, notes, clock) + (({}, True) if with_pitch else ())
    return voice.render_singer(args)


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, float) ** 2)))


def f0_midi(x, t0=None, t1=None):
    t, m = pitch.yin(np.asarray(x, float), SR)
    sel = np.ones(len(t), bool)
    if t0 is not None:
        sel &= t >= t0
    if t1 is not None:
        sel &= t <= t1
    return float(np.nanmedian(m[sel]))


A3 = [(0., 1.5, 57, 'AA', .74)]           # one held "ah" on A3 (220 Hz), mezzo-forte, from 1.0 s to 1.75 s


def test_output_shape_and_values():
    sect, x, y, star, out = sing(A3)
    assert sect == 'BR'
    assert out.dtype == np.float32 and out.ndim == 1
    assert len(out) == int(CLOCK[2] * SR)
    assert np.isfinite(out).all()
    assert rms(out) > 1e-3                                  # it sings
    assert np.isfinite([x, y]).all() and y > 0              # placed on the risers, in front of the microphones
    assert isinstance(star, (bool, np.bool_))


def test_sound_lies_where_the_note_is():
    out = sing(A3)[4]
    before = out[:int(.3 * SR)]                             # long before the breath for the phrase
    during = out[int(1.1 * SR):int(1.7 * SR)]
    after = out[int(2.6 * SR):]
    assert np.abs(before).max() == 0
    assert rms(during) > 100 * (rms(after) + 1e-9)


@pytest.mark.parametrize('sect,midi', [('BS', 48), ('BR', 57), ('T1', 64)])
def test_pitch_is_the_written_note(sect, midi):
    out = sing([(0., 1.5, midi, 'AA', .74)], sect=sect)[4]
    got = f0_midi(out, 1.15, 1.7)
    assert got == pytest.approx(midi, abs=.5)              # within a quarter tone (singers hunt and drift)


def test_pitch_track_returned_with_the_voice():
    r = sing(A3, with_pitch=True)
    assert len(r) == 6
    sung = r[5]
    assert len(sung) == int(voice.CLOCK['n'] * voice.CR / SR) + 2
    voiced = sung[sung > 0]
    assert len(voiced) > .3 * voice.CR                      # most of the 0.75 s note is voiced
    assert 69 + 12 * np.log2(np.median(voiced) / 440) == pytest.approx(57, abs=.5)
    assert np.array_equal(r[4], sing(A3)[4])                # asking for the pitch does not change the sound


def test_melisma_carries_the_vowel_to_a_new_pitch():
    notes = [(0., 1., 55, 'AA', .74), (1., 1., 62, '-', .74)]   # G3 then D4 on one "ah"
    out = sing(notes)[4]
    assert f0_midi(out, 1.12, 1.42) == pytest.approx(55, abs=.6)
    assert f0_midi(out, 1.62, 1.92) == pytest.approx(62, abs=.6)


def test_divisi_shares_the_notes_out_by_singer():
    notes = [(0., 1.5, (57, 61), 'AA', .74)]
    low = sing(notes, idx=0)[4]
    high = sing(notes, idx=1)[4]
    assert f0_midi(low, 1.15, 1.7) == pytest.approx(57, abs=.5)
    assert f0_midi(high, 1.15, 1.7) == pytest.approx(61, abs=.5)


def test_same_seed_same_take():
    assert np.array_equal(sing(A3)[4], sing(A3)[4])


def test_another_seed_another_choir(monkeypatch):
    a = sing(A3)[4]
    monkeypatch.setattr(voice, 'SEED', voice.SEED + 1)
    b = sing(A3)[4]
    assert not np.array_equal(a, b)
    # still the same note, sung about as loudly
    assert f0_midi(b, 1.15, 1.7) == pytest.approx(57, abs=.5)
    assert .2 < rms(b) / rms(a) < 5


def test_singers_differ_within_a_section():
    a, b = sing(A3, idx=0)[4], sing(A3, idx=2)[4]
    assert not np.array_equal(a, b)
    assert np.corrcoef(a, b)[0, 1] < .9


def test_make_singer_is_deterministic(monkeypatch):
    P1, _ = voice.make_singer('T2', 3)
    P2, _ = voice.make_singer('T2', 3)
    assert P1['seed'] == P2['seed'] and P1['x'] == P2['x'] and P1['fs'] == P2['fs']
    monkeypatch.setattr(voice, 'SEED', voice.SEED + 5)
    P3, _ = voice.make_singer('T2', 3)
    assert P3['seed'] != P1['seed'] and P3['x'] != P1['x']


def test_section_leaders():
    assert voice.make_singer('BS', 1)[0]['star'] and voice.make_singer('BS', 6)[0]['star']
    assert not voice.make_singer('BS', 0)[0]['star']


def test_rest_is_silent():
    # a note, two beats' rest (1 s), and a note: the middle of the rest has no singing in it
    notes = [(0., 1., 57, 'AA', .74), (3., 1., 57, 'AA', .74)]
    out = sing(notes, clock=(CLOCK[0], CLOCK[1], 4.0))[4]
    first = out[int(1.05 * SR):int(1.45 * SR)]
    rest = out[int(1.85 * SR):int(2.05 * SR)]               # after the release, before the next breath
    second = out[int(2.55 * SR):int(2.95 * SR)]
    assert rms(rest) < .01 * rms(first)
    assert rms(second) > .3 * rms(first)
    t, m = pitch.yin(np.asarray(out, float), SR)
    assert np.isnan(m[(t > 1.85) & (t < 2.05)]).all()


def test_no_notes_no_sound():
    out = sing([])[4]
    assert len(out) == int(CLOCK[2] * SR) and not out.any()


def test_split_phrases_at_rests():
    notes = [(2., 1., 60, 'AA', .7), (0., 1., 60, 'AA', .7), (1., 1., 60, '-', .7), (3.3, 1., 60, 'AA', .7)]
    ph = voice.split_phrases(notes)
    assert [[n[0] for n in p] for p in ph] == [[0., 1., 2.], [3.3]]


def test_louder_dynamic_more_energy():
    seg = slice(int(1.1 * SR), int(1.7 * SR))
    e = [rms(sing([(0., 1.5, 57, 'AA', d)])[4][seg]) for d in (.42, .74, 1.0)]   # pp, mf, ff
    assert e[0] < e[1] < e[2]
    assert e[2] > 1.5 * e[0]


def test_spoken_note_is_said_not_sung_on_the_pitch():
    sung = sing([(0., 1.5, 64, 'AA', .74)])[4]
    said = sing([(0., 1.5, 64, 'AA', .74, True)])[4]
    assert f0_midi(sung, 1.1, 1.5) == pytest.approx(64, abs=.5)
    m = f0_midi(said, 1.0, 1.4)
    assert m < 58                                           # a speaking voice, well under the written E4
    # and short: a spoken syllable lasts as long as saying it takes, not the note's 0.75 s
    assert rms(said[int(1.55 * SR):int(1.8 * SR)]) < .2 * rms(sung[int(1.55 * SR):int(1.8 * SR)])


def test_clock_maps_beats_to_seconds():
    voice.set_clock([0., 4., 8.], [1., 3., 7.], 10.)
    assert voice.T(0) == 1. and voice.T(2) == 2. and voice.T(6) == 5.
    assert voice.CLOCK['n'] == 10 * SR
