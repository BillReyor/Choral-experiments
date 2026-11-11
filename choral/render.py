"""Render a score file to audio.

    python -m choral.render SCORE.score OUT.wav [--voices VOICES.wav] [--per-section 12]

Singers stand on risers in front of a stereo microphone pair; two leaders per section are also
on close mics, which is what carries the words.  The piano is beside them in the same hall.
"""
import argparse, os, sys, time, wave
import numpy as np
from multiprocessing import Pool, cpu_count
from scipy.signal import fftconvolve, butter, sosfilt
from . import voice, piano, score as scoremod

SR = voice.SR
_E = lambda k, d: float(os.environ.get(k, d))
SPOT = _E('CHORAL_SPOT', 1.8)     # level of the section leaders' close mics over the choir
HALL = _E('CHORAL_HALL', .14)     # hall reverb on the choir (more than this smears fast text)
HALL_RT = _E('CHORAL_RT', 1.6)    # how long the hall rings (seconds)
PRES = _E('CHORAL_PRES', .6)      # presence lift (2-6 kHz) on the vocal bus
PIANO = _E('CHORAL_PIANO', .22)   # piano level relative to the choir at full voice
LEAD_IN = 1.0   # seconds of room before the first beat


def clock_for(sc):
    """Beat -> second map from the tempo marks."""
    pts = sorted(sc.tempo)
    beats, secs = [0.], [LEAD_IN]
    marks = pts + [(sc.beats + 16, pts[-1][1])]
    bpm = pts[0][1]
    for b, new in marks:
        if b > beats[-1]:
            secs.append(secs[-1] + (b - beats[-1]) * 60 / bpm); beats.append(b)
        bpm = new
    return np.array(beats), np.array(secs)


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


def make_ir(seed, rt_lo=None, rt_hi=None):
    rt_lo = rt_lo or HALL_RT; rt_hi = rt_hi or HALL_RT * .63
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


def render(sc, per_section=12, log=print):
    t0 = time.time()
    beats, secs = clock_for(sc)
    total = float(np.interp(sc.beats, beats, secs)) + 4.0
    clock = (beats, secs, total)
    voice.set_clock(*clock)
    voice.PER_SECTION = per_section
    N = voice.CLOCK['n']
    T = voice.T

    tasks = [(sect, i, engine_notes(sc, sect), clock) for sect in voice.SECT for i in range(per_section)
             if sc.parts[sect]]
    dry, send, spot = np.zeros((N, 2)), np.zeros((N, 2)), np.zeros((N, 2))
    geo = np.random.default_rng(99)
    with Pool(min(10, cpu_count())) as pool:
        for sect, x, y, star, mono in pool.imap_unordered(voice.render_singer, tasks):
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
    log('voices rendered in %.0fs' % (time.time() - t0))

    irs = [make_ir(100), make_ir(101)]

    def hall(x):
        return np.stack([fftconvolve(x[:, c], irs[c])[:N] for c in range(2)], axis=1)

    def loud(x):                                   # level of the loudest stretches
        p = (x ** 2).mean(1)
        blk = p[:len(p) // SR * SR].reshape(-1, SR).mean(1)
        return np.sqrt(np.percentile(blk, 90)) + 1e-12

    vox = .7 * dry / loud(dry) + HALL * hall(send / loud(send))
    sp = spot / loud(spot)
    vox += SPOT * (sp + .2 * hall(sp))
    vox += PRES * sosfilt(butter(1, [2000, 6000], 'bandpass', fs=SR, output='sos'), vox, axis=0)
    vox /= loud(vox)

    pno = np.zeros((N, 2))
    if sc.piano:
        p = piano.render(sc.piano, N, T, lambda b: sc.dyn('piano', b))
        p = p + .22 * hall(p)
        pno = p / loud(p) * PIANO
    tone = sosfilt(butter(1, 500, 'low', fs=SR, output='sos'), np.random.default_rng(3).standard_normal((N, 2)), axis=0)
    room = tone / tone.std() * .004                # a hall is never digitally silent

    def master(x):
        x = sosfilt(butter(2, 35, 'high', fs=SR, output='sos'), x + room, axis=0)
        nf = int(1.5 * SR)
        x[-nf:] *= np.linspace(1, 0, nf)[:, None] ** 2
        x = np.tanh(1.1 * x / np.percentile(np.abs(x), 99.9))
        return x * .93 / np.abs(x).max()

    return master(vox + pno), master(vox), clock


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score'); ap.add_argument('out')
    ap.add_argument('--voices', help='also write the voices without the piano')
    ap.add_argument('--per-section', type=int, default=12)
    a = ap.parse_args()
    sc = scoremod.parse(open(a.score).read())
    print(f'{sc.title or a.score}: {len(sc.measures)} measures, {sc.beats:g} beats, '
          f'{sum(len(v) for v in sc.parts.values())} sung notes, {len(sc.piano)} piano notes')
    mix, vox, _ = render(sc, a.per_section)
    write_wav(a.out, mix)
    if a.voices:
        write_wav(a.voices, vox)
    print('wrote', a.out, '%.1fs' % (len(mix) / SR))


if __name__ == '__main__':
    main()
