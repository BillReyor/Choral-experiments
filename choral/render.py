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
    backing=_E('CHORAL_PIANO', .5),    # accompaniment level relative to the choir at full voice: the middle of seven real practice mixes (0.44-0.94)
    others=.2,                         # the other parts, in a "my part predominant" version
    under=.5,                          # the accompaniment, in that version (relative to the balanced mix)
    singers=12,                        # per section
    note_decay=0.,                     # dB per second each note fades (-12 = bell-like)
    # swell: dB each soft, held note swells in from - set only when measured from a recording; otherwise the
    # voice goes by its own rule (6.5 dB at piano and softer in slow music, nothing in quick music)
    attack=1.,                         # how slowly phrases begin, relative to the rule for their dynamic
    scoop=1.,                          # how far under the note phrases begin, relative to the usual
)
LEAD_IN = 1.0   # seconds of room before the first beat


def tune_of(P):
    """A preset's entries that change how the voice itself sings, as settings for the singers."""
    t = {'TUNE.note_decay': P.get('note_decay', 0.), 'TUNE.attack': P.get('attack', 1.), 'TUNE.scoop': P.get('scoop', 1.)}
    if 'swell' in P:
        t['TUNE.swell'] = P['swell']
    return t

NAMES = {'T1': 'Tenor 1', 'T2': 'Tenor 2', 'BR': 'Baritone', 'BS': 'Bass', 'SOLO': 'Solo',
         'TR1': 'Trio tenor 1', 'TR2': 'Trio tenor 2', 'TR3': 'Trio baritone'}
SINGLE = ('SOLO', 'TR1', 'TR2', 'TR3')    # parts sung by one person
SOLO_GAIN = 3.2                        # one close-miked soloist carries like a section


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
        pts = sorted(sc.tempo, key=lambda t: t[0])     # (of two marks at one place the later one in the file counts)
        holds = [(a, a + n, f) for a, n, f in getattr(sc, 'stretch', []) if n > 0]
        cuts = sorted({0., float(sc.beats)} | {float(b) for b, _ in pts if 0 < b < sc.beats} |
                      {float(min(max(x, 0.), sc.beats)) for a, b, f in holds for x in (a, b)})
        beats, secs = [0.], [LEAD_IN]
        for a, b in zip(cuts, cuts[1:]):               # between two cuts one tempo holds, slowed by every stretch that covers it
            bpm = [v for at, v in pts if at <= a + 1e-9][-1] if any(at <= a + 1e-9 for at, v in pts) else pts[0][1]
            slow = float(np.prod([f for h0, h1, f in holds if h0 <= a + 1e-9 and b <= h1 + 1e-9] or [1.]))
            secs.append(secs[-1] + (b - a) * 60 / bpm * slow); beats.append(b)
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


def sing(sc, clock, singers=12, log=print, tune=None, voices=None):
    """Every singer of every section -> {section: array (3, N, 2)}: what the main microphone pair
    hears, what goes to the hall, and the leaders' close mics.  tune: voice settings for this piece
    (keys as in voice.apply_fit).  voices: recordings of real voices for the singers to be re-voiced in
    (choral/revoice.py), dealt out among the singers of each section in turn."""
    t0 = time.time()
    voice.set_clock(*clock)
    voice.PER_SECTION = singers
    N = voice.CLOCK['n']
    tasks = [(sect, i, engine_notes(sc, sect), clock, tune) for sect in voice.SECT if sc.parts[sect]
             for i in ((1,) if sect in SINGLE else range(singers))]            # singer 1 is a section leader: on a close mic
    stems = {sect: np.zeros((3, N, 2), np.float32) for sect in voice.SECT if sc.parts[sect]}
    geo = np.random.default_rng(99)
    with Pool(min(10, cpu_count())) as pool:
        if voices:                                     # every singer first, then all of them to the voice model together
            from . import revoice
            done = list(pool.imap(voice.render_singer, tasks))
            log('voices sung in %.0fs' % (time.time() - t0))
            order = {s: k for k, s in enumerate(dict.fromkeys(t[0] for t in tasks))}
            given = [voices[(t[1] + order[t[0]]) % len(voices)] for t in tasks]      # neighbours in a section, and the same seat in two sections, differ
            new = revoice.revoice([d[4] for d in done], given, log)
            arriving = [(d[0], d[1], d[2], d[3], m) for d, m in zip(done, new)]
        else:
            arriving = pool.imap_unordered(voice.render_singer, tasks)
        for sect, x, y, star, mono in arriving:
            dry, send, spot = stems[sect]
            if sect in SINGLE:
                mono = mono * (SOLO_GAIN if sect == 'SOLO' else .75 * SOLO_GAIN)
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
    log(('voices sung and re-voiced in %.0fs' if voices else 'voices sung in %.0fs') % (time.time() - t0))
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


def versions(vox, back, P, parts=()):
    """Named mixes.  vox is {section: stereo} (or {'all': stereo}); back is the accompaniment.
    parts is a list of (name, [sections]) to single out, e.g. ('Bass', ['BR', 'BS']) in a TTB piece."""
    full = sum(vox.values()); b = P['backing'] * back
    out = {'voices only': full}
    if np.abs(back).max() > 0:
        out['balanced'] = full + b
    for name, sections in parts:
        mine = sum(vox[s] for s in sections)
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
