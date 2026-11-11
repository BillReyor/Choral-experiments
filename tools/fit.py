"""Fit the voice model (or the piano) to a recording by comparing the sound itself.

    python tools/fit.py voice JOBS.json OUT.json [--sweeps 2]
    python tools/fit.py piano JOBS.json OUT.json

A job names a score, a part, a recording of that part alone, and where beat 1 falls in it.  The
model is rendered on exactly the recording's timing, both are turned into mel spectrograms (what
the ear roughly gets: energy in 48 bands, 86 times a second), and the average difference in dB is
the score to beat.  The fitter then tries nudging one setting at a time - a vowel's resonance, a
consonant's length, the brightness of a hammer strike - and keeps whatever brings the model
closer.  Jobs marked "test": true are never fitted on; they show whether a change generalizes.
"""
import argparse, json, os, sys, time, wave
import numpy as np
from multiprocessing import Pool
from scipy.signal import resample_poly, fftconvolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from choral import score, voice, piano, render as R

SR, NFFT, HOP, NMEL = 22050, 1024, 256, 48


def _fb():
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    edges = 700 * (10 ** (np.linspace(mel(60), mel(10000), NMEL + 2) / 2595) - 1)
    f = np.fft.rfftfreq(NFFT, 1 / SR)
    fb = np.zeros((NMEL, len(f)))
    for i in range(NMEL):
        lo, c, hi = edges[i:i + 3]
        fb[i] = np.clip(np.minimum((f - lo) / (c - lo), (hi - f) / (hi - c)), 0, None)
    return fb


FB = _fb()


def logmel(x):
    fr = np.lib.stride_tricks.sliding_window_view(x, NFFT)[::HOP] * np.hanning(NFFT)
    return 10 * np.log10((np.abs(np.fft.rfft(fr, axis=1)) ** 2) @ FB.T + 1e-10)


def distance(Rm, Sm, floor=55.):
    """Mean dB difference between two mel spectrograms, forgiving 35 ms of timing either way."""
    n = min(len(Rm), len(Sm)); Rm, Sm = Rm[:n], Sm[:n]
    Rm = Rm - np.percentile(Rm.max(1), 97); Sm = Sm - np.percentile(Sm.max(1), 97)
    act = (Rm.max(1) > -floor + 12) | (Sm.max(1) > -floor + 12)
    both = (Rm.max(1) > -floor + 20) & (Sm.max(1) > -floor + 20)
    if both.sum() > 20:                                   # one overall gain, set where both are sounding
        Sm = Sm + np.median(Rm[both].mean(1) - Sm[both].mean(1))
    Rm, Sm = np.maximum(Rm, -floor), np.maximum(Sm, -floor)
    best = np.full(n, np.inf)
    for s in range(-3, 4):
        best = np.minimum(best, np.sqrt(((Rm - np.roll(Sm, s, 0)) ** 2).mean(1)))
    return float(best[act].mean())


def reverb(x, rt, wet):
    n = int(1.6 * SR); t = np.arange(n) / SR
    ir = np.random.default_rng(5).standard_normal(n) * np.exp(-6.91 * t / max(rt, .05)) * np.clip(t / .01, 0, 1)
    return x + wet * fftconvolve(x, ir / np.sqrt((ir ** 2).sum()))[:len(x)]


def load_ref(job):
    w = wave.open(job['wav']); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()) / 32768
    x = x.mean(1) if job.get('channel') is None else x[:, job['channel']]
    return resample_poly(x, SR, sr) if sr != SR else x


def window(job, sc):
    spb = 60 / job['bpm']
    b0 = sc.measures[job['m0']][0]; b1 = sc.measures[job['m1']][0] + sc.measures[job['m1']][1]
    return b0, b1, job['offset'] + b0 * spb - .4, job['offset'] + b1 * spb + .8


# ------------------------------------------------------------------ voice --
def voice_start():
    P = {f'FIT.{k}': voice.FIT[k] for k in ('oq', 'rd', 'ring', 'f4', 'f5', 'breath', 'b1')}
    P.update({f'EQ.{i}': db for i, (hz, db) in enumerate(voice.FIT['eq'])})
    P.update({f'TUNE.{k}': v for k, v in voice.TUNE.items()})
    for v in voice.VOW:
        P.update({f'VOW.{v}.{j}': float(voice.VOW[v][j]) for j in range(3)})
    for d in voice.DIPH:
        P.update({f'DIPH.{d}.{a}.{j}': float(voice.DIPH[d][a][j]) for a in range(2) for j in range(2)})
    for c in ('m', 'n', 'ng', 'l', 'r', 'w', 'y', 'v', 'z', 'dh'):
        P[f'CONS.{c}.av'] = voice.CONS[c]['av']
    for c in ('m', 'n', 'l', 'r', 'w', 's', 'z'):
        P[f'CONS.{c}.d'] = voice.CONS[c]['d']
    for c in ('s', 'sh', 'f', 'th', 'z'):
        P[f'CONS.{c}.na'] = voice.CONS[c]['na']
    for c in ('m', 'n', 'ng'):
        P[f'CONS.{c}.lp'] = voice.CONS[c]['lp']
    P.update({'CDUR': voice.CDUR, 'REV.rt': .6, 'REV.wet': .25})
    return P


def voice_apply(P):
    voice.apply_fit(P)


def voice_audio(job, P):
    voice_apply(P)
    sc = score.parse(open(job['score']).read(), warn=lambda *a: None)
    spb = 60 / job['bpm']
    b0, b1, t0, t1 = window(job, sc)
    voice.set_clock([0, sc.beats + 16], [job['offset'], job['offset'] + (sc.beats + 16) * spb], t1 + 3)
    notes = [n for n in R.engine_notes(sc, job['part']) if b0 <= n[0] < b1]
    S, rng = voice.make_singer(job['part'], 4, neutral=True)
    out = np.zeros(voice.CLOCK['n'], np.float32); prev = None
    for ph in voice.split_phrases(notes):
        voice.render_phrase(ph, S, rng, out, gap=9. if prev is None else voice.T(ph[0][0]) - voice.T(prev))
        prev = ph[-1][0] + ph[-1][1]
    y = resample_poly(out.astype(float), SR, voice.SR)
    return reverb(y, P.get('REV.rt', .6), P.get('REV.wet', .25))[int(t0 * SR):int(t1 * SR)]


# ------------------------------------------------------------------- tone --
def tone_start():
    """Only the settings that colour a held vowel: resonances, their widths, the voice source, the EQ."""
    P = voice_start()
    keep = lambda k: (k.startswith(('VOW.', 'EQ.')) or (k.startswith('DIPH.') and k.split('.')[2] == '0')
                      or k in ('FIT.oq', 'FIT.rd', 'FIT.ring', 'FIT.f4', 'FIT.f5', 'FIT.b1', 'TUNE.b2', 'TUNE.b3', 'TUNE.rd_effort'))
    return {k: v for k, v in P.items() if keep(k)}


_TONE = {}


def tone_error(job, P):
    import tone
    voice.apply_fit(P)
    sc = score.parse(open(job['score']).read(), warn=lambda *a: None)
    spb = 60 / job['bpm']
    key = (job['wav'], job['m0'], job['m1'])
    if key not in _TONE:
        _TONE[key] = tone.envelopes(tone.load(job['wav'], job.get('channel')), sc, job['part'], job['offset'], spb, job['m0'], job['m1'])
    mine = tone.envelopes(tone.synth(sc, job['part'], job['offset'], spb, job['m0'], job['m1']), sc, job['part'], job['offset'], spb, job['m0'], job['m1'])
    return tone.error(tone.compare(_TONE[key], mine))


# ------------------------------------------------------------------ piano --
def piano_start():
    P = {f'P.{k}': v for k, v in piano.FIT.items() if not isinstance(v, tuple)}
    P.update({f'PEQ.{i}': db for i, (hz, db) in enumerate(piano.FIT['eq'])})
    P.update({'REV.rt': .8, 'REV.wet': .2})
    return P


def piano_apply(P):
    piano.apply_fit(P)


def piano_audio(job, P):
    piano_apply(P)
    sc = score.parse(open(job['score']).read(), warn=lambda *a: None)
    spb = 60 / job['bpm']
    b0, b1, t0, t1 = window(job, sc)
    T = lambda b: job['offset'] + b * spb
    notes = [n for n in sc.piano if b0 - 4 <= n['beat'] < b1]
    y = piano.render(notes, int((t1 + 3) * piano.SR), T, lambda b: sc.dyn('piano', b)).mean(1)
    y = resample_poly(y, SR, piano.SR)
    return reverb(y, P.get('REV.rt', .8), P.get('REV.wet', .2))[int(t0 * SR):int(t1 * SR)]


# ------------------------------------------------------------------- fit --
_REF = {}


def evaluate(args):
    mode, jobs, P = args
    tot = []
    if mode == 'tone':
        return float(np.mean([tone_error(job, P) for job in jobs]))
    for job in jobs:
        key = (job['wav'], job['m0'], job['m1'])
        if key not in _REF:
            sc = score.parse(open(job['score']).read(), warn=lambda *a: None)
            b0, b1, t0, t1 = window(job, sc)
            _REF[key] = logmel(load_ref(job)[int(t0 * SR):int(t1 * SR)])
        y = (voice_audio if mode == 'voice' else piano_audio)(job, P)
        tot.append(distance(_REF[key], logmel(y)))
    return float(np.mean(tot))


def candidates(k, v):
    if k.startswith(('EQ.', 'PEQ.')):
        return [float(np.clip(v + d, -14, 14)) for d in (-3, -1.2, 1.2, 3)]
    if k in ('FIT.rd',):
        return [v - .2, v - .08, v + .08, v + .2]
    lo, hi = .5 * abs(v) if v else -1, 2 * abs(v) if v else 1
    if k.startswith(('VOW.', 'DIPH.')):
        return [v * m for m in (.9, .96, 1.04, 1.1)]
    return [float(np.clip(v * m, lo, hi)) for m in (.75, .9, 1.11, 1.33)] if v else [.1, .25, .5, 1.]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['voice', 'tone', 'piano']); ap.add_argument('jobs'); ap.add_argument('out')
    ap.add_argument('--sweeps', type=int, default=2); ap.add_argument('--start')
    a = ap.parse_args()
    jobs = json.load(open(a.jobs))
    train = [j for j in jobs if not j.get('test')]; test = [j for j in jobs if j.get('test')]
    P = {'voice': voice_start, 'tone': tone_start, 'piano': piano_start}[a.mode]()
    start = dict(P)
    if a.start:
        P.update(json.load(open(a.start)))
    t0 = time.time()
    with Pool(8) as pool:
        base, base_t = pool.map(evaluate, [(a.mode, train, P), (a.mode, test or train, P)])
        best = base
        print(f'start: fitted passages {base:.2f} dB, held-out passages {base_t:.2f} dB', flush=True)
        for sweep in range(a.sweeps):
            for k in list(P):
                cands = candidates(k, P[k])
                res = pool.map(evaluate, [(a.mode, train, dict(P, **{k: c})) for c in cands])
                i = int(np.argmin(res))
                if res[i] < best - .003:
                    print(f'  {k:16s} {P[k]:9.3f} -> {cands[i]:9.3f}   {best:.3f} -> {res[i]:.3f}', flush=True)
                    P[k], best = cands[i], res[i]
            json.dump({k: v for k, v in P.items() if v != start[k]}, open(a.out, 'w'), indent=1)
            held = pool.map(evaluate, [(a.mode, test or train, P)])[0]
            print(f'after sweep {sweep + 1}: fitted {best:.2f} dB (was {base:.2f}), held-out {held:.2f} dB (was {base_t:.2f})'
                  f'   [{time.time() - t0:.0f}s]', flush=True)


if __name__ == '__main__':
    main()
