"""choral/piano.py: the modelled piano that plays a score's accompaniment."""
import numpy as np
import pytest

from choral import piano, pitch

SR = piano.SR


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, float) ** 2)))


def T(b):                         # 120 beats a minute, the first beat half a second in
    return .5 + .5 * b


def flat(_):
    return .7


def nt(beat, dur, midi, flags='', **kw):
    return dict(beat=beat, dur=dur, midi=midi, flags=flags, **kw)


@pytest.mark.parametrize('midi', [33, 45, 57, 69, 76])
def test_note_pitch(midi):
    x = piano.note(midi, 1.0, .6, np.random.default_rng(0))
    assert np.isfinite(x).all()
    t, m = pitch.yin(x, SR, fmin=40., fmax=700.)
    assert np.nanmedian(m[t < .8]) == pytest.approx(midi, abs=.3)


def test_note_length_and_onset():
    x = piano.note(60, 1.0, .6, np.random.default_rng(0))
    ring = min(7.0, 1.2 + 14 * 2 ** (-(60 - 36) / 14))
    assert len(x) == int((min(1.0, ring) + .4) * SR)
    assert x[0] == 0                                  # a 2 ms fade-in: no click at the start
    long = piano.note(60, 30., .6, np.random.default_rng(0))
    assert len(long) == int((ring + .4) * SR)          # a string rings only so long, however long it is held


def test_note_decays():
    x = piano.note(57, 2.0, .6, np.random.default_rng(0))
    w = SR // 10
    e = np.array([rms(x[i:i + w]) for i in range(0, len(x) - w, w)])
    assert e.argmax() <= 1                             # loudest at the strike
    assert e[8] < .6 * e[0]                            # fading while held
    assert e[-1] < .1 * e[0]                           # and damped after it is let go


def test_damper_stops_the_string():
    short = piano.note(57, .3, .6, np.random.default_rng(0))
    held = piano.note(57, 1.2, .6, np.random.default_rng(0))
    win = slice(int(.6 * SR), int(.7 * SR))
    assert rms(short[win]) < .2 * rms(held[win])


def test_low_notes_ring_longer():
    lo = piano.note(36, 10., .6, np.random.default_rng(0))
    hi = piano.note(84, 10., .6, np.random.default_rng(0))
    assert len(lo) > len(hi)


def test_harder_strike_louder_and_brighter():
    soft = piano.note(57, 1., .2, np.random.default_rng(0))
    hard = piano.note(57, 1., .9, np.random.default_rng(0))
    assert rms(hard) > 1.3 * rms(soft)
    f = np.fft.rfftfreq(len(soft), 1 / SR)
    cent = lambda x: float((f * np.abs(np.fft.rfft(x))).sum() / np.abs(np.fft.rfft(x)).sum())
    assert cent(hard) > cent(soft)


def test_render_shape_and_finite():
    out = piano.render([nt(0., 2., 60)], 3 * SR, T, flat)
    assert out.shape == (3 * SR, 2)
    assert np.isfinite(out).all()
    assert rms(out[:int(.49 * SR)]) < 1e-3 * rms(out[int(.5 * SR):int(1. * SR)])   # silent before the note
    assert rms(out) > 1e-3


def test_render_note_starts_on_its_beat():
    out = piano.render([nt(2., 1., 60)], 3 * SR, T, flat)          # beat 2 -> 1.5 s
    env = np.abs(out).sum(1)
    onset = np.flatnonzero(env > .1 * env.max())[0] / SR
    assert onset == pytest.approx(1.5, abs=.03)


def test_render_pitch():
    out = piano.render([nt(0., 2., 57)], 3 * SR, T, flat)
    t, m = pitch.yin(out.mean(1), SR, fmin=40., fmax=700.)
    assert np.nanmedian(m[(t > .55) & (t < 1.3)]) == pytest.approx(57, abs=.3)


def test_render_chord_has_every_note():
    chord = [nt(0., 2., m) for m in (48, 52, 55)]     # C major: C3 E3 G3
    out = piano.render(chord, 3 * SR, T, flat)
    assert np.isfinite(out).all()
    seg = out[int(.6 * SR):int(1.6 * SR)].mean(1)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    peak = lambda hz: spec[(f > hz * .985) & (f < hz * 1.015)].max()
    floor = np.median(spec[(f > 100) & (f < 300)])
    for m in (48, 52, 55):
        assert peak(440 * 2 ** ((m - 69) / 12)) > 20 * floor
    single = piano.render([nt(0., 2., 48)], 3 * SR, T, flat)
    assert rms(out) > 1.3 * rms(single)


def test_bass_left_treble_right():
    lo = piano.render([nt(0., 2., 36)], 3 * SR, T, flat)
    hi = piano.render([nt(0., 2., 90)], 3 * SR, T, flat)
    assert rms(lo[:, 0]) > rms(lo[:, 1])
    assert rms(hi[:, 1]) > rms(hi[:, 0])


def test_render_deterministic_by_seed():
    notes = lambda: [nt(0., 1., 60), nt(1., 1., 64)]
    a = piano.render(notes(), 3 * SR, T, flat, seed=1)
    b = piano.render(notes(), 3 * SR, T, flat, seed=1)
    c = piano.render(notes(), 3 * SR, T, flat, seed=2)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_louder_dynamic_louder_render():
    soft = piano.render([nt(0., 2., 60)], 3 * SR, T, lambda b: .4)
    loud = piano.render([nt(0., 2., 60)], 3 * SR, T, lambda b: 1.)
    assert rms(loud) > 1.2 * rms(soft)


def test_staccato_is_shorter():
    legato = piano.render([nt(0., 2., 60)], 3 * SR, T, flat)
    stacc = piano.render([nt(0., 2., 60, "'")], 3 * SR, T, flat)
    late = slice(int(1.3 * SR), int(1.8 * SR))
    assert rms(stacc[late]) < .3 * rms(legato[late])


def test_notes_outside_the_buffer_are_skipped():
    out = piano.render([nt(20., 1., 60)], 2 * SR, T, flat)          # beat 20 -> 10.5 s, past the end
    assert out.shape == (2 * SR, 2) and not out.any()


def test_empty_render_is_silent():
    out = piano.render([], SR, T, flat)
    assert out.shape == (SR, 2) and not out.any()


def test_apply_fit(monkeypatch):
    monkeypatch.setattr(piano, 'FIT', dict(piano.FIT))
    eq0 = piano.FIT['eq']
    piano.apply_fit({'P.dec0': .5, 'PEQ.2': 3.})
    assert piano.FIT['dec0'] == .5
    assert piano.FIT['eq'][2] == (eq0[2][0], 3.)
    assert piano.FIT['eq'][0] == eq0[0]
