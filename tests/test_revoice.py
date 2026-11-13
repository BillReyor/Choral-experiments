"""choral/revoice.py, the parts that do not need the voice-conversion model: who sings in which voice, where a
singer's track is cut into stretches, and how a converted stretch is lined up with and made as loud as its original."""
import wave

import numpy as np
import pytest

from choral import revoice as R

SR = R.SR
NAMES = {'T1': 'tenor 1', 'T2': 'tenor 2', 'BR': 'baritone', 'BS': 'bass 2'}
WRITTEN = {'T1': 62, 'T2': 57, 'BR': 52, 'BS': 47}


@pytest.fixture
def pitches(monkeypatch):
    """Recordings by how low they sing, known without reading any file."""
    known = {'/v/a.wav': 45., '/v/b.wav': 50., '/v/c.wav': 55., '/v/d.wav': 60., '/v/bass 2 - Joe.wav': 40.}
    for k, v in known.items():
        monkeypatch.setitem(R._PITCH, k, v)
    return known


# ---------------------------------------------------------------- names in file names ----
@pytest.mark.parametrize('path, parts, names, part', [
    ('/a/bass 2.wav', list(NAMES), NAMES, 'BS'),
    ('/a/Tenor 1 - Sam.wav', ['T1', 'T2'], NAMES, 'T1'),
    ('/a/tenor1b.wav', ['T1'], NAMES, 'T1'),
    ('/a/Tenor_2_take3.wav', ['T1', 'T2'], NAMES, 'T2'),
    ('/a/BR_x.wav', ['BR'], None, 'BR'),
    ('/a/bassoon.wav', ['BS'], {'BS': 'bass'}, None),       # a word that merely begins with the name
    ('/a/tenor 12.wav', ['T1'], NAMES, None),               # another number
    ('/a/sam.wav', list(NAMES), NAMES, None),
])
def test_asked(path, parts, names, part):
    assert R.asked(path, parts, names) == part


# --------------------------------------------------------------------- seating ----
def test_deal_seats_voices_by_pitch_lowest_to_lowest(pitches):
    seats = [(p, i) for p in WRITTEN for i in range(3)]
    given = R.deal(['/v/d.wav', '/v/a.wav', '/v/c.wav', '/v/b.wav'], seats, WRITTEN, log=lambda *a: None)
    by_part = {p: {f for (q, _), (f, s) in zip(seats, given) if q == p} for p in WRITTEN}
    assert by_part == {'T1': {'/v/d.wav'}, 'T2': {'/v/c.wav'}, 'BR': {'/v/b.wav'}, 'BS': {'/v/a.wav'}}
    # three copies of one recording in a section: made a little larger and smaller so they are not one man three times
    sizes = [s for (q, _), (f, s) in zip(seats, given) if q == 'T1']
    assert sizes == [-0.4, 0.0, 0.4]
    assert all(abs(s) <= R.SPREAD + R.LEAN for f, s in given)


def test_deal_named_recording_and_shared_voice_larger_in_lower_sections(pitches):
    seats = [(p, i) for p in WRITTEN for i in range(3)]
    given = R.deal(['/v/a.wav', '/v/bass 2 - Joe.wav'], seats, WRITTEN, log=lambda *a: None, names=NAMES)
    voice = {(p, i): v for (p, i), v in zip(seats, given)}
    assert all(voice['BS', i][0] == '/v/bass 2 - Joe.wav' for i in range(3))
    assert all(voice[p, i][0] == '/v/a.wav' for p in ('T1', 'T2', 'BR') for i in range(3))
    mean = {p: np.mean([voice[p, i][1] for i in range(3)]) for p in ('T1', 'T2', 'BR')}
    # + is a smaller voice: the one recording serving three sections is smallest in the highest
    assert mean['BR'] < mean['T2'] < mean['T1']
    assert mean['BR'] == pytest.approx(-R.LEAN) and mean['T1'] == pytest.approx(R.LEAN)


def test_deal_solo_part_takes_nearest_voice_as_it_is(pitches):
    seats = [('T1', 0), ('BS', 0), ('BS', 1)]
    given = R.deal(['/v/a.wav', '/v/d.wav', '/v/c.wav'], seats, {'T1': 62, 'BS': 47}, log=lambda *a: None)
    assert given == [('/v/d.wav', 0.0), ('/v/a.wav', 0.0), ('/v/c.wav', 0.0)]


def test_deal_part_without_voice_borrows_nearest(pitches):
    seats = [('T1', 0), ('T1', 1), ('BS', 0), ('BS', 1)]
    given = R.deal(['/v/bass 2 - Joe.wav'], seats, {'T1': 62, 'BS': 47}, log=lambda *a: None, names={'T1': 'tenor 1', 'BS': 'bass 2'})
    assert {f for f, s in given} == {'/v/bass 2 - Joe.wav'}


def test_deal_logs_each_part(pitches):
    said = []
    R.deal(['/v/a.wav', '/v/d.wav'], [('T1', 0), ('BS', 0)], {'T1': 62, 'BS': 47}, log=said.append, names={'T1': 'tenor 1', 'BS': 'bass 2'})
    assert len(said) == 2 and 'tenor 1' in said[0] and 'd' in said[0] and 'bass 2' in said[1]


# ------------------------------------------------------------------ stretches ----
def tone(seconds, f=220., amp=.5):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * f * t)


def test_stretches_silence_has_none():
    assert R.stretches(np.zeros(SR)) == []


def test_stretches_join_short_gaps_and_pad():
    x = np.zeros(6 * SR)
    x[SR:2 * SR] = tone(1)
    x[int(2.5 * SR):3 * SR] = tone(.5)              # half a second later: the same stretch
    x[5 * SR:int(5.5 * SR)] = tone(.5, amp=.3)       # two seconds later: a stretch of its own
    got = R.stretches(x)
    assert len(got) == 2
    (a0, b0, k0, l0), (a1, b1, k1, l1) = got
    assert (a0, b0) == (k0, l0) and (a1, b1) == (k1, l1)     # not cut: all of it is kept
    assert .55 * SR < a0 < 1. * SR - .25 * SR and 3. * SR + .25 * SR < b0 < 3.45 * SR     # takes about `pad` of the silence around it
    assert 4.5 * SR < a1 < 5 * SR and 5.5 * SR < b1 < 6 * SR


def test_stretches_cut_long_singing_into_pieces():
    x = tone(40, 200, .4)
    got = R.stretches(x)
    assert len(got) >= 3
    kept = [(k, l) for a, b, k, l in got]
    assert kept[0][0] == 0 and kept[-1][1] == len(x)
    assert all(l0 == k1 for (_, l0), (k1, _) in zip(kept, kept[1:]))        # the kept pieces meet exactly
    assert all(l - k <= R.HARD * SR for k, l in kept)
    for a, b, k, l in got:                                                  # each handed over with some context
        assert a <= k and l <= b and (k - a) <= .3 * SR + 1 and (b - l) <= .3 * SR + 1
    assert any(k - a > 0 for a, b, k, l in got)


def test_stretches_cut_at_a_quiet_moment():
    x = np.concatenate([tone(10), np.zeros(int(.4 * SR)), tone(10)])     # a breath after ten seconds
    x = np.concatenate([x, tone(.01)])
    got = R.stretches(x, gap=1.5)
    assert len(got) == 2
    cut = got[0][3]
    assert 10 * SR <= cut <= 10.4 * SR


# ---------------------------------------------------------------- line up, loudness ----
def bursts(seed=0):
    rng = np.random.default_rng(seed)
    env = np.zeros(2 * SR)
    for s in (.2, .7, 1.3):
        env[int(s * SR):int((s + .3) * SR)] = 1
    return rng.standard_normal(2 * SR) * env * .3


def residual_lag(out, src, reach=4 * R.HOP):
    """The shift (samples) that best lines `out` up with `src`, and how well it then matches."""
    best = max(range(-reach, reach + 1), key=lambda s: float(np.dot(np.roll(out, -s), src)))
    return best, float(np.corrcoef(np.roll(out, -best), src)[0, 1])


@pytest.mark.parametrize('delay', [13 * R.HOP, -9 * R.HOP, 700, -300])
def test_fit_lines_up_and_matches_loudness(delay):
    """Lined up to within one step of the loudness comparison (HOP samples, 1.5 ms), and as loud as the original."""
    src = bursts()
    d = delay
    y = .1 * (np.r_[np.zeros(d), src[:-d]] if d > 0 else np.r_[src[-d:], np.zeros(-d)])    # late (or early), and quieter
    before, _ = residual_lag(y, src, reach=1000)
    assert before == d
    out = R._fit(y, src)
    assert len(out) == len(src)
    after, match = residual_lag(out, src)
    assert abs(after) <= R.HOP and match > .99
    assert np.sqrt(np.mean(out ** 2) / np.mean(src ** 2)) == pytest.approx(1, abs=.05)


def test_fit_pads_short_result_and_fades_ends():
    src = bursts()
    src[:] += .2 * np.random.default_rng(1).standard_normal(len(src))    # sound at the very ends too
    out = R._fit(src[:SR].copy(), src)
    assert len(out) == len(src)
    assert out[0] == 0 and out[-1] == 0


def test_fit_follows_the_original_moment_by_moment():
    src = bursts()
    y = .3 * np.random.default_rng(5).standard_normal(len(src))           # the model's own idea of loudness: always on
    out = R._fit(y, src)
    quiet = slice(int(1.85 * SR), int(1.95 * SR))                         # well inside the silence after the last burst
    loud = slice(int(1.35 * SR), int(1.55 * SR))
    assert np.sqrt(np.mean(out[quiet] ** 2)) < .03 * np.sqrt(np.mean(out[loud] ** 2))
    assert np.sqrt(np.mean(out[loud] ** 2)) == pytest.approx(np.sqrt(np.mean(src[loud] ** 2)), rel=.25)


# ------------------------------------------------------------------ files ----
def test_write_read_roundtrip(tmp_path):
    x = tone(.5, 330, .6)
    p = str(tmp_path / 'x.wav')
    R._write(p, x)
    assert R._plain(p) and not R._floats(p)
    y = R._read(p)
    assert len(y) == len(x) and np.max(np.abs(y - x)) < 1e-4


def test_read_24_bit_stereo_and_resamples(tmp_path):
    x = tone(.5, 220, .5)
    q = np.round(x * 2 ** 23).astype(np.int32)
    raw = np.stack([q & 0xFF, (q >> 8) & 0xFF, (q >> 16) & 0xFF], 1).astype(np.uint8)
    frames = np.repeat(raw[:, None, :], 2, axis=1).tobytes()                 # both channels the same
    p = str(tmp_path / 'x24.wav')
    with wave.open(p, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(3); w.setframerate(SR); w.writeframes(frames)
    assert not R._plain(p)
    y = R._read(p)
    assert np.max(np.abs(y - x)) < 1e-5
    p2 = str(tmp_path / 'x22.wav')
    R._write(p2, x[::2], sr=SR // 2)
    assert len(R._read(p2)) == pytest.approx(len(x), abs=2)


def test_sized_keeps_plain_short_recording_and_resizes_others(tmp_path):
    ref = str(tmp_path / 'ref.wav')
    R._write(ref, tone(2))
    made = {}
    assert R._sized(ref, 0., str(tmp_path), made) == str(ref)
    bigger = R._sized(ref, -1., str(tmp_path), made)                         # a larger voice: played slower, so longer
    assert bigger != ref and bigger.startswith(str(tmp_path))
    assert len(R._read(bigger)) == pytest.approx(2 * SR * 2 ** (1 / 12), rel=.01)
    assert R._sized(ref, -1., str(tmp_path), made) == bigger                 # made once
    long_ = str(tmp_path / 'long.wav')
    R._write(long_, tone(R.VOICE_SECONDS + 3))
    cut = R._sized(long_, 0., str(tmp_path), made)
    assert len(R._read(cut)) == int(R.VOICE_SECONDS * SR)


def test_command_none_without_setup(tmp_path, monkeypatch):
    monkeypatch.setenv('CHORAL_REVOICE', str(tmp_path / 'missing.json'))
    assert R.command() is None
    f = tmp_path / 'cmd.json'
    f.write_text('["/no/such/python", "/no/such/driver.py"]')
    monkeypatch.setenv('CHORAL_REVOICE', str(f))
    assert R.command() is None


def test_revoice_refuses_without_model(monkeypatch):
    monkeypatch.setattr(R, 'command', lambda: None)
    with pytest.raises(SystemExit, match='No voice-conversion model'):
        R.revoice([np.zeros(SR)], ['/v/a.wav'])


def test_kept_depends_on_inputs(tmp_path):
    a, b = str(tmp_path / 'a.wav'), str(tmp_path / 'b.wav')
    R._write(a, tone(.1)); R._write(b, tone(.1, 300))
    job = dict(source=a, reference=b, out='x', seed=0)
    k = R._kept(job, ['m'])
    assert k == R._kept(dict(job, out='elsewhere'), ['m'])             # where it is written does not matter
    assert k != R._kept(dict(job, seed=1), ['m'])
    assert k != R._kept(job, ['other model'])
    assert k != R._kept(dict(job, reference=a), ['m'])
    assert k.startswith(R.CACHE) and k.endswith('.wav')
