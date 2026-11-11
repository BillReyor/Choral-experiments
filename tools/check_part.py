"""Compare one voice part of a score with a recording of that part alone.

    python tools/check_part.py SCORE PART SOLO.wav [--channel 1]

Fits tempo and start offset, then lists notes where the singer's pitch differs from the score.
"""
import argparse, sys, wave, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from choral import score
from pitchtrack import yin

NAMES = 'C C# D Eb E F F# G Ab A Bb B'.split()
nm = lambda x: NAMES[int(round(x)) % 12] + str(int(round(x)) // 12 - 1)


def load(path, channel=None):
    w = wave.open(path); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()) / 32768
    return sr, (x.mean(1) if channel is None else x[:, channel])


def fit(notes, t, m, bpm0):
    def agree(t0, bpm):
        spb = 60 / bpm; ok = tot = 0
        for b, d, mi in notes:
            v = m[(t >= t0 + (b + .25 * d) * spb) & (t <= t0 + (b + .85 * d) * spb)]; v = v[~np.isnan(v)]
            if len(v):
                tot += 1; ok += abs(np.median(v) - mi) < .7
        return ok / max(tot, 1)
    best = max((agree(a, b), a, b) for b in np.arange(bpm0 - 2, bpm0 + 2.01, .25) for a in np.arange(-2, 8, .05))
    return max((agree(a, b), a, b) for b in np.arange(best[2] - .25, best[2] + .2501, .02) for a in np.arange(best[1] - .1, best[1] + .1, .01))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('score'); ap.add_argument('part'); ap.add_argument('wav')
    ap.add_argument('--channel', type=int); a = ap.parse_args()
    sc = score.load(a.score)
    sr, x = load(a.wav, a.channel)
    t, m = yin(x, sr)
    notes = [(n['beat'], n['dur'], n['midi'][0] if isinstance(n['midi'], tuple) else n['midi']) for n in sc.parts[a.part]]
    ag, t0, bpm = fit(notes, t, m, sc.tempo[0][1]); spb = 60 / bpm
    print(f'{a.part}: {100 * ag:.1f}% of notes agree  (recording starts {t0:.2f}s before beat 1, {bpm:.2f} bpm)')
    for n, (b, d, mi) in zip(sc.parts[a.part], notes):
        v = m[(t >= t0 + (b + .25 * d) * spb) & (t <= t0 + (b + .85 * d) * spb)]; v = v[~np.isnan(v)]
        where = f"m{n['m']} beat {b - sc.measures[n['m']][0] + 1:g}"
        if len(v) and abs(np.median(v) - mi) >= .7:
            print(f"  {where}: score {nm(mi)} on '{n['lyric']}', singer {nm(np.median(v))} ({np.median(v) - mi:+.1f})")
        elif not len(v) and d >= .5:
            print(f"  {where}: score {nm(mi)} on '{n['lyric']}', nothing sung")


if __name__ == '__main__':
    main()
