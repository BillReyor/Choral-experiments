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


def nominal(sc):
    """The score's own clock, starting at zero: (beats, seconds) through every tempo mark."""
    pts = sorted(sc.tempo)
    beats, secs, bpm = [0.], [0.], pts[0][1]
    for b, new in pts + [(sc.beats, pts[-1][1])]:
        if b > beats[-1]:
            secs.append(secs[-1] + (b - beats[-1]) * 60 / bpm); beats.append(b)
        bpm = new
    return np.array(beats), np.array(secs)


def _wanted(notes, total_beats, res):
    want = np.full(int(total_beats * res) + 2, np.nan)
    for b, d, mi in notes:
        want[int(round(b * res)):int(round((b + d) * res))] = mi
    return want


def steady_fit(notes, t, m, nom, res=16):
    """Fit the recording to the score's clock: one start time and one stretch for the whole piece,
    then each tempo section's own start and stretch (a marked "120" and "138" are rarely played as
    exactly that ratio).  Returns (share of notes on pitch, beats, seconds) - a piecewise-steady map."""
    nb, ns = nom
    want = _wanted(notes, nb[-1], res)
    v = ~np.isnan(m); tv, mv = t[v], m[v]

    def score(to_nominal, lo=-1e9, hi=1e9):            # share of voiced frames on the expected pitch
        x = to_nominal(tv)                             # nominal seconds each frame falls at
        b = np.interp(x, ns, nb, left=-1, right=-1)
        i = np.clip(np.floor(b * res).astype(int), 0, len(want) - 1)
        ok = (b >= 0) & (x >= lo) & (x < hi)
        return float(_near(mv[ok], want[i[ok]]).sum()) / max(len(tv), 1)
    _, a0, s0 = max((score(lambda x: (x - a) / s), a, s) for s in np.arange(.92, 1.08, .004) for a in np.arange(-2, 25, .1))
    _, a0, s0 = max((score(lambda x: (x - a) / s), a, s) for s in np.arange(s0 - .006, s0 + .006, .0005) for a in np.arange(a0 - .15, a0 + .15, .005))
    beats, secs = [], []
    for k in range(len(nb) - 1):                       # each tempo section: its own start and stretch
        n0, n1 = ns[k], ns[k + 1]
        A, Sx = a0 + s0 * n0, s0
        if len(nb) > 2 and any(nb[k] <= b < nb[k + 1] for b, d, mi in notes):
            _, A, Sx = max((score(lambda x: n0 + (x - A_) / S_, n0, n1), A_, S_)
                           for S_ in np.arange(s0 * .97, s0 * 1.03, s0 * .001) for A_ in np.arange(A - .4, A + .4, .01))
        bb = np.arange(nb[k], nb[k + 1] + (1 if k == len(nb) - 2 else 0))
        beats += list(bb); secs += list(A + Sx * (np.interp(bb, nb, ns) - n0))
    beats, secs = np.array(beats, float), np.maximum.accumulate(np.array(secs))
    ok = tot = 0
    for b, d, mi in notes:
        t0, t1 = np.interp([b + .25 * d, b + .85 * d], beats, secs)
        x = m[(t >= t0) & (t <= t1)]; x = x[~np.isnan(x)]
        if len(x):
            tot += 1; ok += abs((np.median(x) - mi + 6) % 12 - 6) < .7
    return ok / max(tot, 1), beats, secs


def attack_grid(x, sr, beats, secs, sections):
    """Sharpen a steady map on an accompaniment: its note attacks mark the beat far more exactly
    than a singer does.  Each tempo section may move a tenth of a second and stretch by 0.4%."""
    tt, flux = _flux(x, sr)
    secs = secs.copy()
    for b0, b1 in sections:
        sel = (beats >= b0) & ((beats < b1) | (b1 >= beats[-1] - 30))
        if b1 - b0 < 16:
            continue
        g = np.arange(b0, b1, .5)
        base = np.interp(g, beats, secs); t0 = base[0]
        _, da, st = max((np.interp(t0 + da + (base - t0) * st, tt, flux).mean(), da, st)
                        for st in np.arange(.996, 1.004, .0002) for da in np.arange(-.1, .1, .005))
        secs[sel] = t0 + da + (secs[sel] - t0) * st
    return np.maximum.accumulate(secs)


def follow(notes, total_beats, t, m, sbeats, ssecs, res=8):
    """Tempo map as (beats, seconds).  The recording is matched to the score slot by slot; then only
    the moments that really say something about time - a change of pitch, an entry after a rest -
    are kept as anchors, and only a drift that never returns to the steady pulse counts as a change
    of tempo (one singer running late for a bar and catching up does not)."""
    S = int(total_beats * res) + 1
    want = _wanted(notes, total_beats, res)[:S]
    dt = t[1] - t[0]; A = len(t)
    steady = lambda b: np.interp(b, sbeats, ssecs)
    centre = (steady(np.arange(S) / res) - t[0]) / dt       # where the steady map puts each slot, in frames
    step = np.maximum(np.diff(centre, prepend=2 * centre[0] - centre[1]), 1.)
    voiced = ~np.isnan(m)
    ks = np.arange(max(1, int(step.min() * .4)), int(step.max() * 4) + 1)
    D = np.full(A, np.inf); back = np.zeros((S, A), np.int16)
    a0 = int(round(centre[0])); D[max(0, a0 - 2):a0 + 3] = 0
    idx = np.arange(A)
    for s in range(1, S):
        cost = np.where(voiced, .3, 0.) if np.isnan(want[s]) else np.where(voiced, np.where(_near(m, want[s]), 0., 1.), .6)
        pen = .03 * np.abs(np.log2(ks / step[s]))
        best = np.full(A, np.inf); arg = np.zeros(A, np.int16)
        for k, p in zip(ks, pen):
            cand = np.full(A, np.inf); cand[k:] = D[:-k] + p
            better = cand < best
            best[better] = cand[better]; arg[better] = k
        off = np.abs(idx - centre[s]) * dt
        D = best + cost + .02 * np.minimum(off, 1.)
        D[off > 6.] = np.inf
        back[s] = arg
    a = int(np.argmin(D)); path = [a]
    for s in range(S - 1, 0, -1):
        a -= back[s][a]; path.append(a)
    secs = t[np.array(path[::-1])]

    ab, ad = [], []                                           # anchors: (beat, seconds off the steady pulse)
    for i, (b, d, mi) in enumerate(notes):
        prev = notes[i - 1] if i else None
        if prev is None or prev[0] + prev[1] < b - .01 or prev[2] != mi:
            ab.append(b); ad.append(secs[int(round(b * res))] - steady(b))
    ab, ad = np.array(ab), np.array(ad)
    raw = ad.copy()
    ad = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(ad, 1, mode='edge'), 3), axis=1)
    on_grid = np.where(np.abs(ad) < .07)[0]
    if len(on_grid):
        ad[:on_grid[-1] + 1] = 0.
    # Music that breathes (a ritardando and "a tempo" in mid-piece) does return to the pulse: where five
    # anchors in a row agree that the singer is away from it, that is the tempo, not one late entry.
    if len(raw) >= 5:
        med5 = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(raw, 2, mode='edge'), 5), axis=1)
        lo5 = np.min(np.abs(np.lib.stride_tricks.sliding_window_view(np.pad(raw, 2, mode='edge'), 5)), axis=1)
        sway = (lo5 > .12) & (np.abs(med5) > .15)
        ad = np.where(sway & (ad == 0), med5, ad)
    pts = dict(zip(ab, ad))
    for i, (b, d, mi) in enumerate(notes):                    # a note before a rest ends in the tempo it began in
        if i + 1 == len(notes) or notes[i + 1][0] > b + d + .4:
            pts[b + d] = float(np.interp(b, ab, ad))
    b, d, mi = notes[-1]                                      # the last note: measure its release directly
    start = float(steady(b)) + float(np.interp(b, ab, ad))
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


def _piano_attacks(sc):
    """Beats at which the written accompaniment strikes, and how heavily (more notes at once = heavier)."""
    on = {}
    for n in sc.piano:
        on[n['beat']] = on.get(n['beat'], 0) + 1
    ob = np.array(sorted(on))
    return ob, np.sqrt([on[b] for b in ob])


def _fits(sc, x, sr, beats, secs, span, hop, lags):
    """For each stretch of `span` beats: how well the written piano attacks, placed by the map and shifted by each
    lag, land on the recording's own attacks.  -> (stretch centres in beats, fit[stretch, lag], attacks per stretch)"""
    tt, fl = _flux(x, sr)
    fl = fl / np.percentile(fl, 99)
    ob, ow = _piano_attacks(sc)
    starts = np.arange(0, max(sc.beats - span / 2, hop), hop)
    fit = np.zeros((len(starts), len(lags))); count = np.zeros(len(starts), int)
    for i, b0 in enumerate(starts):
        sel = (ob >= b0) & (ob < b0 + span)
        count[i] = sel.sum()
        if count[i] >= 4:
            at = np.interp(ob[sel], beats, secs)
            v = np.array([(np.interp(at + lg, tt, fl, left=0., right=0.) * ow[sel]).sum() for lg in lags]) / ow[sel].sum()   # nothing is heard outside the recording
            fit[i] = np.clip(v / (np.median(v) + 1e-9) - 1, 0, 3) * min(count[i] / 8, 1)
    return starts + span / 2, fit, count


def _singer_fits(sc, part, x, sr, beats, secs, starts, span, lags):
    """For each stretch: the share of this singer's notes that are on their written pitch when the map is shifted
    by each lag (the middle four fifths of every note must be on pitch).  -> (fit[stretch, lag] in 0..1, notes per stretch)"""
    t, m = yin(x, sr)
    dt = t[1] - t[0]
    notes = part_notes(sc, part)
    fit = np.zeros((len(starts), len(lags))); count = np.zeros(len(starts), int)
    if not notes:
        return fit, count
    per = np.zeros((len(notes), len(lags)))
    for i, (b, d, mi) in enumerate(notes):
        a, z = np.interp([b, b + d], beats, secs)
        c = np.cumsum(np.r_[0., (np.abs(m - mi) < .7).astype(float)])      # NaN (no voice) compares false
        i0 = np.clip(((a + .1 * (z - a) + lags - t[0]) / dt).astype(int), 0, len(m))
        i1 = np.clip(((a + .9 * (z - a) + lags - t[0]) / dt).astype(int), 0, len(m))
        per[i] = (c[i1] - c[i0]) / np.maximum(i1 - i0, 1)
    nb = np.array([n[0] for n in notes])
    for w, b0 in enumerate(starts):
        sel = (nb >= b0) & (nb < b0 + span)
        count[w] = sel.sum()
        if count[w] >= 2:
            fit[w] = per[sel].mean(0) * min(count[w] / 4, 1)
    return fit, count


def _path(E, lags, K, jump=4.):
    """The best path through (how far the map is off, how fast that is changing) -> lag per stretch.  Keeping a tempo
    is free, changing it a little costs a little, and one sudden change of place and tempo - a held chord, a new
    section in a tempo the map did not expect - costs a fixed price, so it has to be worth it: several stretches
    of clearly better fit.  (Music repeats; a verse fits the next verse's place nearly as well as its own.)"""
    W, L = E.shape
    ks = np.arange(-K, K + 1); nk = len(ks)
    D = np.repeat(E[0][:, None], nk, 1) - .002 * np.abs(ks)[None, :] - .05 * np.abs(lags)[:, None]
    kind = np.zeros((W, L, nk), np.int8); far = np.zeros((W, 2), int)
    for w in range(1, W):
        jj, kk = np.unravel_index(int(np.argmax(D)), D.shape)
        far[w] = jj, kk
        best = np.full((L, nk), D[jj, kk] - jump); how = np.full((L, nk), 9, np.int8)
        for dk in (-2, -1, 0, 1, 2):                         # tempo as it was, or changed by a step or two
            lo, hi = max(0, -dk), min(nk, nk - dk)
            for i in range(lo, hi):                          # arriving at lag j with slope k means coming from lag j - k
                k = ks[i]
                col = np.full(L, -np.inf)
                if k > 0:
                    col[k:] = D[:L - k, i + dk]
                elif k < 0:
                    col[:k] = D[-k:, i + dk]
                else:
                    col = D[:, i + dk].copy()
                col -= .05 * abs(dk)
                better = col > best[:, i]
                best[better, i] = col[better]; how[better, i] = dk
        D = best + E[w][:, None] - .002 * np.abs(ks)[None, :]
        kind[w] = how
    j, i = np.unravel_index(int(np.argmax(D)), D.shape)
    path, slope = [j], ks[i]
    for w in range(W - 1, 0, -1):
        h = kind[w][j, i]
        if h == 9:
            j, i = far[w]
        else:
            j, i = j - ks[i], i + h
        path.append(j)
    return lags[np.array(path[::-1])], slope * (lags[1] - lags[0])


def track(sc, beats, secs, accompaniment=None, singers=None, log=print, span=8., hop=2.):
    """Bend a tempo map onto the recordings there are.  Two kinds of evidence, stretch by stretch along the piece:
    the written piano attacks landing on the accompaniment track's own attacks (exact to a hundredth of a second,
    but a pattern of even notes fits equally well a beat further on), and each isolated singer's notes being on
    their written pitch (only good to a tenth of a second, but a melody fits in one place only).  The path taken
    is the one that fits best over the whole piece (see _path).  First coarsely and far - the map may be wrong by
    many seconds and by a different tempo - then finely around what that found.
    accompaniment: (mono array, sr); singers: {part: (mono array, sr)}.  -> seconds for each of `beats`."""
    beats = np.asarray(beats, float); ref = np.asarray(secs, float).copy()
    starts = np.arange(0, max(sc.beats - span / 2, hop), hop)
    centres = starts + span / 2
    total = np.zeros(len(starts)); heard = np.zeros(len(starts), bool)
    for lags, K in ((np.arange(-20., 20.001, .02), 40), (np.arange(-1., 1.0001, .01), 8), (np.arange(-.5, .5001, .01), 6)):
        E = np.zeros((len(starts), len(lags))); heard[:] = False
        if accompaniment is not None and len(sc.piano) >= 16:
            _, fp, cp = _fits(sc, accompaniment[0], accompaniment[1], beats, ref, span, hop, lags)
            E += .5 * fp; heard |= cp >= 4
        for part, (x, sr) in (singers or {}).items():
            fs, cs = _singer_fits(sc, part, x, sr, beats, ref, starts, span, lags)
            E += 2. * fs; heard |= cs >= 2
        if heard.sum() < 6:
            return ref
        lag, slope = _path(E, lags, K)
        if len(lag) >= 3:
            lag = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(lag, 1, mode='edge'), 3), axis=1)
        last = int(np.flatnonzero(heard)[-1])                # after the last thing heard, carry on in the tempo found
        # A sudden move needs music on both sides to vouch for it.  One with less than 32 beats after it (or before
        # it) means the recordings do not fit the score as read there - misread notes, a cut - and the map carries on
        # in the tempo it had instead of chasing them.
        big = np.flatnonzero(np.abs(np.diff(lag)) > 1.5) + 1
        late = [w for w in big if len(lag) - w < 32 / hop]
        if late and late[0] > 8:
            w0 = late[0]
            m0 = max(q for q in sc.measures if sc.measures[q][0] <= starts[w0] + span / 2 + 1e-6)
            log(f'  ! from about measure {m0} the recordings do not fit the score as read (misread notes, or a cut): '
                f'the timing carries on from there in the tempo it had')
            last = min(last, w0 - 1)
        early = [w for w in big if w < 32 / hop and w <= last]
        if early:
            w1 = early[-1]
            lag[:w1] = lag[w1] - (lag[min(w1 + 4, last)] - lag[w1]) / 4 * np.arange(w1, 0, -1)
        cb = np.r_[centres[:last + 1], centres[last] + 400.]
        cl = np.r_[lag[:last + 1], lag[last] + (lag[last] - lag[max(last - 4, 0)]) / max(min(last, 4), 1) * 400. / hop]
        moved = np.interp(beats, cb, cl)
        new = ref + moved
        step = np.diff(new)                                  # time only runs forwards: a beat lasts at least a third of its neighbours
        floor = np.median(step) / 3 * np.diff(beats)
        new = np.r_[new[0], new[0] + np.cumsum(np.maximum(step, floor))]
        total += lag
        if np.abs(new - ref).max() < .02:
            ref = new
            break
        ref = new
    log(f'followed through the recordings ({heard.sum()} of {len(starts)} stretches say something): the map moved by '
        f'{1000 * np.median(np.abs(total[heard])):.0f} ms on average, {np.abs(total[heard]).max():.1f} s at most')
    return ref


def on_pitch(sc, part, x, sr, beats, secs):
    """Share of a singer's notes that are on their written pitch where the map says they are."""
    fit, count = _singer_fits(sc, part, x, sr, beats, secs, np.array([0.]), sc.beats + 1., np.array([0.]))
    return float(fit[0, 0]) if count[0] >= 4 else float('nan')


def against_accompaniment(sc, timing, x, sr, span=8., hop=4.):
    """Are the voices in time with the accompaniment track?  -> [(measure, seconds the map is off, clear?)] per stretch:
    where the written piano attacks, placed by the tempo map, best fit the recording's own attacks."""
    from . import render as R
    beats, secs = R.clock_for(sc, timing, absolute=True)
    lags = np.arange(-.4, .4001, .01)
    centres, fit, count = _fits(sc, x, sr, beats, secs, span, hop, lags)
    out = []
    near = np.abs(lags) <= .03
    for c, f, k in zip(centres, fit, count):
        if k >= 4:
            m = max(q for q in sc.measures if sc.measures[q][0] <= c - span / 2 + 1e-6)
            here = f[near].max() >= .7 * f.max()             # an even pattern fits a beat away just as well: that is not "off"
            out.append((m, 0. if here else float(lags[int(np.argmax(f))]), bool(f.max() > .6)))
    return out


def sync_report(rows):
    """One line on what against_accompaniment() found."""
    clear = [r for r in rows if r[2]]
    if not clear:
        return 'voices against the accompaniment: nothing clear enough to say'
    off = [r for r in clear if abs(r[1]) > .06]
    line = f'voices against the accompaniment: within 60 ms in {len(clear) - len(off)} of {len(clear)} stretches'
    if off:
        line += '; off at measures ' + ', '.join(f'{m} ({1000 * d:+.0f} ms)' for m, d, _ in off[:12]) + (' ...' if len(off) > 12 else '')
    return line


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
    nb, ns = nominal(sc)
    ag, sb, ss = steady_fit(notes, t, m, (nb, ns))
    tempos = lambda: ', then '.join('%.2f bpm' % (60 * 4 / float(np.interp(b + 6, sb, ss) - np.interp(b + 2, sb, ss))) for b in nb[:-1])
    log(f'{part}: {100 * ag:.0f}% of its notes are on pitch with beat 1 at {ss[0]:.2f}s, {tempos()}')
    if ag < .6:
        log('  ! that is too few to trust: is this the right part, and is the transcription right?')
    if accompaniment is not None:
        last = max(b for b, d, mi in notes)
        ss = attack_grid(accompaniment[0], accompaniment[1], sb, ss, [(b0, min(b1, last, sc.beats - 24)) for b0, b1 in zip(nb[:-1], nb[1:])])
        log(f'accompaniment attacks put beat 1 at {ss[0]:.3f}s, {tempos()}')
    beats, secs = follow(notes, sc.beats, t, m, sb, ss)
    dev = secs - np.interp(beats, sb, ss)
    moved = np.where(np.abs(dev) > .05)[0]
    if len(moved):
        b0 = beats[moved[0]]
        mnum = max(k for k in sc.measures if sc.measures[k][0] <= b0)
        log(f'tempo leaves the steady pulse at measure {mnum}; the last beat falls {dev[-1]:+.2f}s late')
    return {'offset': round(float(ss[0]), 3), 'bpm': round(60 / float(ss[1] - ss[0]), 3), 'agree': round(float(ag), 3),
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
