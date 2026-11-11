"""Where does every beat of the score fall in a recording?

A recording of one part alone (or the accompaniment alone) is enough to recover the tempo, the
moment of the first beat, and any place the tempo bends - a ritardando, a held last chord.

    python -m choral.timing SCORE PART SOLO.wav OUT.json [--channel 1] [--accompaniment ACC.wav]
"""
import argparse, json, wave
import numpy as np
from .pitch import yin


def read_wav(path, channel=None):
    w = wave.open(path); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()) / 32768
    return (x.mean(1) if channel is None else x[:, channel]), sr


def part_notes(sc, part):
    return [(n['beat'], n['dur'], n['midi'][0] if isinstance(n['midi'], tuple) else n['midi']) for n in sc.parts[part]]


def _near(m, pitch):
    return np.abs((m - pitch + 6) % 12 - 6) < .7


def steady_fit(notes, t, m, bpm0, res=16):
    """One tempo and one start time that put the most of the sung sound on the pitch the score
    expects at that moment.  Returns (share of notes on pitch, start, bpm)."""
    S = int(max(b + d for b, d, mi in notes) * res) + 1
    want = np.full(S + 1, np.nan)
    for b, d, mi in notes:
        want[int(round(b * res)):int(round((b + d) * res))] = mi
    v = ~np.isnan(m); tv, mv = t[v], m[v]

    def frames(t0, bpm):                                     # share of voiced frames that are on the expected pitch
        i = np.floor((tv - t0) * bpm / 60 * res).astype(int)
        ok = (i >= 0) & (i < S)
        return float(_near(mv[ok], want[i[ok]]).sum()) / max(len(tv), 1)
    _, a0, b0 = max((frames(a, b), a, b) for b in np.arange(bpm0 * .92, bpm0 * 1.08, bpm0 * .004) for a in np.arange(-2, 25, .1))
    _, t0, bpm = max((frames(a, b), a, b) for b in np.arange(b0 * .994, b0 * 1.006, b0 * .0002) for a in np.arange(a0 - .15, a0 + .15, .005))
    spb = 60 / bpm; ok = tot = 0
    for b, d, mi in notes:
        x = m[(t >= t0 + (b + .25 * d) * spb) & (t <= t0 + (b + .85 * d) * spb)]; x = x[~np.isnan(x)]
        if len(x):
            tot += 1; ok += abs((np.median(x) - mi + 6) % 12 - 6) < .7
    return ok / max(tot, 1), float(t0), float(bpm)


def attack_grid(x, sr, t0, bpm, beats):
    """Sharpen a rough (start, tempo) on an accompaniment: its note attacks mark the beat far more
    exactly than a singer does.  Looks within a tenth of a second and 0.4% of the rough answer."""
    tt, flux = _flux(x[:int((t0 + beats * 60 / bpm + 2) * sr)], sr)
    grid = np.arange(0, beats, .5)
    s, a, b = max((np.interp(a + grid * 60 / b, tt, flux).mean(), a, b)
                  for b in np.arange(bpm * .996, bpm * 1.004, bpm * .0001) for a in np.arange(t0 - .1, t0 + .1, .005))
    return float(a), float(b)


def follow(notes, total_beats, t, m, t0, bpm, res=8):
    """Tempo map as (beats, seconds).  The recording is matched to the score slot by slot; then only
    the moments that really say something about time - a change of pitch, an entry after a rest -
    are kept as anchors, and only a drift that never returns to the steady pulse counts as a change
    of tempo (one singer running late for a bar and catching up does not)."""
    S = int(total_beats * res) + 1
    want = np.full(S, np.nan)
    for b, d, mi in notes:
        want[int(round(b * res)):int(round((b + d) * res))] = mi
    dt = t[1] - t[0]; A = len(t)
    nominal = 60 / bpm / res / dt
    voiced = ~np.isnan(m)
    ks = np.arange(max(1, int(nominal * .4)), int(nominal * 4) + 1)
    pen = .03 * np.abs(np.log2(ks / nominal))
    D = np.full(A, np.inf); back = np.zeros((S, A), np.int16)
    a0 = int(round((t0 - t[0]) / dt)); D[max(0, a0 - 2):a0 + 3] = 0
    idx = np.arange(A)
    for s in range(1, S):
        cost = np.where(voiced, .3, 0.) if np.isnan(want[s]) else np.where(voiced, np.where(_near(m, want[s]), 0., 1.), .6)
        best = np.full(A, np.inf); arg = np.zeros(A, np.int16)
        for k, p in zip(ks, pen):
            cand = np.full(A, np.inf); cand[k:] = D[:-k] + p
            better = cand < best
            best[better] = cand[better]; arg[better] = k
        off = np.abs(idx - (a0 + s * nominal)) * dt
        D = best + cost + .02 * np.minimum(off, 1.)
        D[off > 6.] = np.inf
        back[s] = arg
    a = int(np.argmin(D)); path = [a]
    for s in range(S - 1, 0, -1):
        a -= back[s][a]; path.append(a)
    secs = t[np.array(path[::-1])]
    steady = lambda b: t0 + b * 60 / bpm

    ab, ad = [], []                                           # anchors: (beat, seconds off the steady pulse)
    for i, (b, d, mi) in enumerate(notes):
        prev = notes[i - 1] if i else None
        if prev is None or prev[0] + prev[1] < b - .01 or prev[2] != mi:
            ab.append(b); ad.append(secs[int(round(b * res))] - steady(b))
    ab, ad = np.array(ab), np.array(ad)
    ad = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(ad, 1, mode='edge'), 3), axis=1)
    on_grid = np.where(np.abs(ad) < .07)[0]
    if len(on_grid):
        ad[:on_grid[-1] + 1] = 0.
    pts = dict(zip(ab, ad))
    for i, (b, d, mi) in enumerate(notes):                    # a note before a rest ends in the tempo it began in
        if i + 1 == len(notes) or notes[i + 1][0] > b + d + .4:
            pts[b + d] = float(np.interp(b, ab, ad))
    b, d, mi = notes[-1]                                      # the last note: measure its release directly
    start = steady(b) + float(np.interp(b, ab, ad))
    on = voiced & _near(m, mi) & (t > start)
    w = int(.25 / dt)
    for g in np.where(~on & (t > start + .3))[0]:
        if not on[g:g + w].any():
            if t[g] - steady(b + d) > pts[b + d] + .15:
                pts[b + d] = float(t[g] - steady(b + d))
            break
    kb = np.array(sorted(pts)); kd = np.array([pts[k] for k in kb])
    beats = np.arange(0, total_beats + 1.)
    dev = np.interp(beats, kb, kd)
    dev[np.abs(dev) < .03] = 0.
    return beats, steady(beats) + dev


def _flux(x, sr, hop=220, n=2048):
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    M = np.log1p(50 * np.abs(np.fft.rfft(fr, axis=1)))
    return (np.arange(len(fr) - 1) * hop + hop + n / 2) / sr, np.maximum(np.diff(M, axis=0), 0).sum(1)


def from_accompaniment(sc, x, sr, log=print):
    """Timing from an accompaniment recording alone, for a score whose piano part is written out:
    slide the pattern of written note attacks along the recording at many tempos and keep the best."""
    on = {}
    for n in sc.piano:
        on[n['beat']] = on.get(n['beat'], 0) + 1
    if len(on) < 16:
        raise SystemExit('to line the voices up with an accompaniment track I need either the piano part written in '
                         'the score, or a recording of one voice part (e.g. a "predominant" practice track)')
    ob = np.array(sorted(on)); ow = np.sqrt([on[b] for b in ob])
    keep = ob < np.percentile(ob, 85)                        # endings slow down; fit the body of the piece
    ob, ow = ob[keep], ow[keep]
    tt, fl = _flux(x[:int(sr * min(len(x) / sr, 30 + ob[-1] * 60 / sc.tempo[0][1] * 1.1))], sr)
    dt = tt[1] - tt[0]; fl = fl / fl.max()
    best = (-1, 0, 0)
    bpm0 = sc.tempo[0][1]
    for bpm in np.arange(bpm0 * .9, bpm0 * 1.1, bpm0 * .0005):
        comb = np.zeros(int(ob[-1] * 60 / bpm / dt) + 2)
        np.add.at(comb, np.round(ob * 60 / bpm / dt).astype(int), ow)
        lim = min(len(fl) - len(comb), int(30 / dt))
        if lim <= 0:
            continue
        c = np.correlate(fl[:len(comb) + lim], comb, 'valid')
        k = int(c.argmax())
        if c[k] > best[0]:
            best = (c[k], tt[0] + k * dt, bpm)
    _, t0, bpm = best
    t0, bpm = attack_grid_at(tt, fl, t0, bpm, ob)
    log(f'accompaniment: beat 1 at {t0:.2f}s, {bpm:.2f} bpm')
    return {'offset': round(t0, 3), 'bpm': round(bpm, 3)}


def attack_grid_at(tt, fl, t0, bpm, grid):
    s, a, b = max((np.interp(a + grid * 60 / b, tt, fl).mean(), a, b)
                  for b in np.arange(bpm * .9995, bpm * 1.0005, bpm * .00005) for a in np.arange(t0 - .03, t0 + .03, .003))
    return float(a), float(b)


def measure(sc, part, x, sr, accompaniment=None, log=print):
    """Timing of a piece from a recording of one part (mono array x): {'offset','bpm','beats','secs'}.
    accompaniment=(array, sr) sharpens the beat grid on its note attacks."""
    t, m = yin(x, sr)
    notes = part_notes(sc, part)
    ag, t0, bpm = steady_fit(notes, t, m, sc.tempo[0][1])
    log(f'{part}: {100 * ag:.0f}% of its notes are on pitch with beat 1 at {t0:.2f}s, {bpm:.2f} bpm')
    if ag < .6:
        log('  ! that is too few to trust: is this the right part, and is the transcription right?')
    if accompaniment is not None:
        last = max(b for b, d, mi in notes)
        t0, bpm = attack_grid(accompaniment[0], accompaniment[1], t0, bpm, min(last, sc.beats - 24))
        log(f'accompaniment attacks put beat 1 at {t0:.3f}s, {bpm:.2f} bpm')
    beats, secs = follow(notes, sc.beats, t, m, t0, bpm)
    dev = secs - (t0 + beats * 60 / bpm)
    moved = np.where(np.abs(dev) > .05)[0]
    if len(moved):
        b0 = beats[moved[0]]
        mnum = max(k for k in sc.measures if sc.measures[k][0] <= b0)
        log(f'tempo leaves the steady pulse at measure {mnum}; the last beat falls {dev[-1]:+.2f}s late')
    return {'offset': round(t0, 3), 'bpm': round(bpm, 3), 'agree': round(float(ag), 3),
            'beats': [float(b) for b in beats], 'secs': [round(float(s), 3) for s in secs]}


def main():
    from . import score
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score'); ap.add_argument('part'); ap.add_argument('wav'); ap.add_argument('out')
    ap.add_argument('--channel', type=int); ap.add_argument('--accompaniment')
    a = ap.parse_args()
    x, sr = read_wav(a.wav, a.channel)
    json.dump(measure(score.load(a.score), a.part, x, sr, read_wav(a.accompaniment) if a.accompaniment else None), open(a.out, 'w'))
    print('wrote', a.out)


if __name__ == '__main__':
    main()
