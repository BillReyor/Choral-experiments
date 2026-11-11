"""Fit the voice model's tone settings to a recording of a real singer on the same notes.

    python tools/calibrate.py SCORE PART SOLO.wav --offset 1.07 --bpm 100 [--channel 1]

Compares long-term spectra in eight bands and searches the settings in choral.voice.FIT.
"""
import argparse, sys, os, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from choral import score, voice, render as R

BANDS = [(80, 300), (300, 600), (600, 1000), (1000, 2000), (2000, 3000), (3000, 4000), (4000, 6000), (6000, 10000)]


def ltas(x, sr):
    n = 4096 if sr > 30000 else 2048
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::n // 2]
    e = (fr ** 2).mean(1); fr = fr[e > .25 * np.percentile(e, 95)]
    P = (np.abs(np.fft.rfft(fr * np.hanning(n), axis=1)) ** 2).mean(0); f = np.fft.rfftfreq(n, 1 / sr)
    v = np.array([P[(f >= a) & (f < b)].sum() for a, b in BANDS])
    return 10 * np.log10(v / v.sum() + 1e-12)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('score'); ap.add_argument('part'); ap.add_argument('wav')
    ap.add_argument('--channel', type=int); ap.add_argument('--singers', default='2,4,9'); a = ap.parse_args()
    sc = score.load(a.score)
    w = wave.open(a.wav); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()) / 32768
    target = ltas(x.mean(1) if a.channel is None else x[:, a.channel], sr)
    beats, secs = R.clock_for(sc)
    clock = (beats, secs, float(np.interp(sc.beats, beats, secs)) + 4)
    notes = [n for n in R.engine_notes(sc, a.part) if n[0] < 130]            # the first third is enough
    who = [int(i) for i in a.singers.split(',')]

    def mine():
        return ltas(sum(voice.render_singer((a.part, i, notes, clock))[4].astype(float) for i in who), voice.SR)

    w8 = np.array([1, 1, 1, 1, 1, 1, .5, .3])
    err = lambda l: float(np.sqrt(((l - target) ** 2 * w8).sum() / w8.sum()))
    # Only settings that leave the vowel resonances sharp; the rest of the difference becomes an EQ curve.
    grid = dict(oq=[.9, 1, 1.1, 1.2, 1.3, 1.4], ring=[.7, 1, 1.4, 2, 2.6], f4=[2800, 3000, 3200, 3400], f5=[3500, 3700, 3900])
    best = err(mine())
    print('bands           ' + ' '.join(f'{lo}-{hi}'.rjust(10) for lo, hi in BANDS))
    print('real singer     ' + ' '.join(f'{v:10.1f}' for v in target))
    print('model, before   ' + ' '.join(f'{v:10.1f}' for v in mine()) + f'   rms error {best:.2f} dB')
    for sweep in range(2):
        for k, vals in grid.items():
            keep = voice.FIT[k]
            for v in vals:
                voice.FIT[k] = v
                e = err(mine())
                if e < best - .02:
                    best, keep = e, v
            voice.FIT[k] = keep
        print(f'after sweep {sweep + 1}: rms error {best:.2f} dB  ' + ', '.join(f'{k}={voice.FIT[k]:g}' for k in grid))
    print('model, after    ' + ' '.join(f'{v:10.1f}' for v in mine()))
    centres = [float(np.sqrt(lo * hi)) for lo, hi in BANDS]
    eq = np.zeros(len(BANDS))
    for _ in range(4):
        voice.FIT['eq'] = tuple(zip(centres, eq))
        d = target - mine()
        eq = np.clip(eq + .8 * (d - (d * w8).sum() / w8.sum()), -10, 10)
    voice.FIT['eq'] = tuple((round(c), round(float(g), 1)) for c, g in zip(centres, eq))
    l = mine()
    print('model, with EQ  ' + ' '.join(f'{v:10.1f}' for v in l) + f'   rms error {err(l):.2f} dB')
    print('FIT =', {k: v for k, v in voice.FIT.items()})


if __name__ == '__main__':
    main()
