"""Render a score to audio: the choir, its accompaniment, and versions for learning one part.

    python -m choral.render SCORE.score OUT.wav [--voices VOICES.wav] [--per-section 12]

(`python -m choral` is the full program; this is the plain renderer.)  Singers stand on risers in
front of a stereo microphone pair; two leaders per section are also on close mics, which is what
carries the words.  Every section is kept on its own stem so one part can be brought forward,
left out, or heard alone.
"""
import argparse, os, time, wave
import numpy as np
from multiprocessing import Pool, cpu_count
from scipy.signal import fftconvolve, butter, sosfilt
from . import voice, piano, score as scoremod

SR = voice.SR
_E = lambda k, d: float(os.environ.get(k, d))
PRESET = dict(                         # what differs from piece to piece (see choral/presets.py)
    spot=_E('CHORAL_SPOT', 1.8),       # level of the section leaders' close mics over the choir
    hall=_E('CHORAL_HALL', .14),       # hall reverb on the choir (more than the text can stand smears it)
    hall_rt=_E('CHORAL_RT', 1.6),      # how long the hall rings (seconds)
    pres=_E('CHORAL_PRES', .6),        # presence lift (2-6 kHz) on the vocal bus
    backing=_E('CHORAL_PIANO', .22),   # accompaniment level relative to the choir at full voice
    others=.2,                         # the other parts, in a "my part predominant" version
    under=.5,                          # the accompaniment, in that version (relative to the balanced mix)
    singers=12,                        # per section
)
LEAD_IN = 1.0   # seconds of room before the first beat
NAMES = {'T1': 'Tenor 1', 'T2': 'Tenor 2', 'BR': 'Baritone', 'BS': 'Bass'}


def clock_for(sc, timing=None, absolute=False):
    """Beat -> second map.  From a measured timing (the score's own `timing:` file, or one passed in)
    when there is one, else from the tempo marks.  absolute=True keeps a measured map on the
    recording's own clock, so the voices line up with an accompaniment track; otherwise the first
    beat is placed LEAD_IN seconds in."""
    timing = timing or sc.timing
    if timing and timing.get('beats'):
        beats, secs = np.array(timing['beats'], float), np.array(timing['secs'], float)
    elif timing:
        beats = np.array([0., sc.beats]); secs = timing['offset'] + beats * 60 / timing['bpm']
    else:
        pts = sorted(sc.tempo)
        beats, secs = [0.], [LEAD_IN]
        bpm = pts[0][1]
        for b, new in pts + [(sc.beats, pts[-1][1])]:
            if b > beats[-1]:
                secs.append(secs[-1] + (b - beats[-1]) * 60 / bpm); beats.append(b)
            bpm = new
        beats, secs = np.array(beats), np.array(secs)
    if timing and not absolute:
        secs = secs - secs[0] + LEAD_IN
    slope = (secs[-1] - secs[-2]) / (beats[-1] - beats[-2])
    return np.append(beats, beats[-1] + 16), np.append(secs, secs[-1] + 16 * slope)


def engine_notes(sc, part):
    """Score notes -> engine notes (beat, beats, midi, phonemes, dynamic), expanding slides."""
    notes, out = sc.parts[part], []
    for i, n in enumerate(notes):
        dy = sc.dyn('voice', n['beat'])
        if '%gl' in n['flags'] and i + 1 < len(notes) and n['dur'] > 1:
            nxt = notes[i + 1]['midi']
            a = np.array(n['midi'] if isinstance(n['midi'], tuple) else (n['midi'],), float)
            b = np.array(nxt if isinstance(nxt, tuple) else (nxt,), float)
            out.append((n['beat'], n['dur'] - 1, n['midi'], n['phon'], dy))
            for k in range(1, 6):          # glide through the last beat
                m = tuple(a + (b.mean() - a) * k / 6) if len(a) > 1 else float(a[0] + (b.mean() - a[0]) * k / 6)
                out.append((n['beat'] + n['dur'] - 1 + (k - 1) / 5, .2, m, '-', sc.dyn('voice', n['beat'] + n['dur'] - 1)))
        else:
            out.append((n['beat'], n['dur'], n['midi'], n['phon'], dy))
    return out


def make_ir(seed, rt_lo, rt_hi):
    r = np.random.default_rng(seed)
    n = int(2.6 * SR)
    t = np.arange(n) / SR
    x = r.normal(0, 1, n)
    lo = sosfilt(butter(2, 1200, 'low', fs=SR, output='sos'), x)
    hi = sosfilt(butter(2, [1200, 10000], 'bandpass', fs=SR, output='sos'), x)
    ir = (lo * np.exp(-6.91 * t / rt_lo) + .8 * hi * np.exp(-6.91 * t / rt_hi)) * np.clip(t / .04, 0, 1) ** 1.5
    for tt, g in zip(r.uniform(.006, .06, 7), np.linspace(.9, .3, 7)):
        ir[int(tt * SR)] += g * r.choice([-1, 1]) * 12
    ir = np.concatenate([np.zeros(int(.015 * SR)), ir])
    return ir / np.sqrt((ir ** 2).sum())


def write_wav(path, x):
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())


def loud(x):
    """Level of the loudest stretches (90th percentile of one-second powers)."""
    p = (x ** 2).mean(1)
    blk = p[:len(p) // SR * SR].reshape(-1, SR).mean(1)
    return float(np.sqrt(np.percentile(blk, 90)) + 1e-12)


def sing(sc, clock, singers=12, log=print):
    """Every singer of every section -> {section: array (3, N, 2)}: what the main microphone pair
    hears, what goes to the hall, and the leaders' close mics."""
    t0 = time.time()
    voice.set_clock(*clock)
    voice.PER_SECTION = singers
    N = voice.CLOCK['n']
    tasks = [(sect, i, engine_notes(sc, sect), clock) for sect in voice.SECT for i in range(singers) if sc.parts[sect]]
    stems = {sect: np.zeros((3, N, 2), np.float32) for sect in voice.SECT if sc.parts[sect]}
    geo = np.random.default_rng(99)
    with Pool(min(10, cpu_count())) as pool:
        for sect, x, y, star, mono in pool.imap_unordered(voice.render_singer, tasks):
            dry, send, spot = stems[sect]
            for c, (mx, aim) in enumerate(((-.35, 125.), (.35, 55.))):       # two cardioids, angled apart
                d = np.hypot(x - mx, y)
                g = (.5 + .5 * np.cos(np.arctan2(y, x - mx) - np.deg2rad(aim))) / d
                k = int((d - 2.6) / 343 * SR)                                # time of flight to this mic
                dry[k:, c] += g * mono[:N - k]
                k2 = k + int(geo.uniform(.002, .007) * SR)                   # one early bounce
                dry[k2:, c] += .3 * g * mono[:N - k2]
                send[k:, c] += (.6 if (x < 0) == (c == 0) else .4) * mono[:N - k]
            if star:
                th = (np.clip(x / 4.5, -1, 1) * .6 + 1) * np.pi / 4
                spot[:, 0] += mono * np.cos(th); spot[:, 1] += mono * np.sin(th)
    log('voices sung in %.0fs' % (time.time() - t0))
    return stems


def hall_of(P, N):
    irs = [make_ir(100, P['hall_rt'], P['hall_rt'] * .63), make_ir(101, P['hall_rt'], P['hall_rt'] * .63)]
    return lambda x: np.stack([fftconvolve(x[:, c], irs[c])[:N] for c in range(2)], axis=1)


def mix_voices(stems, P, only=None):
    """Stems -> {section: stereo}, each section placed in the same hall at the same gains, so the
    sections add up to the full choir exactly.  only=[...] mixes just those sections (still at the
    full choir's gains)."""
    N = next(iter(stems.values())).shape[1]
    hall = hall_of(P, N)
    tot = sum(stems.values())
    Ld, Ls, Lsp = loud(tot[0]), loud(tot[1]), loud(tot[2])
    pres = butter(1, [2000, 6000], 'bandpass', fs=SR, output='sos')

    def place(dry, send, spot):
        sp = P['spot'] * spot / Lsp
        v = .7 * dry / Ld + sp + hall(P['hall'] * send / Ls + .2 * sp)
        return v + P['pres'] * sosfilt(pres, v, axis=0)
    L = loud(place(*tot))
    return {k: place(*stems[k]) / L for k in (only or stems)}


def choir(stems, P):
    """The whole choir as one stereo mix (cheaper than mixing each section when no part is singled out)."""
    return mix_voices({'all': sum(stems.values())}, P)['all']


def backing(sc, N, T, P, track=None):
    """The accompaniment at unit loudness: a recording if one is given, else the score's piano."""
    if track is not None:
        x = np.zeros((N, 2)); x[:min(N, len(track))] = track[:N]
    elif sc.piano:
        p = piano.render(sc.piano, N, T, lambda b: sc.dyn('piano', b))
        x = p + .22 * hall_of(P, N)(p)
    else:
        return np.zeros((N, 2))
    return x / loud(x)


def master(x):
    N = len(x)
    tone = sosfilt(butter(1, 500, 'low', fs=SR, output='sos'), np.random.default_rng(3).standard_normal((N, 2)), axis=0)
    x = sosfilt(butter(2, 35, 'high', fs=SR, output='sos'), x + tone / tone.std() * .004, axis=0)   # a hall is never digitally silent
    nf = int(1.5 * SR)
    x[-nf:] *= np.linspace(1, 0, nf)[:, None] ** 2
    x = np.tanh(1.1 * x / np.percentile(np.abs(x), 99.9))
    return x * .93 / np.abs(x).max()


def versions(vox, back, P, part=None):
    """Named mixes.  vox is {section: stereo} (or {'all': stereo}); back is the accompaniment."""
    full = sum(vox.values()); b = P['backing'] * back
    out = {'voices only': full}
    if np.abs(back).max() > 0:
        out['balanced'] = full + b
    if part:
        mine = vox[part]; name = NAMES[part]
        out[f'{name} predominant'] = mine + P['others'] * (full - mine) + P['under'] * b
        out[f'{name} muted'] = full - mine + b
        out[f'{name} alone'] = mine
    return {k: master(v) for k, v in out.items()}


def render(sc, per_section=12, log=print, preset=None):
    """The simple path: (full mix, voices only, clock)."""
    P = dict(PRESET, singers=per_section, **(preset or {}))
    clock = clock_for(sc)
    total = float(np.interp(sc.beats, *clock)) + 4.0
    stems = sing(sc, (*clock, total), P['singers'], log)
    vox = {'all': choir(stems, P)}
    out = versions(vox, backing(sc, len(vox['all']), voice.T, P), P)
    return out.get('balanced', out['voices only']), out['voices only'], (*clock, total)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score'); ap.add_argument('out')
    ap.add_argument('--voices', help='also write the voices without the piano')
    ap.add_argument('--per-section', type=int, default=12)
    a = ap.parse_args()
    sc = scoremod.load(a.score, warn=print)
    print(f'{sc.title or a.score}: {len(sc.measures)} measures, {sc.beats:g} beats, '
          f'{sum(len(v) for v in sc.parts.values())} sung notes, {len(sc.piano)} piano notes')
    mix, vox, _ = render(sc, a.per_section)
    write_wav(a.out, mix)
    if a.voices:
        write_wav(a.voices, vox)
    print('wrote', a.out, '%.1fs' % (len(mix) / SR))


if __name__ == '__main__':
    main()
