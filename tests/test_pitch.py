"""choral/pitch.py: the YIN pitch tracker used to check what the engine sings."""
import numpy as np
import pytest

from choral import pitch

SR = 44100


def tone(f0, secs=.5, harmonics=1, sr=SR):
    t = np.arange(int(secs * sr)) / sr
    return sum(np.sin(2 * np.pi * k * f0 * t) / k for k in range(1, harmonics + 1))


def hz_to_midi(f):
    return 69 + 12 * np.log2(f / 440)


@pytest.mark.parametrize('f0', [82.41, 110., 220., 329.63, 440.])
def test_pure_tone_pitch(f0):
    t, midi = pitch.yin(tone(f0), SR)
    assert np.isfinite(midi).all()
    assert np.nanmedian(midi) == pytest.approx(hz_to_midi(f0), abs=.05)


@pytest.mark.parametrize('f0', [98., 196.])
def test_harmonic_rich_tone_is_not_an_octave_off(f0):
    # a sawtooth-like tone with strong upper partials: YIN must still return the fundamental
    t, midi = pitch.yin(tone(f0, harmonics=12), SR)
    assert np.nanmedian(midi) == pytest.approx(hz_to_midi(f0), abs=.1)


def test_silence_is_unvoiced():
    t, midi = pitch.yin(np.zeros(SR // 2), SR)
    assert len(midi) > 0 and np.isnan(midi).all()


def test_white_noise_is_mostly_unvoiced():
    x = np.random.default_rng(0).standard_normal(SR // 2)
    t, midi = pitch.yin(x, SR)
    assert np.isnan(midi).mean() > .9


def test_frame_times_and_count():
    x = tone(220., secs=1.)
    win, hop = 1024, 256
    t, midi = pitch.yin(x, SR, win=win, hop=hop)
    tmax = int(SR / 65.)
    n = (len(x) - win - tmax) // hop
    assert len(t) == len(midi) == n
    assert t[0] == pytest.approx(win / 2 / SR)
    assert np.allclose(np.diff(t), hop / SR)


def test_tracks_a_pitch_change_in_time():
    x = np.concatenate([tone(150., .5), tone(300., .5)])
    t, midi = pitch.yin(x, SR)
    early = midi[t < .4]
    late = midi[t > .65]
    assert np.nanmedian(early) == pytest.approx(hz_to_midi(150.), abs=.1)
    assert np.nanmedian(late) == pytest.approx(hz_to_midi(300.), abs=.1)


def test_tone_followed_by_silence():
    x = np.concatenate([tone(200., .5), np.zeros(SR // 2)])
    t, midi = pitch.yin(x, SR)
    assert np.isfinite(midi[t < .4]).all()
    assert np.isnan(midi[t > .6]).all()


def test_outside_search_range_is_not_reported_in_range():
    # 1000 Hz lies above fmax=520: whatever is reported must not be 1000 Hz itself
    t, midi = pitch.yin(tone(1000.), SR)
    v = midi[np.isfinite(midi)]
    assert not np.any(np.abs(v - hz_to_midi(1000.)) < .5)


def test_custom_range_and_sample_rate():
    sr = 22050
    t, midi = pitch.yin(tone(600., sr=sr), sr, fmin=300., fmax=900., win=512, hop=128)
    assert np.nanmedian(midi) == pytest.approx(hz_to_midi(600.), abs=.1)


def test_long_input_is_processed_in_blocks():
    # more than 2000 frames: the block loop must cover all of them
    x = tone(130.81, secs=13.)
    t, midi = pitch.yin(x, SR)
    assert len(midi) > 2000
    assert np.isfinite(midi).all()
    assert np.abs(midi - hz_to_midi(130.81)).max() < .1
