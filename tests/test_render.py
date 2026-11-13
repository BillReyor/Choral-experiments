"""choral/render.py: stems per section, the practice mixes made from them, the clock and the measure map."""
import wave

import numpy as np
import pytest

from choral import render as R, score as scoremod

SR = R.SR
N = 3 * SR
# one test tone per section and one for the accompaniment, all above the 500 Hz of master()'s room tone
FREQ = {'T1': 1100., 'T2': 900., 'BR': 750., 'BS': 600.}
BACK_HZ = 1300.

TINY = """title: Tiny test
tempo: 120
time: 2/4
== 1
TEN: !mf c4/q=la d4/q=la
LOW: c3/h=la
RH: c4+e4+g4/h
LH: c2/h
tempo: 60
== 2
TEN: e4/h=la
LOW: g2/h=la
RH: c4+e4+g4/h
LH: c2/h
"""


def load(tmp_path, text, name='tiny.score'):
    p = tmp_path / name
    p.write_text(text)
    return scoremod.load(str(p))


def sine(hz, n=N, amp=.1):
    t = np.arange(n) / SR
    return amp * np.sin(2 * np.pi * hz * t)


def stems_of(freqs=FREQ, amp=.1):
    """Synthetic stems: each section a steady tone in all three feeds (main pair, hall send, close mics)."""
    out = {}
    for k, hz in freqs.items():
        s = sine(hz, amp=amp)
        out[k] = np.stack([np.stack([s, s], 1)] * 3).astype(np.float32)
    return out


def level(x, hz):
    """Amplitude of one tone in a stereo mix (mid channel, the steady middle of it)."""
    seg = x[SR // 2:3 * SR // 2].mean(1)                  # before the final fade-out
    seg = seg - seg.mean()
    w = np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg * w))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    return float(spec[(f > hz - 8) & (f < hz + 8)].max())


P = dict(R.PRESET)


# ------------------------------------------------------------------ stems and mixes ---------
def test_mix_voices_keeps_sections_separate_and_adds_up():
    st = stems_of()
    vox = R.mix_voices(st, P)
    assert set(vox) == set(FREQ)
    for k, x in vox.items():
        assert x.shape == (N, 2) and np.isfinite(x).all()
        own = level(x, FREQ[k])
        for j, hz in FREQ.items():
            if j != k:
                assert level(x, hz) < 1e-3 * own          # nothing of another section leaks in
    full = R.choir(st, P)
    assert np.allclose(sum(vox.values()), full, atol=1e-6 * np.abs(full).max())


def test_choir_mix_is_at_unit_loudness():
    for amp in (.01, .5):
        assert R.loud(R.choir(stems_of(amp=amp), P)) == pytest.approx(1., rel=1e-6)


def test_mix_voices_only_uses_full_choir_gains():
    st = stems_of()
    every = R.mix_voices(st, P)
    one = R.mix_voices(st, P, only=['BR'])
    assert list(one) == ['BR']
    assert np.allclose(one['BR'], every['BR'])


def test_silent_section_mixes_to_silence():
    st = stems_of()
    st['T2'][:] = 0
    vox = R.mix_voices(st, P)
    assert not np.abs(vox['T2']).max() > 0


def backing_tone():
    b = np.stack([sine(BACK_HZ), sine(BACK_HZ)], 1)
    return b / R.loud(b)


def all_versions(**kw):
    vox = R.mix_voices(stems_of(), P)
    return dict(R.versions(vox, backing_tone(), P, [('Baritone', ['BR'])], **kw)), vox


def test_version_names():
    out, _ = all_versions()
    assert list(out) == ['voices only', 'balanced', 'Baritone predominant', 'Baritone muted', 'Baritone alone']


def test_versions_levels_are_sane():
    out, _ = all_versions()
    for name, x in out.items():
        assert x.shape == (N, 2), name
        assert np.isfinite(x).all(), name
        peak = np.abs(x).max()
        assert .9 < peak <= .93 + 1e-9, name             # mastered to just under full scale: no clipping
        assert np.abs(x[-10:]).max() < 1e-3, name         # faded out at the end


def test_alone_is_just_the_part():
    out, _ = all_versions()
    x = out['Baritone alone']
    me = level(x, FREQ['BR'])
    for k in ('T1', 'T2', 'BS'):
        assert level(x, FREQ[k]) < 1e-3 * me
    assert level(x, BACK_HZ) < 1e-3 * me


def test_muted_leaves_the_part_out():
    out, _ = all_versions()
    x = out['Baritone muted']
    others = min(level(x, FREQ[k]) for k in ('T1', 'T2', 'BS'))
    assert level(x, FREQ['BR']) < 1e-3 * others
    assert level(x, BACK_HZ) > .1 * others             # the accompaniment is still there


def test_predominant_brings_the_part_forward():
    out, _ = all_versions()
    bal, pre = out['balanced'], out['Baritone predominant']
    for k in ('T1', 'T2', 'BS'):
        r_bal = level(bal, FREQ['BR']) / level(bal, FREQ[k])
        r_pre = level(pre, FREQ['BR']) / level(pre, FREQ[k])
        assert r_pre / r_bal == pytest.approx(1 / P['others'], rel=.2)     # the others at 0.2
    # the accompaniment at P['under'] of its balanced level, measured against the part
    b_bal = level(bal, BACK_HZ) / level(bal, FREQ['BR'])
    b_pre = level(pre, BACK_HZ) / level(pre, FREQ['BR'])
    assert b_pre / b_bal == pytest.approx(P['under'], rel=.2)


def test_balanced_has_everyone():
    out, _ = all_versions()
    x, v = out['balanced'], out['voices only']
    for hz in FREQ.values():
        assert level(x, hz) > 0.05 * max(level(x, h) for h in FREQ.values())
    assert level(x, BACK_HZ) > 30 * level(v, BACK_HZ)       # the piano is in balanced, not in voices only (only intermodulation there)


def test_versions_only_one():
    vox = R.mix_voices(stems_of(), P)
    got = list(R.versions(vox, backing_tone(), P, [('Baritone', ['BR'])], only='baritone MUTED'))
    assert [n for n, _ in got] == ['Baritone muted']


def test_versions_without_accompaniment_has_no_balanced():
    vox = R.mix_voices(stems_of(), P)
    names = [n for n, _ in R.versions(vox, np.zeros((N, 2)), P, [('Bass', ['BR', 'BS'])])]
    assert names == ['voices only', 'Bass predominant', 'Bass muted', 'Bass alone']


def test_two_section_group_alone_has_both():
    vox = R.mix_voices(stems_of(), P)
    out = dict(R.versions(vox, backing_tone(), P, [('Bass', ['BR', 'BS'])]))
    x = out['Bass alone']
    assert level(x, FREQ['BR']) > .3 * level(x, FREQ['BS'])
    assert level(x, FREQ['T1']) < 1e-3 * level(x, FREQ['BS'])


# ------------------------------------------------------------------ helpers -----------------
def test_loud_is_level_of_loudest_stretches():
    x = np.zeros((10 * SR, 2))
    x[:SR] = .5                                         # one loud second of ten
    assert R.loud(x) == pytest.approx(np.sqrt(.25 * .1), rel=.05)     # the 90th percentile lies in the quiet seconds' edge
    assert R.loud(np.full((4 * SR, 2), .3)) == pytest.approx(.3, rel=1e-6)


def test_write_wav_roundtrip(tmp_path):
    x = np.stack([np.linspace(-1.5, 1.5, SR), np.zeros(SR)], 1)
    f = tmp_path / 'x.wav'
    R.write_wav(str(f), x)
    with wave.open(str(f)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (2, 2, SR, SR)
        y = np.frombuffer(w.readframes(SR), '<i2').reshape(-1, 2)
    assert y[:, 0].min() == -32767 and y[:, 0].max() == 32767     # clipped to full scale, not wrapped
    assert np.all(np.diff(y[:, 0].astype(int)) >= 0)
    assert not y[:, 1].any()


def test_at_once_respects_choral_workers(monkeypatch):
    monkeypatch.setattr(R, 'cpu_count', lambda: 8)
    monkeypatch.delenv('CHORAL_WORKERS', raising=False)
    assert R.at_once(10) == 8 and R.at_once(3) == 3
    monkeypatch.setenv('CHORAL_WORKERS', '2')
    assert R.at_once(10) == 2
    monkeypatch.setenv('CHORAL_WORKERS', '0')
    assert R.at_once(10) == 1
    monkeypatch.setenv('CHORAL_WORKERS', '64')
    assert R.at_once(10) == 8
    monkeypatch.setenv('CHORAL_WORKERS', 'lots')
    assert R.at_once(10) == 8


def test_tune_of():
    assert R.tune_of({}) == {'TUNE.note_decay': 0., 'TUNE.attack': 1., 'TUNE.scoop': 1.}
    assert R.tune_of({'swell': 3., 'attack': 2.})['TUNE.swell'] == 3.


def test_make_ir_is_unit_energy_and_deterministic():
    a, b = R.make_ir(100, 1.6, 1.), R.make_ir(100, 1.6, 1.)
    assert np.array_equal(a, b)
    assert (a ** 2).sum() == pytest.approx(1.)
    assert not a[:int(.015 * SR)].any()                # pre-delay


# ------------------------------------------------------------------ clock and measures ------
def test_clock_from_tempo_marks(tmp_path):
    sc = load(tmp_path, TINY)
    beats, secs = R.clock_for(sc)
    assert secs[0] == R.LEAD_IN
    T = lambda b: float(np.interp(b, beats, secs))
    assert T(2) - T(0) == pytest.approx(1.)             # two beats at 120
    assert T(4) - T(2) == pytest.approx(2.)             # two beats at 60
    assert T(6) - T(4) == pytest.approx(2.)             # past the end the last tempo goes on
    assert np.all(np.diff(secs) > 0)


def test_clock_from_measured_timing(tmp_path):
    sc = load(tmp_path, TINY)
    timing = {'beats': [0., 2., 4.], 'secs': [5., 6.5, 7.5]}
    b, s = R.clock_for(sc, timing)
    assert s[0] == R.LEAD_IN and s[2] - s[0] == pytest.approx(2.5)
    b, s = R.clock_for(sc, timing, absolute=True)
    assert s[0] == 5.


def test_measure_starts(tmp_path):
    sc = load(tmp_path, TINY)
    assert R.measure_starts(sc, R.clock_for(sc)) == [[1.0, 1], [2.0, 2]]


def test_measure_starts_with_a_repeat(tmp_path):
    sc = load(tmp_path, TINY.replace('time: 2/4', 'time: 2/4\nplay: 1-2 1-2'))
    ms = R.measure_starts(sc, R.clock_for(sc))
    assert [m for _, m in ms] == [1, 2, 1, 2]           # printed numbers, the repeat coming twice
    secs = [s for s, _ in ms]
    assert secs == sorted(secs) and secs[0] == 1.0


def test_measure_starts_demo(demo_score):
    sc = scoremod.load(demo_score)
    ms = R.measure_starts(sc, R.clock_for(sc))
    assert [m for _, m in ms] == [1, 2, 3, 4, 5]
    assert np.allclose(np.diff([s for s, _ in ms]), 4 * 60 / 66, atol=.011)    # 4/4 at 66


def test_engine_notes(tmp_path):
    sc = load(tmp_path, TINY)
    en = R.engine_notes(sc, 'T1')
    assert [(b, d, m) for b, d, m, *_ in en] == [(0., 1., 60), (1., 1., 62), (2., 2., 64)]
    assert all(p == 'l AA' and dy == pytest.approx(.74) for *_, p, dy in en)


# ------------------------------------------------------------------ a real (tiny) render -----
def test_sing_keeps_a_stem_per_section(tmp_path, monkeypatch):
    monkeypatch.setenv('CHORAL_WORKERS', '2')
    sc = load(tmp_path, TINY)
    clock = R.clock_for(sc)
    total = float(np.interp(sc.beats, *clock)) + 2.
    stems = R.sing(sc, (*clock, total), singers=2, log=lambda *a: None)
    assert set(stems) == {'T1', 'T2', 'BR', 'BS'}
    n = int(total * SR)
    for k, s in stems.items():
        assert s.shape == (3, n, 2) and np.isfinite(s).all()
        assert np.abs(s[0]).max() > 0 and np.abs(s[1]).max() > 0
        assert np.abs(s[2]).max() > 0                    # singer 1 of 2 is a leader, on a close mic
    vox = R.mix_voices(stems, R.PRESET)
    back = R.backing(sc, n, lambda b: float(np.interp(b, *clock)), R.PRESET)
    assert R.loud(back) == pytest.approx(1., rel=1e-6)
    out = dict(R.versions(vox, back, R.PRESET, [('Bass', ['BS'])]))
    for x in out.values():
        assert np.isfinite(x).all() and np.abs(x).max() <= .93 + 1e-9
    # the basses' stem holds G2/C3; the tenors' C4-E4: "alone" carries the low part only
    from choral import pitch
    t, m = pitch.yin(out['Bass alone'].mean(1), SR)
    v = m[(t > 1.1) & (t < 4.5)]
    assert np.nanmedian(v) < 52
