"""choral/timing.py: the deterministic parts, on small synthetic signals."""
import wave

import numpy as np
import pytest

from choral import score, timing


def quiet(*a):
    pass


@pytest.fixture
def sc():
    return score.parse('tempo: 60\n== 1\nT1: c4/q d4/q e4/q f4/q\n== 2\nT1: g4/h e4/h\n', warn=quiet)


def pitch_track(sc, offset, length=12., hop=.01, part='T1'):
    """A perfect pitch track (MIDI per frame, NaN where silent) of the score played at its tempo from `offset`."""
    nb, ns = timing.nominal(sc)
    t = np.arange(0, length, hop)
    m = np.full(len(t), np.nan)
    for b, d, mi in timing.part_notes(sc, part):
        a, z = np.interp([b, b + d], nb, ns) + offset
        m[(t >= a + .02) & (t < z - .02)] = mi
    return t, m


def test_read_wav_mono_and_channel(tmp_path):
    p = tmp_path / 'x.wav'
    data = np.array([[16384, -16384], [8192, 0]], '<i2')
    with wave.open(str(p), 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(data.tobytes())
    x, sr = timing.read_wav(str(p))
    assert sr == 8000
    assert np.allclose(x, [0., .125])
    x1, _ = timing.read_wav(str(p), channel=0)
    assert np.allclose(x1, [.5, .25])


def test_part_notes_takes_top_of_a_chord():
    sc = score.parse('== 1\nTEN: c4+e4+g4/h=Ah d4/h\n', warn=quiet)
    assert timing.part_notes(sc, 'T1') == [(0., 2., 67), (2., 2., 62)]


def test_near_is_octave_blind():
    m = np.array([60., 72.3, 61., 59.5, 48.6, np.nan])
    assert timing._near(m, 60).tolist() == [True, True, False, True, True, False]


def test_nominal_clock_through_tempo_changes():
    sc = score.parse('tempo: 60\n== 1\nT1: c4/w\ntempo: 120\n== 2\nT1: c4/w\n', warn=quiet)
    b, s = timing.nominal(sc)
    assert b.tolist() == [0., 4., 8.]
    assert s.tolist() == [0., 4., 6.]


def test_nominal_single_tempo(sc):
    b, s = timing.nominal(sc)
    assert b.tolist() == [0., 8.] and s.tolist() == [0., 8.]


def test_wanted_grid():
    w = timing._wanted([(0, 1, 60), (2, .5, 62)], 3, 2)
    assert len(w) == 8
    assert w[:2].tolist() == [60., 60.] and w[4] == 62.
    assert np.isnan(w[[2, 3, 5, 6, 7]]).all()


def test_steady_fit_finds_offset(sc):
    t, m = pitch_track(sc, 1.5)
    agree, beats, secs = timing.steady_fit(timing.part_notes(sc, 'T1'), t, m, timing.nominal(sc))
    assert agree == 1.
    assert beats.tolist() == list(range(9))
    assert secs[0] == pytest.approx(1.5, abs=.03)
    assert np.diff(secs) == pytest.approx(np.ones(8), abs=.01)


def test_follow_steady_recording_stays_steady(sc):
    t, m = pitch_track(sc, 1.5)
    notes = timing.part_notes(sc, 'T1')
    sb, ss = np.arange(9.), np.arange(9.) + 1.5
    beats, secs = timing.follow(notes, sc.beats, t, m, sb, ss)
    assert beats.tolist() == list(range(9))
    assert secs == pytest.approx(ss, abs=.03)


def test_on_pitch_synthetic_singer(sc):
    sr = 22050
    nb, ns = timing.nominal(sc)
    x = np.zeros(int(sr * 11))
    for b, d, mi in timing.part_notes(sc, 'T1'):
        a, z = np.interp([b, b + d], nb, ns) + 1.5
        i = np.arange(int(a * sr), int(z * sr))
        x[i] = .3 * np.sin(2 * np.pi * 440 * 2 ** ((mi - 69) / 12) * i / sr)
    beats = np.arange(9.)
    assert timing.on_pitch(sc, 'T1', x, sr, beats, beats + 1.5) == pytest.approx(1.)
    assert timing.on_pitch(sc, 'T1', x, sr, beats, beats + 2.1) < .7


def test_piano_attacks_weighted_by_notes_struck():
    sc = score.parse('== 1\nRH: c4+e4/h c4/h\nLH: c3/w\n', warn=quiet)
    ob, ow = timing._piano_attacks(sc)
    assert ob.tolist() == [0., 2.]
    assert ow == pytest.approx([np.sqrt(3), 1.])


def test_path_follows_a_constant_best_lag():
    E = np.zeros((6, 11)); E[:, 7] = 1.
    lags = np.arange(-5, 6) * .1
    lag, slope = timing._path(E, lags, 2)
    assert lag == pytest.approx([.2] * 6)
    assert slope == 0


def test_flux_peaks_at_a_click():
    sr = 22050
    y = np.zeros(sr * 2)
    y[sr:sr + 200] = np.random.default_rng(0).standard_normal(200)
    tt, fl = timing._flux(y, sr)
    assert len(tt) == len(fl)
    assert tt[np.argmax(fl)] == pytest.approx(1., abs=.06)


def test_sync_report():
    assert timing.sync_report([]) == 'voices against the accompaniment: nothing clear enough to say'
    assert timing.sync_report([(1, 0., False)]) == 'voices against the accompaniment: nothing clear enough to say'
    line = timing.sync_report([(1, 0., True), (3, .1, True), (5, .0, False)])
    assert line == 'voices against the accompaniment: within 60 ms in 1 of 2 stretches; off at measures 3 (+100 ms)'


def test_from_accompaniment_needs_a_written_piano_part(sc):
    with pytest.raises(SystemExit):
        timing.from_accompaniment(sc, np.zeros(22050), 22050, log=quiet)
