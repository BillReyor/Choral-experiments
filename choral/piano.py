"""A physically-motivated piano: stiff strings struck by a felt hammer, two or three strings per
note beating against each other, a two-stage decay, a soundboard colour, and a player who voices
chords, leans on the beat and uses the sustain pedal.  tools/fit.py fits FIT to a recording."""
import os
import numpy as np

SR = 44100

FIT = dict(
    bright0=2.3,      # how fast the partials fall away on a soft note (higher = duller)
    bright_vel=1.1,   # how much a harder strike brightens the tone
    strike=.12,       # where the hammer hits the string (fraction of its length): thins every 1/strike-th partial
    dec0=1.5, dec_k=.35,          # decay of the first partial, and how much faster each higher one dies
    slow_frac=.3, slow_rate=.22,  # the long "aftersound" of a piano note
    stiff=1.0,        # string stiffness (inharmonicity)
    detune=1.0,       # spread between the strings of one note
    thump=.25, thump_ms=4.,       # hammer knock
    release=.09,      # how quickly the damper stops a string
    vel_exp=1.6,      # loudness range between soft and loud playing
    sustain=.0,       # beats of pedal: how long a note rings past its written length
    top=.12, bass=.08,            # voicing: the top note of a chord and the bass sing out
    accent=.10,       # a little extra weight on the beat
    eq=((90, 0.), (220, 0.), (500, 0.), (1100, 0.), (2400, 0.), (5000, 0.), (9000, 0.)),   # soundboard + microphone
)


def apply_fit(P):
    """Install fitted settings, e.g. {"P.dec0": .84, "PEQ.2": 6}."""
    eq = list(FIT['eq'])
    for k, v in P.items():
        if k.startswith('P.'):
            FIT[k[2:]] = v
        elif k.startswith('PEQ.'):
            eq[int(k[4:])] = (eq[int(k[4:])][0], v)
    FIT['eq'] = tuple(eq)


_fit_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'piano_fit.json')
if os.path.exists(_fit_file) and not os.environ.get('CHORAL_NOFIT'):     # settings found by tools/fit.py
    import json
    apply_fit(json.load(open(_fit_file)))

LEAD = .12            # how far an instrument's line (IN:) stands forward: as much as the top note of a chord does

def note(midi, dur, vel, rng):
    """One note as a mono array.  dur is how long the string is left undamped (seconds); vel is 0..1."""
    f0 = 440 * 2 ** ((midi - 69) / 12)
    ring = min(7.0, 1.2 + 14 * 2 ** (-(midi - 36) / 14))     # low strings ring longer
    n = int((min(dur, ring) + .4) * SR)
    t = np.arange(n) / SR
    B = 7e-5 * FIT['stiff'] * 2 ** ((midi - 40) / 16)
    sig = np.zeros(n)
    slope = FIT['bright0'] - FIT['bright_vel'] * vel
    strings = 1 if midi < 36 else 2 if midi < 52 else 3
    for k in range(1, 48):
        fk = k * f0 * np.sqrt(1 + B * k * k)
        if fk > 10000:
            break
        a = k ** -slope * (.25 + abs(np.sin(np.pi * k * FIT['strike'])))
        fast = (FIT['dec0'] + FIT['dec_k'] * k) * (f0 / 130) ** .5
        env = (1 - FIT['slow_frac']) * np.exp(-t * fast) + FIT['slow_frac'] * np.exp(-t * fast * FIT['slow_rate'])
        part = np.zeros(n)
        for s in range(strings):
            det = rng.normal(0, .0004 * FIT['detune']) if strings > 1 else 0.
            part += np.sin(2 * np.pi * fk * (1 + det) * t + rng.uniform(0, 6.28))
        sig += a * env * part / strings
    m = max(8, int(FIT['thump_ms'] * 1e-3 * SR))
    thump = rng.standard_normal(n) * np.exp(-t / (FIT['thump_ms'] * 1e-3))
    k = int(SR / max(2 * f0, 400))
    sig += FIT['thump'] * vel * np.convolve(thump, np.ones(k) / k, 'same')
    sig[:int(.002 * SR)] *= np.linspace(0, 1, int(.002 * SR))
    off = int(dur * SR)                                      # the damper falls
    if off < n:
        sig[off:] *= np.exp(-np.arange(n - off) / (FIT['release'] * SR))
    return sig * (.2 + .8 * vel ** FIT['vel_exp'])


def render(notes, n_samples, T, dyn, seed=1):
    """notes: dicts with beat, dur (beats), midi, flags.  T maps beats to seconds; dyn(beat) -> 0..1."""
    rng = np.random.default_rng(seed)
    out = np.zeros((n_samples, 2))
    by_beat = {}
    for nt in notes:
        by_beat.setdefault(round(nt['beat'] * 96), []).append(nt['midi'])
    next_same = {}
    for nt in sorted(notes, key=lambda n: -n['beat']):
        nt['_next'] = next_same.get(nt['midi'])
        next_same[nt['midi']] = nt['beat']
    for nt in notes:
        chord = by_beat[round(nt['beat'] * 96)]
        hold = nt['dur'] * (.45 if "'" in nt['flags'] else 1.)
        if "'" not in nt['flags']:
            hold += FIT['sustain']                                   # pedal
        if nt['_next'] is not None:
            hold = min(hold, nt['_next'] - nt['beat'] - .02)         # the same key struck again
        t0, t1 = T(nt['beat']), T(nt['beat'] + max(hold, .08))
        vel = dyn(nt['beat']) * .8 + (.14 if '>' in nt['flags'] else 0)
        if nt.get('hand') == 'IN':                                   # an instrument's line is the tune where it plays: a little
            vel += LEAD                                              # forward of the chords, which often lie around it
        frac = nt['beat'] % 1
        vel += FIT['accent'] * (1 if frac == 0 and nt['beat'] % 2 == 0 else .4 if frac == 0 else -.3)
        if len(chord) > 1:                                           # voicing
            vel += FIT['top'] * (nt['midi'] == max(chord)) + FIT['bass'] * (nt['midi'] == min(chord)) - .04
        vel = float(np.clip(vel + rng.normal(0, .025), .08, 1))
        sig = note(nt['midi'], t1 - t0, vel, rng)
        roll = .004 * sorted(chord).index(nt['midi']) if len(chord) > 2 else 0.   # fingers never land exactly together
        i0 = int((t0 + roll + rng.normal(0, .004)) * SR)
        if i0 < 0 or i0 >= n_samples:
            continue
        sig = sig[:n_samples - i0]
        th = (np.clip((nt['midi'] - 60) / 48, -.6, .6) + 1) * np.pi / 4      # bass left, treble right
        out[i0:i0 + len(sig), 0] += sig * np.cos(th)
        out[i0:i0 + len(sig), 1] += sig * np.sin(th)
    hz, db = zip(*FIT['eq'])
    if any(db):
        f = np.fft.rfftfreq(n_samples, 1 / SR)
        g = 10 ** (np.interp(np.log(np.maximum(f, 20.)), np.log(hz), db) / 20)
        out = np.stack([np.fft.irfft(np.fft.rfft(out[:, c]) * g, n_samples) for c in range(2)], axis=1)
    return out
