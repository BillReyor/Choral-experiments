"""Realism scorecard: how does one synthesized voice differ from a real singer on the same notes?

    python tools/realism.py SCORE PART REAL_SOLO.wav --offset 1.07 --bpm 100 [--channel 1] [--timing MAP.json]

Renders the same part with one simulated singer and measures both recordings the same way:
how pitch moves between notes, how it starts, how steady it is, how each note is shaped in
loudness, how the tone is built (harmonics vs breath), how much the tone moves while a note is
held, and how strong the consonants are.  Numbers that differ are the places the model is fake.
"""
import argparse, os, sys, wave
import numpy as np
from scipy.signal import resample_poly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from choral import score, voice, render as R
from pitchtrack import yin

SR = 22050
HOP = 256


def measure(x, notes, t0, spb, clock=None):
    """notes: dicts with beat, dur, midi, phon.  Returns {metric: value}."""
    t, m = yin(x, SR)
    env_n = 256
    fr = np.lib.stride_tricks.sliding_window_view(x, env_n)[::64]
    et = (np.arange(len(fr)) * 64 + env_n / 2) / SR
    edb = 10 * np.log10((fr ** 2).mean(1) + 1e-10)
    n = 2048
    F = np.lib.stride_tricks.sliding_window_view(x, n)[::HOP]
    ft = (np.arange(len(F)) * HOP + n / 2) / SR
    freqs = np.fft.rfftfreq(n, 1 / SR)
    spec = lambda i: np.abs(np.fft.rfft(F[i] * np.hanning(n)))
    hf = np.lib.stride_tricks.sliding_window_view(
        __import__('scipy.signal', fromlist=['sosfilt']).sosfilt(
            __import__('scipy.signal', fromlist=['butter']).butter(4, 4000, 'high', fs=SR, output='sos'), x), env_n)[::64]
    hfdb = 10 * np.log10((hf ** 2).mean(1) + 1e-10)

    T = (lambda b: float(np.interp(b, clock[0], clock[1]))) if clock else (lambda b: t0 + b * spb)
    M = lambda nt: nt['midi'][0] if isinstance(nt['midi'], tuple) else nt['midi']
    out = {}
    trans, over, lateness, scoop, scoop_t, wob, wob_fast, tune = [], [], [], [], [], [], [], []
    att, slope, lvl, pit, flutter, fill = [], [], [], [], [], []
    h1h2, hnr_lo, hnr_hi, live = [], [], [], []
    sib, sib_d, stop = [], [], []
    for i, nt in enumerate(notes):
        a, z, mi = T(nt['beat']), T(nt['beat'] + nt['dur']), M(nt)
        sel = (t >= a + .3 * min(z - a, .6)) & (t <= z - .1 * (z - a)); v = m[sel]; v = v[~np.isnan(v)]
        if len(v) < 4:
            continue
        med = np.median(v); tune.append(100 * (med - mi))
        es = edb[(et >= a + .25 * (z - a)) & (et <= z - .15 * (z - a))]
        if len(es):
            lvl.append(np.median(es)); pit.append(mi)
        prev = notes[i - 1] if i else None
        legato = prev is not None and abs(prev['beat'] + prev['dur'] - nt['beat']) < 1e-6
        # --- moving between notes
        if legato and abs(mi - M(prev)) >= 2 and prev['dur'] >= .5 and nt['dur'] >= .5:
            pm = M(prev)
            w = (t >= a - .2) & (t <= a + .3); tt, vv = t[w], m[w]
            ok = ~np.isnan(vv)
            if ok.sum() > 12:
                u = (vv[ok] - pm) / (mi - pm); tu = tt[ok]
                lo = np.where(u > .2)[0]; hi = np.where(u > .8)[0]
                if len(lo) and len(hi) and hi[0] >= lo[0]:
                    trans.append(1000 * (tu[hi[0]] - tu[lo[0]]))
                    lateness.append(1000 * (.5 * (tu[hi[0]] + tu[lo[0]]) - a))
                    after = u[hi[0]:hi[0] + 14]
                    over.append(100 * max(0., after.max() - 1) * abs(mi - pm))       # cents past the target
        # --- starting from silence
        if (not legato) and nt['dur'] >= .5:
            w = (t >= a - .08) & (t <= a + .35); tt, vv = t[w], m[w]; ok = ~np.isnan(vv)
            if ok.sum() > 8:
                c = 100 * (vv[ok] - med); tu = tt[ok]
                scoop.append(c[:2].mean())
                inside = np.where(np.abs(c) < 20)[0]
                if len(inside):
                    scoop_t.append(1000 * (tu[inside[0]] - tu[0]))
        e_all = edb[(et >= a) & (et <= z)]
        if z - a >= .28 and len(e_all) > 8:
            fill.append(100 * (e_all > np.percentile(e_all, 80) - 6).mean())
        # --- holding a note
        if z - a >= .55:
            w = (t >= a + .2) & (t <= z - .08); vv = m[w]; vv = vv[~np.isnan(vv)]
            if len(vv) > 20:
                c = 100 * (vv - np.polyval(np.polyfit(np.arange(len(vv)), vv, 1), np.arange(len(vv))))
                sm = np.convolve(c, np.ones(9) / 9, 'same')
                wob.append(c.std()); wob_fast.append((c - sm)[5:-5].std())
            e = edb[(et >= a + .2) & (et <= z - .1)]
            if len(e) > 20:
                k = np.arange(len(e)) * 64 / SR
                p = np.polyfit(k, e, 1); slope.append(p[0]); flutter.append((e - np.polyval(p, k)).std())
            e = edb[(et >= a - .05) & (et <= a + .3)]; k = et[(et >= a - .05) & (et <= a + .3)]
            if len(e) > 10 and not legato:
                top = np.median(edb[(et >= a + .15) & (et <= a + .4)])
                r10 = np.where(e > top - 20)[0]; r90 = np.where(e > top - 2)[0]
                if len(r10) and len(r90) and r90[0] > r10[0]:
                    att.append(1000 * (k[r90[0]] - k[r10[0]]))
            # tone: fundamental vs 2nd harmonic, harmonics vs noise, and how much the tone moves
            idx = np.where((ft >= a + .45 * (z - a)) & (ft <= z - .12 * (z - a)))[0]
            f0 = 440 * 2 ** ((med - 69) / 12)
            if len(idx) >= 3 and f0 > 90:
                bands = []
                for j in idx:
                    S_ = spec(j)
                    pk = lambda f: S_[max(0, int((f - .08 * f0) * n / SR)):int((f + .08 * f0) * n / SR) + 1].max()
                    h1h2.append(20 * np.log10(pk(f0) / (pk(2 * f0) + 1e-9) + 1e-9))
                    for lo_, hi_, store in ((300, 2000, hnr_lo), (2000, 5000, hnr_hi)):
                        ks = np.arange(int(np.ceil(lo_ / f0)), int(hi_ / f0) + 1)
                        if len(ks) < 2:
                            continue
                        har = sum((S_[int((k_ * f0 - .12 * f0) * n / SR):int((k_ * f0 + .12 * f0) * n / SR) + 1] ** 2).sum() for k_ in ks)
                        noi = sum((S_[int((k_ * f0 + .3 * f0) * n / SR):int((k_ * f0 + .7 * f0) * n / SR) + 1] ** 2).sum() for k_ in ks)
                        store.append(10 * np.log10(har / (noi * .24 / .4 + 1e-12) + 1e-12))
                    P_ = S_ ** 2
                    bands.append([10 * np.log10(P_[(freqs >= lo_) & (freqs < hi_)].sum() + 1e-12)
                                  for lo_, hi_ in ((80, 400), (400, 900), (900, 1800), (1800, 3000), (3000, 5000))])
                if len(bands) >= 4:
                    B = np.array(bands); B = B - B.mean(1, keepdims=True)
                    live.append(B.std(0).mean())
        # --- consonants: hiss and click strength against the vowel
        ph = nt.get('phon', '')
        on = ph.split()[:1]
        if on and on[0] in ('s', 'sh') and len(es):
            w = (et >= a - .22) & (et <= a + .03)
            if w.sum() > 5:
                seg = hfdb[w]; sib.append(seg.max() - np.median(es)); sib_d.append(1000 * 64 / SR * (seg > seg.max() - 6).sum())
        if on and on[0] in ('t', 'k', 'p') and len(es):
            w = (et >= a - .12) & (et <= a + .04)
            if w.sum() > 5:
                stop.append(hfdb[w].max() - np.median(es))
    md = lambda v: float(np.median(v)) if len(v) else float('nan')
    out['glide between notes (ms)'] = md(trans)
    out['glide lands late by (ms)'] = md(lateness)
    out['overshoot past the note (cents)'] = md(over)
    out['starts off pitch by (cents)'] = md(scoop)
    out['settles on pitch after (ms)'] = md(scoop_t)
    out['pitch wobble on held notes (cents)'] = md(wob)
    out['  of which fast flutter (cents)'] = md(wob_fast)
    out['tuning spread across notes (cents)'] = float(1.48 * np.median(np.abs(np.array(tune) - np.median(tune))))
    out['attack time from silence (ms)'] = md(att)
    out['loudness drift in a held note (dB/s)'] = md(slope)
    out['loudness flutter in a held note (dB)'] = md(flutter)
    out['share of each note at full voice (%)'] = md(fill)
    out['loudness spread across notes (dB)'] = float(np.std(lvl))
    out['louder when higher (dB/semitone)'] = float(np.polyfit(pit, lvl, 1)[0])
    out['fundamental over 2nd harmonic (dB)'] = md(h1h2)
    out['harmonics over noise 0.3-2 kHz (dB)'] = md(hnr_lo)
    out['harmonics over noise 2-5 kHz (dB)'] = md(hnr_hi)
    out['tone movement in a held note (dB)'] = md(live)
    out['"s" hiss vs vowel (dB)'] = md(sib)
    out['"s" length (ms)'] = md(sib_d)
    out['p/t/k click vs vowel (dB)'] = md(stop)
    return out


def load(path, channel):
    w = wave.open(path); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()) / 32768
    x = x.mean(1) if channel is None else x[:, channel]
    return resample_poly(x, SR, sr) if sr != SR else x


def synth(sc, part, singer):
    beats, secs = R.clock_for(sc)
    clock = (beats, secs, float(np.interp(sc.beats, beats, secs)) + 4)
    y = voice.render_singer((part, singer, R.engine_notes(sc, part), clock))[4].astype(float)
    return resample_poly(y, SR, voice.SR)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score'); ap.add_argument('part'); ap.add_argument('wav')
    ap.add_argument('--offset', type=float, default=0.); ap.add_argument('--bpm', type=float)
    ap.add_argument('--channel', type=int); ap.add_argument('--singers', default='4,2,9')
    ap.add_argument('--timing', help='a tempo map (JSON with beats and secs, from choral.timing) for a recording that does not keep one tempo')
    a = ap.parse_args()
    sc = score.load(a.score)
    notes = sc.parts[a.part]
    clock = None
    if a.timing:
        import json
        tm = json.load(open(a.timing)); clock = (tm['beats'], tm['secs'])
    real = measure(load(a.wav, a.channel), notes, a.offset, 60 / (a.bpm or sc.tempo[0][1]), clock)
    mine = [measure(synth(sc, a.part, int(i)), notes, R.LEAD_IN, 60 / sc.tempo[0][1]) for i in a.singers.split(',')]
    print(f'{"":42s}{"real":>9s}{"model":>9s}   (model = median of singers {a.singers})')
    for k in real:
        mv = float(np.median([m_[k] for m_ in mine]))
        flag = '  <--' if abs(mv - real[k]) > max(.35 * abs(real[k]), 1.0) else ''
        print(f'{k:42s}{real[k]:9.1f}{mv:9.1f}{flag}')


if __name__ == '__main__':
    main()
