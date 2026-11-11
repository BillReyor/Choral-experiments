"""A small physical-ish piano: inharmonic partials that die away at their own rates, two strings
per note beating gently against each other, and a felt-hammer thump."""
import numpy as np

SR = 44100


def note(midi, dur, vel, rng):
    """One note as a mono array.  dur is how long the key is held (seconds); vel is 0..1."""
    f0 = 440 * 2 ** ((midi - 69) / 12)
    ring = min(6.0, 1.2 + 14 * 2 ** (-(midi - 36) / 14))     # low strings ring longer
    n = int((min(dur, ring) + .35) * SR)
    t = np.arange(n) / SR
    B = 7e-5 * 2 ** ((midi - 40) / 16)                       # string stiffness
    sig = np.zeros(n)
    bright = 2.3 - 1.1 * vel                                 # a harder hit excites more partials
    for k in range(1, 40):
        fk = k * f0 * np.sqrt(1 + B * k * k)
        if fk > 9000:
            break
        a = k ** -bright * (1 - .6 * np.exp(-k / 1.5) * (midi > 84))
        fast = (1.5 + .35 * k) * (f0 / 130) ** .5            # two-stage decay
        env = .7 * np.exp(-t * fast) + .3 * np.exp(-t * fast * .22)
        ph = rng.uniform(0, 6.28, 2)
        det = rng.normal(0, .0004)
        sig += a * env * (np.sin(2 * np.pi * fk * t + ph[0]) + np.sin(2 * np.pi * fk * (1 + det) * t + ph[1])) * .5
    thump = rng.standard_normal(n) * np.exp(-t / .004)       # hammer
    k = int(SR / max(2 * f0, 400))
    thump = np.convolve(thump, np.ones(k) / k, 'same')
    sig += .25 * vel * thump
    sig[:int(.002 * SR)] *= np.linspace(0, 1, int(.002 * SR))
    off = int(dur * SR)                                      # damper falls when the key is released
    if off < n:
        sig[off:] *= np.exp(-np.arange(n - off) / (.09 * SR))
    return sig * (.25 + .75 * vel ** 1.6)


def render(notes, n_samples, T, dyn, seed=1):
    """notes: dicts with beat, dur (beats), midi, flags.  T maps beats to seconds; dyn(beat) -> 0..1."""
    rng = np.random.default_rng(seed)
    out = np.zeros((n_samples, 2))
    for nt in notes:
        t0, t1 = T(nt['beat']), T(nt['beat'] + nt['dur'])
        dur = (t1 - t0) * (.45 if "'" in nt['flags'] else 1.)
        vel = float(np.clip(dyn(nt['beat']) * .8 + (.14 if '>' in nt['flags'] else 0) + rng.normal(0, .02), .1, 1))
        sig = note(nt['midi'], dur, vel, rng)
        i0 = int((t0 + rng.normal(0, .004)) * SR)
        if i0 < 0 or i0 >= n_samples:
            continue
        sig = sig[:n_samples - i0]
        th = (np.clip((nt['midi'] - 60) / 48, -.6, .6) + 1) * np.pi / 4      # bass left, treble right
        out[i0:i0 + len(sig), 0] += sig * np.cos(th)
        out[i0:i0 + len(sig), 1] += sig * np.sin(th)
    return out
