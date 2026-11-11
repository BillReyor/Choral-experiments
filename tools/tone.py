"""Tone, harmonic by harmonic: compare held vowels in a real solo recording with the model.

    python tools/tone.py SCORE PART SOLO.wav --offset 1.07 --bpm 100 [--channel 1]

For every note held long enough, the strength of each harmonic is measured in the middle of the
note, in the recording and in a neutral simulated singer on the same note.  Only the harmonic
peaks are compared, so room reverb and noise between the harmonics do not count - this is the
voice's own colour.  The report shows where the model is too strong or too weak across the
spectrum, and for which vowels.
"""
import argparse, os, sys, wave
import numpy as np
from scipy.signal import resample_poly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from choral import score, voice, render as R

SR, N, HOP = 22050, 2048, 256
FMAX = 5000.


def harmonics(x, t0, t1, f0):
    """Median dB level of each harmonic of f0 over the frames between t0 and t1 (None if too short)."""
    seg = x[int(t0 * SR):int(t1 * SR) + N]
    if len(seg) < N + 2 * HOP:
        return None
    fr = np.lib.stride_tricks.sliding_window_view(seg, N)[::HOP] * np.hanning(N)
    S = np.abs(np.fft.rfft(fr, axis=1))
    # refine f0 from the strongest low harmonics
    best, bf = -1, f0
    for c in f0 * 2 ** (np.arange(-60, 61, 6) / 1200):
        e = sum(S[:, int(round(k * c * N / SR))].mean() for k in range(1, 7))
        if e > best:
            best, bf = e, c
    K = int(FMAX / bf)
    A = np.empty(K)
    for k in range(1, K + 1):
        c = k * bf * N / SR; w = max(2, int(.03 * c) + 1)
        A[k - 1] = np.median(S[:, int(c) - w:int(c) + w + 2].max(1))
    return bf, 20 * np.log10(A + 1e-9)


def held_notes(sc, part, min_sec, spb):
    DI = voice.DIPH
    out = []
    for n in sc.parts[part]:
        toks = n.get('phon', '').split()
        v = next((t for t in toks if t.isupper()), None)
        if v and n['dur'] * spb >= min_sec:
            mi = n['midi'][0] if isinstance(n['midi'], tuple) else n['midi']
            out.append((n, v, 440 * 2 ** ((mi - 69) / 12)))
    return out


def envelopes(x, sc, part, offset, spb, m0=None, m1=None, min_sec=.42):
    rows = []
    for n, v, f0 in held_notes(sc, part, min_sec, spb):
        if (m0 and n['m'] < m0) or (m1 and n['m'] > m1):
            continue
        a, z = offset + n['beat'] * spb, offset + (n['beat'] + n['dur']) * spb
        h = harmonics(x, a + .3 * (z - a), a + .62 * (z - a) - N / SR, f0)
        rows.append((n, v, h))
    return rows


def compare(real, mine):
    """Per-note harmonic differences (model minus real), level-matched.  Returns list of (vowel, freqs, diff, weight)."""
    out = []
    for (n, v, hr), (_, _, hm) in zip(real, mine):
        if hr is None or hm is None:
            continue
        k = min(len(hr[1]), len(hm[1]))
        r, m = hr[1][:k], hm[1][:k]
        w = np.clip((r - r.max() + 45) / 20, 0, 1)            # harmonics far below the strongest barely matter
        if w.sum() < 3:
            continue
        d = (m - r); d = d - (d * w).sum() / w.sum()
        out.append((v, hr[0] * np.arange(1, k + 1), d, w))
    return out


def error(cmp):
    num = sum((d * d * w).sum() for _, _, d, w in cmp); den = sum(w.sum() for _, _, d, w in cmp)
    return float(np.sqrt(num / den))


def load(path, channel):
    w = wave.open(path); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()) / 32768
    x = x.mean(1) if channel is None else x[:, channel]
    return resample_poly(x, SR, sr) if sr != SR else x


def synth(sc, part, offset, spb, m0=None, m1=None):
    voice.set_clock([0, sc.beats + 16], [offset, offset + (sc.beats + 16) * spb], offset + sc.beats * spb + 5)
    notes = [n for n in R.engine_notes(sc, part)]
    if m0:
        b0 = sc.measures[m0][0]; b1 = sc.measures[m1][0] + sc.measures[m1][1]
        notes = [n for n in notes if b0 - 2 <= n[0] < b1 + 2]
    S, rng = voice.make_singer(part, 4, neutral=True)
    out = np.zeros(voice.CLOCK['n'], np.float32); prev = None
    for ph in voice.split_phrases(notes):
        voice.render_phrase(ph, S, rng, out, gap=9. if prev is None else voice.T(ph[0][0]) - voice.T(prev))
        prev = ph[-1][0] + ph[-1][1]
    return resample_poly(out.astype(float), SR, voice.SR)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score'); ap.add_argument('part'); ap.add_argument('wav')
    ap.add_argument('--offset', type=float, default=0.); ap.add_argument('--bpm', type=float); ap.add_argument('--channel', type=int)
    a = ap.parse_args()
    sc = score.load(a.score)
    spb = 60 / (a.bpm or sc.tempo[0][1])
    real = envelopes(load(a.wav, a.channel), sc, a.part, a.offset, spb)
    mine = envelopes(synth(sc, a.part, a.offset, spb), sc, a.part, a.offset, spb)
    cmp = compare(real, mine)
    print(f'{len(cmp)} held notes compared; tone error {error(cmp):.2f} dB (model vs real, harmonic by harmonic)')
    edges = [80, 250, 400, 550, 700, 900, 1150, 1450, 1800, 2200, 2700, 3200, 3800, 4400, 5000]
    print('model minus real by frequency (dB; + = model too strong):')
    allf = np.concatenate([f for _, f, d, w in cmp]); alld = np.concatenate([d for _, f, d, w in cmp]); allw = np.concatenate([w for _, f, d, w in cmp])
    for lo, hi in zip(edges[:-1], edges[1:]):
        s = (allf >= lo) & (allf < hi) & (allw > .2)
        if s.sum() > 5:
            print(f'  {lo:5d}-{hi:<5d} {np.average(alld[s], weights=allw[s]):+6.1f}   spread {np.sqrt(np.average((alld[s] - np.average(alld[s], weights=allw[s])) ** 2, weights=allw[s])):4.1f}')
    by = {}
    for v, f, d, w in cmp:
        by.setdefault(v, []).append((d * d * w).sum() / w.sum())
    print('by vowel (error dB, notes):', ', '.join(f'{v} {np.sqrt(np.mean(e)):.1f} ({len(e)})' for v, e in sorted(by.items(), key=lambda kv: -len(kv[1]))))


if __name__ == '__main__':
    main()
