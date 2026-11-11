"""Check every written vocal note against a recording of all the voices together.

    python tools/check_mix.py SCORE VOICES.wav --offset 1.07 --bpm 100

For each note it asks: is there more energy at the written pitch than at the pitches a step or
two away (ignoring pitches that another voice is singing at that moment)?  Notes that fail are
the places to re-read in the sheet music.
"""
import argparse, sys, wave, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from choral import score

NAMES = 'C C# D Eb E F F# G Ab A Bb B'.split()
nm = lambda x: NAMES[int(round(x)) % 12] + str(int(round(x)) // 12 - 1)


def salience(seg, sr, midi):
    n = 1 << int(np.ceil(np.log2(len(seg) * 4)))
    S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n))
    f0 = 440 * 2 ** ((midi - 69) / 12)
    tot = 0.
    for k, w in ((1, 1.), (2, 1.), (3, .8), (4, .6), (5, .4)):
        c = k * f0 * n / sr
        lo, hi = int(c * 2 ** (-.3 / 12)), int(np.ceil(c * 2 ** (.3 / 12))) + 1
        if hi < len(S):
            tot += w * S[lo:hi].max()
    return tot


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('score'); ap.add_argument('wav')
    ap.add_argument('--offset', type=float, default=0.); ap.add_argument('--bpm', type=float)
    ap.add_argument('--parts', default='T1,T2,BR,BS'); a = ap.parse_args()
    sc = score.load(a.score)
    w = wave.open(a.wav); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()).mean(1) / 32768
    spb = 60 / (a.bpm or sc.tempo[0][1])
    allnotes = [(p, n) for p in sc.parts for n in sc.parts[p]]
    pitches = lambda n: n['midi'] if isinstance(n['midi'], tuple) else (n['midi'],)
    for part in a.parts.split(','):
        bad = 0
        for n in sc.parts[part]:
            b, d = n['beat'], n['dur']
            i0, i1 = int((a.offset + (b + .12 * min(d, 1)) * spb) * sr), int((a.offset + (b + min(d, 2.) * .95) * spb) * sr)
            seg = x[i0:i1]
            if len(seg) < 256:
                continue
            others = {m for p, o in allnotes if o is not n and o['beat'] < b + d - .05 and o['beat'] + o['dur'] > b + .05
                      for m in pitches(o)}
            for mi in pitches(n):
                mine = salience(seg, sr, mi)
                rivals = {c: salience(seg, sr, c) for c in (mi - 4, mi - 3, mi - 2, mi - 1, mi + 1, mi + 2, mi + 3, mi + 4)
                          if not any((c - o) % 12 == 0 or abs(c - o) in (7, 19) for o in others | set(pitches(n)))}
                if rivals:
                    c = max(rivals, key=rivals.get)
                    if rivals[c] > 1.5 * mine:
                        bad += 1
                        print(f"  {part} m{n['m']} beat {b - sc.measures[n['m']][0] + 1:g} ({d:g}): wrote {nm(mi)} "
                              f"'{n['lyric']}', but {nm(c)} is {rivals[c] / max(mine, 1e-9):.1f}x stronger")
        print(f'{part}: {bad} suspicious of {len(sc.parts[part])} notes')


if __name__ == '__main__':
    main()
