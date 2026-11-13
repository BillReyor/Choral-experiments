"""choral/reference.py: subtracting the tracks of a learning-track set from one another, on made-up signals.

The signals are short noise "recordings" (stereo, 44.1 kHz); tempo 60, so one beat is one second."""
import types
import wave

import numpy as np
import pytest

from choral import reference as R

SR = R.SR


def noise(seconds, seed, on=None):
    rng = np.random.default_rng(seed)
    x = .1 * rng.standard_normal((int(seconds * SR), 2))
    if on is not None:
        m = np.zeros(len(x))
        for a, b in on:
            m[int(a * SR):int(b * SR)] = 1
        x *= m[:, None]
    return x


def corr(a, b):
    return float(np.corrcoef(np.ravel(a), np.ravel(b))[0, 1])


def test_gain_and_db():
    x = noise(1, 0)
    assert R._gain(.7 * x, x, slice(0, SR)) == pytest.approx(.7)
    assert R._gain(.7 * x + noise(1, 1), x, slice(0, SR)) == pytest.approx(.7, abs=.02)
    assert R._db(np.ones(10)) == pytest.approx(0, abs=1e-9)
    assert R._db(.1 * np.ones(10)) == pytest.approx(-20)
    assert R._db(np.zeros(10)) == pytest.approx(-120)


# ------------------------------------------------------------- the set of tracks ----
LEN = 12                                       # seconds = beats
T1 = [(5, 6.5), (10.5, 12)]                    # the part: silent from 6.5 to 10.5 while the others sing
OTHERS = [(5, 12)]


@pytest.fixture
def tracks():
    acc = noise(LEN, 1)
    part = noise(LEN, 2, T1)
    others = noise(LEN, 3, OTHERS)
    return dict(acc=acc, part=part, others=others,
                balanced=part + others + .5 * acc,
                muted=others + .5 * acc,
                predominant=part + .5 * others + .4 * acc)


@pytest.fixture
def sc():
    note = lambda a, b: dict(beat=a, dur=b - a)
    return types.SimpleNamespace(parts={'T1': [note(*s) for s in T1], 'BS': [note(*s) for s in OTHERS]}, beats=LEN)


CLOCK = (np.array([0., LEN]), np.array([0., LEN]))


def test_isolate_with_muted_track(tracks, sc):
    said = []
    out = R.isolate(sc, CLOCK, 'T1', tracks['balanced'], tracks['acc'], muted=tracks['muted'], log=said.append)
    assert out['acc_gain'] == pytest.approx(.5, abs=1e-6)
    assert out['clean'] > 60                                           # the same takes: the accompaniment cancels
    assert corr(out['voices'], tracks['part'] + tracks['others']) > .9999
    assert corr(out['accompaniment'], tracks['acc']) > .9999
    assert np.allclose(out['part'], tracks['part'], atol=1e-6)
    assert any('muted' in s for s in said)


def test_isolate_with_predominant_track(tracks, sc):
    out = R.isolate(sc, CLOCK, 'T1', tracks['balanced'], tracks['acc'], predominant=tracks['predominant'], log=lambda *a: None)
    assert corr(out['part'], tracks['part']) > .999
    assert np.sqrt(np.mean(out['part'] ** 2)) == pytest.approx(np.sqrt(np.mean(tracks['part'] ** 2)), rel=.02)


def test_isolate_muted_from_another_take_falls_back_to_predominant(tracks, sc):
    other_take = noise(LEN, 9, OTHERS) * 1.5 + .5 * tracks['acc']       # not the balanced mix without the part
    said = []
    out = R.isolate(sc, CLOCK, 'T1', tracks['balanced'], tracks['acc'], muted=other_take, predominant=tracks['predominant'], log=said.append)
    assert any('not the balanced mix' in s for s in said)
    assert corr(out['part'], tracks['part']) > .999


def test_isolate_different_takes_are_not_trusted(tracks, sc):
    other_acc = noise(LEN, 7)                                           # an accompaniment that is not the one in the mix
    out = R.isolate(sc, CLOCK, 'T1', tracks['balanced'], other_acc, muted=tracks['muted'], log=lambda *a: None)
    assert out['clean'] < 15 and 'part' not in out


def test_isolate_first_pass_without_clock(tracks):
    out = R.isolate(None, None, 'T1', tracks['balanced'], tracks['acc'], muted=tracks['muted'], log=lambda *a: None)
    assert out['acc_gain'] == pytest.approx(.5, abs=.02)
    assert out['clean'] >= 15                                          # found the opening, where only the accompaniment plays
    assert corr(out['part'], tracks['part']) > .99


def test_isolate_uses_shortest_track(tracks, sc):
    short = tracks['muted'][:-SR]
    out = R.isolate(sc, CLOCK, 'T1', tracks['balanced'], tracks['acc'], muted=short, log=lambda *a: None)
    assert len(out['voices']) == len(short) and len(out['part']) == len(short)


# ----------------------------------------------------------------- reading audio ----
def write_wav(path, x, sr):
    x = np.atleast_2d(x.T).T
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(x.shape[1]); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())


def test_load_audio_stereo_wav(tmp_path):
    x = noise(.5, 4)
    write_wav(tmp_path / 's.wav', x, SR)
    y = R.load_audio(str(tmp_path / 's.wav'))
    assert y.shape == x.shape and np.max(np.abs(y - x)) < 1e-4


def test_load_audio_mono_and_resampled(tmp_path):
    t = np.arange(SR // 4) / (SR // 2)
    x = .5 * np.sin(2 * np.pi * 440 * t)
    write_wav(tmp_path / 'm.wav', x, SR // 2)
    y = R.load_audio(str(tmp_path / 'm.wav'))
    assert y.shape == (2 * len(x), 2)
    assert np.array_equal(y[:, 0], y[:, 1])
    spec = np.abs(np.fft.rfft(y[:, 0]))
    assert np.fft.rfftfreq(len(y), 1 / SR)[np.argmax(spec)] == pytest.approx(440, abs=3)


def test_load_audio_other_format_without_converter(tmp_path, monkeypatch):
    monkeypatch.setattr(R.shutil, 'which', lambda name: None)
    with pytest.raises(SystemExit, match='ffmpeg'):
        R.load_audio(str(tmp_path / 'song.mp3'))
