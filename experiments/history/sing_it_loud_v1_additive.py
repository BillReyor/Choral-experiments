"""Synthesised TTBB pop chorus with band, live-concert style.
Original song ("Sing It Loud"): words, melody and arrangement written for this render.
Voices: phoneme-driven formant synthesis (harmonics shaped by moving formants,
consonant noise, pitch glides, per-singer timing/tuning/timbre differences).
"""
import sys, wave, time
import numpy as np
from scipy.signal import fftconvolve, butter, sosfilt
from scipy.ndimage import gaussian_filter1d as gf
from multiprocessing import Pool, cpu_count

SR = 44100
HOP = 100
CR = SR / HOP
BEAT = 0.5          # 120 bpm
T0 = 2.6
STAB = 212          # beat of the final hit
TOTAL = T0 + STAB * BEAT + 12.0
N = int(TOTAL * SR)
FRAC = (np.arange(HOP) / HOP)


def T(b):
    return T0 + b * BEAT


# =========================================================== phonemes =====
VOW = {'IY': (280, 2250, 2900), 'IH': (400, 1950, 2560), 'EH': (550, 1770, 2500), 'AE': (680, 1650, 2480),
       'AA': (720, 1120, 2550), 'AH': (630, 1200, 2450), 'AO': (570, 850, 2450), 'UH': (440, 1020, 2300),
       'UW': (320, 870, 2300), 'ER': (480, 1350, 1700), 'AX': (500, 1400, 2500)}
DIPH = {'AY': ((720, 1150, 2550), (420, 1900, 2550)), 'AW': ((700, 1350, 2500), (450, 950, 2350)),
        'EY': ((500, 1850, 2550), (340, 2150, 2750)), 'OW': ((530, 930, 2400), (360, 820, 2300)),
        'OY': ((570, 850, 2450), (400, 1900, 2550))}
CONS = {
    'm': dict(F=(250, 1000, 2200), d=.070, av=.5, br=.12),
    'n': dict(F=(250, 1500, 2600), d=.065, av=.5, br=.12),
    'ng': dict(F=(250, 2000, 2700), d=.070, av=.5, br=.12),
    'l': dict(F=(360, 1100, 2700), d=.060, av=.75, br=.5),
    'r': dict(F=(330, 1100, 1500), d=.060, av=.75, br=.5),
    'w': dict(F=(300, 650, 2200), d=.060, av=.7, br=.4),
    'y': dict(F=(270, 2200, 3000), d=.055, av=.7, br=.5),
    'v': dict(F=(300, 1100, 2300), d=.060, av=.45, br=.25, noise='f', na=.25),
    'z': dict(F=(300, 1600, 2600), d=.070, av=.4, br=.25, noise='s', na=.5),
    'dh': dict(F=(300, 1500, 2550), d=.045, av=.4, br=.25, noise='f', na=.12),
    's': dict(F=(300, 1700, 2600), d=.095, av=0, noise='s', na=1.0),
    'sh': dict(F=(300, 1900, 2500), d=.095, av=0, noise='sh', na=.9),
    'f': dict(F=(300, 1100, 2300), d=.080, av=0, noise='f', na=.45),
    'h': dict(F=None, d=.065, av=0, noise='h', na=.55),
    'b': dict(stop=1, voiced=1, F=(200, 900, 2200), cl=.045, bd=.012, noise='p', na=.3),
    'd': dict(stop=1, voiced=1, F=(200, 1700, 2650), cl=.045, bd=.015, noise='t', na=.35),
    'g': dict(stop=1, voiced=1, F=(200, 2000, 2300), cl=.045, bd=.020, noise='k', na=.35),
    'p': dict(stop=1, voiced=0, F=(200, 900, 2200), cl=.055, bd=.022, noise='p', na=.7),
    't': dict(stop=1, voiced=0, F=(200, 1700, 2650), cl=.050, bd=.030, noise='t', na=.9),
    'k': dict(stop=1, voiced=0, F=(250, 1900, 2300), cl=.055, bd=.035, noise='k', na=.8),
}
FORMANT_BW = (70., 100., 130., 220., 260., 400., 450., 500.)


def cons_segs(c, scale):
    p = CONS[c]
    if p.get('stop'):
        v = p['voiced']
        return [dict(d=p['cl'] * scale, F=p['F'], av=.15 if v else 0., br=.06, noise=None, na=0, burst=False),
                dict(d=p['bd'] * scale, F=p['F'], av=.3 if v else 0., br=.3, noise=p['noise'], na=p['na'], burst=True)]
    return [dict(d=p['d'] * scale, F=p['F'], av=p['av'], br=p.get('br', .3), noise=p.get('noise'),
                 na=p.get('na', 0), burst=False)]


def cascade(f, F5, bwscale=1.0):
    H = np.ones_like(f, dtype=float)
    for Fi, Bi in zip(F5, FORMANT_BW):
        hb = Bi * bwscale / 2
        H = H * (Fi ** 2 + hb ** 2) / np.sqrt(((f - Fi) ** 2 + hb ** 2) * ((f + Fi) ** 2 + hb ** 2))
    return H


def nshape(typ, f, Fh=None):
    if typ == 's':
        return np.exp(-((f - 6500) / 2300) ** 2) * (f > 2500)
    if typ == 'sh':
        return np.exp(-((f - 3100) / 1200) ** 2) + .35 * np.exp(-((f - 5600) / 1600) ** 2)
    if typ == 'f':
        return (.3 + np.exp(-((f - 6000) / 4000) ** 2)) * (f > 800) * (f < 11000)
    if typ == 't':
        return np.exp(-((f - 5200) / 2400) ** 2) * (f > 1800)
    if typ == 'k':
        return np.exp(-((f - 2300) / 900) ** 2)
    if typ == 'p':
        return np.exp(-((f - 900) / 700) ** 2)
    if typ == 'h':
        F5 = list(Fh) + [3350, 4200]
        return cascade(f, F5, 2.0) * f / (f + 800) * (f < 9000)
    raise KeyError(typ)


def up(x):
    return (x[:-1, None] + (x[1:] - x[:-1])[:, None] * FRAC).ravel()


BREATH_SOS = butter(2, [1500, 7000], 'bandpass', fs=SR, output='sos')

# ============================================================ singers =====
SECT = {'T1': (-0.62, 1.06), 'T2': (-0.22, 1.03), 'BR': (0.22, 0.98), 'BS': (0.62, 0.93)}
PER_SECTION = 12


def singer_params(sect, idx):
    rng = np.random.default_rng(1000 * (list(SECT).index(sect) + 1) + idx)
    pan, fs = SECT[sect]
    return dict(pan=float(np.clip(pan + rng.uniform(-.2, .2), -1, 1)), fs=fs * rng.normal(1, .03),
                det=rng.normal(0, 12), tilt=rng.uniform(-.08, .14), vr=rng.uniform(5.0, 6.3), vd=rng.uniform(8, 22),
                lag=rng.normal(0, .014), scoop=rng.uniform(0, 50), port=rng.uniform(6, 11),
                fsig=rng.uniform(4, 7), cs=rng.uniform(.85, 1.2), gain=rng.uniform(.8, 1.2)), rng


def split_phrases(notes):
    notes = sorted(notes, key=lambda x: x[0])
    out, cur = [], []
    for nt in notes:
        if cur and nt[0] - (cur[-1][0] + cur[-1][1]) >= 0.24:
            out.append(cur); cur = []
        cur.append(nt)
    if cur:
        out.append(cur)
    return out


def render_phrase(ph, P, rng, out):
    n = len(ph)
    lag = P['lag'] + rng.normal(0, .012)
    ts = np.array([T(x[0]) for x in ph]) + lag + rng.normal(0, .010, n)
    ts = np.maximum.accumulate(ts)
    tend = T(ph[-1][0] + ph[-1][1]) + lag + rng.normal(0, .012)
    te = np.append(ts[1:], max(tend, ts[-1] + .09))
    mids = np.array([x[2] for x in ph], float)
    dyns = np.array([x[4] for x in ph], float)

    # ---- syllables -> onset / vowel / coda per note (melisma notes marked '-')
    on = [[] for _ in range(n)]
    co = [[] for _ in range(n)]
    vow = [None] * n
    head = [True] * n
    cur_v, cur_coda = 'AA', []
    for i, x in enumerate(ph):
        s = x[3]
        if s == '-':
            head[i] = False
            vow[i] = cur_v
        else:
            toks = s.split()
            vi = next(j for j, tk in enumerate(toks) if tk in VOW or tk in DIPH)
            cur_v = toks[vi]
            vow[i] = cur_v
            cur_coda = toks[vi + 1:]
            for c in toks[:vi]:
                on[i] += cons_segs(c, P['cs'] * rng.uniform(.9, 1.1))
        last = (i == n - 1) or ph[i + 1][3] != '-'
        if last:
            for c in cur_coda:
                co[i] += cons_segs(c, P['cs'] * rng.uniform(.9, 1.1))
    lastflag = [(i == n - 1) or ph[i + 1][3] != '-' for i in range(n)]
    for i in range(n):  # squeeze consonants into short notes
        need = sum(s['d'] for s in co[i]) + (sum(s['d'] for s in on[i + 1]) if i < n - 1 else 0)
        lim = 0.62 * (te[i] - ts[i])
        if need > lim:
            k = lim / need
            for s in co[i]:
                s['d'] *= k
            if i < n - 1:
                for s in on[i + 1]:
                    s['d'] *= k

    segs, noises = [], []

    def put(t, seglist, Fv):
        for s in seglist:
            segs.append((t, t + s['d'], s['F'], s['av'], s['br'], None))
            if s['noise']:
                noises.append((s['noise'], t, s['d'], s['na'], s['burst'], Fv))
            t += s['d']

    def vF(v):
        return DIPH[v][0] if v in DIPH else VOW[v]

    for i in range(n):
        if on[i]:
            put(ts[i] - sum(s['d'] for s in on[i]), on[i], vF(vow[i]))
        vend = te[i] - sum(s['d'] for s in co[i]) - (sum(s['d'] for s in on[i + 1]) if i < n - 1 else 0)
        v = vow[i]
        if v in DIPH:
            A, B = DIPH[v]
            if lastflag[i]:
                dg = min(.14, .45 * (vend - ts[i]))
                segs.append((ts[i], vend - dg, A, 1., 1., None))
                segs.append((vend - dg, vend, A, 1., 1., B))
            else:
                segs.append((ts[i], vend, A, 1., 1., None))
        else:
            segs.append((ts[i], vend, VOW[v], 1., 1., None))
        if co[i]:
            put(vend, co[i], vF(v))

    # ---- control-rate tracks
    tA = min(s[0] for s in segs) - .04
    tB = max(s[1] for s in segs) + .15
    M = int((tB - tA) * CR) + 2
    tc = tA + np.arange(M) / CR
    Ft = np.full((M, 3), np.nan)
    av = np.zeros(M)
    br = np.full(M, .3)
    for (a, b, F, v_, r_, F2) in segs:
        i0 = int(round((a - tA) * CR)); i1 = max(int(round((b - tA) * CR)), i0 + 1)
        if F is not None:
            if F2 is None:
                Ft[i0:i1] = F
            else:
                w = np.linspace(0, 1, i1 - i0)[:, None]
                Ft[i0:i1] = np.array(F) * (1 - w) + np.array(F2) * w
        av[i0:i1] = v_; br[i0:i1] = r_
    idx = np.where(~np.isnan(Ft[:, 0]))[0]
    Ft = Ft[idx[np.clip(np.searchsorted(idx, np.arange(M)), 0, len(idx) - 1)]]
    Ft = gf(Ft, P['fsig'], axis=0, mode='nearest')
    av = gf(av, 2.5, mode='nearest')
    br = gf(br, 3, mode='nearest')
    if not on[0]:
        av *= np.clip((tc - (ts[0] - .005)) / .03, 0, 1)
    if not co[-1]:
        tl = max(s[1] for s in segs)
        av *= np.clip((tl - tc) / .06, 0, 1)

    ni = np.clip(np.searchsorted(ts - .025, tc, side='right') - 1, 0, n - 1)
    mid = gf(mids[ni], P['port'], mode='nearest')
    dy = gf(dyns[ni], 12, mode='nearest')
    vstart = ts.copy()
    for i in range(1, n):
        if not head[i] and mids[i] == mids[i - 1]:
            vstart[i] = vstart[i - 1]
    depth = gf(P['vd'] * np.clip((tc - vstart[ni] - .25) / .3, 0, 1), 8, mode='nearest')
    drift = gf(rng.normal(0, 1, M), 60, mode='nearest') * np.sqrt(2 * np.sqrt(np.pi) * 60) * 6
    flut = gf(rng.normal(0, 1, M), 3, mode='nearest') * 7
    cents = (P['det'] + drift + flut + depth * np.sin(2 * np.pi * P['vr'] * tc + rng.uniform(0, 6.28))
             - P['scoop'] * np.exp(-np.clip(tc - ts[0], 0, None) / .05))
    f0 = 440 * 2 ** ((mid - 69) / 12 + cents / 1200)

    F = Ft * P['fs']
    F[:, 0] = np.maximum(F[:, 0], .92 * f0)
    F5 = [F[:, 0:1], F[:, 1:2], F[:, 2:3], 3000 * P['fs'], 3650 * P['fs'],
          4600 * P['fs'], 5600 * P['fs'], 6600 * P['fs']]   # upper resonances keep the top end open
    fc = (1500 + 4500 * dy) * br + 150
    K = int(min(7200 / f0.min(), 90))
    k = np.arange(1, K + 1)
    fk = f0[:, None] * k[None, :]
    A = cascade(fk, F5) * (1 / k)[None, :] / (1 + (fk / fc[:, None]) ** 2)
    A *= (1 + (fk / 1200) ** 2) ** (.15 * dy + P.get('tilt', 0))[:, None]   # belt/presence
    A[fk > 7200] = 0
    lvl = gf(np.sqrt((A ** 2).sum(1)), 40, mode='nearest')
    amp = av * dy ** 1.2
    A *= (amp / np.maximum(lvl, 1e-9) ** .85)[:, None]

    # ---- audio rate
    ns = (M - 1) * HOP
    phase = np.mod(np.cumsum(2 * np.pi * up(f0) / SR), 2 * np.pi).astype(np.float32)
    sig = np.zeros(ns, np.float32)
    amax = A.max()
    frac32 = FRAC.astype(np.float32)
    A32 = A.astype(np.float32)
    for j in range(K):
        col = A32[:, j]
        if col.max() < 3e-4 * amax:
            continue
        a = (col[:-1, None] + (col[1:] - col[:-1])[:, None] * frac32).ravel()
        sig += a * np.sin((j + 1) * phase)
    nz = sosfilt(BREATH_SOS, rng.standard_normal(ns))
    sig += (0.03 * nz / nz.std() * up(amp)).astype(np.float32)

    for (typ, t0, d, na, burst, Fv) in noises:
        m = int((d + (.03 if burst else .02)) * SR)
        x = rng.standard_normal(m)
        fr = np.fft.rfftfreq(m, 1 / SR)
        x = np.fft.irfft(np.fft.rfft(x) * nshape(typ, fr, Fv), m)
        x /= x.std() + 1e-9
        tt = np.arange(m) / SR
        if burst:
            e = np.exp(-tt / (d * .6)) * np.minimum(1, tt / .001)
            g = .22
        else:
            e = np.minimum(1, tt / .02) * np.minimum(1, (m / SR - tt) / .025)
            g = .11
        i0 = int((t0 - tA) * SR)
        dn = dy[min(int((t0 - tA) * CR), M - 1)]
        if i0 >= 0 and i0 + m <= ns:
            sig[i0:i0 + m] += (x * e * na * g * dn ** 1.2).astype(np.float32)

    i0 = int(tA * SR)
    if i0 >= 0 and i0 + ns <= len(out):
        out[i0:i0 + ns] += sig * P['gain']


def render_singer(args):
    sect, idx, notes = args
    P, rng = singer_params(sect, idx)
    out = np.zeros(N, np.float32)
    for ph in split_phrases(notes):
        render_phrase(ph, P, rng, out)
    return sect, P['pan'], out


# ============================================================== score =====
NOTE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def m(name):
    pc = NOTE[name[0]]; r = name[1:]
    if r[0] == '#':
        pc += 1; r = r[1:]
    return 12 * (int(r) + 1) + pc


CHD = {'G': (7, (7, 11, 2)), 'D': (2, (2, 6, 9)), 'Em': (4, (4, 7, 11)), 'C': (0, (0, 4, 7)), 'E': (4, (4, 8, 11))}
PROG = {'intro': ['G', 'D', 'Em', 'C'], 'verse8': ['Em', 'C', 'G', 'D'] * 2, 'verse4': ['Em', 'C', 'G', 'D'],
        'pre': ['C', 'D', 'C', 'D'], 'chorus': ['G', 'D', 'Em', 'C', 'G', 'D', ('C', 'D'), 'G'],
        'bridge': ['Em', 'C', 'G', ('D', 'E')], 'ext': ['G'], 'stab': ['G']}
FORM = [('intro', 0, 0), ('verse8', 4, 0), ('pre', 12, 0), ('chorus', 16, 0), ('verse4', 24, 0), ('pre', 28, 0),
        ('chorus', 32, 0), ('bridge', 40, 0), ('chorus', 44, 2), ('ext', 52, 2), ('stab', 53, 2)]
CHORDS = []   # (beat0, beat1, root, pcs, name)
SEC = {}
for name, sb, sh in FORM:
    for j, c in enumerate(PROG[name]):
        b0 = (sb + j) * 4
        SEC[sb + j] = (name, j, len(PROG[name]), sh)
        parts = [(c, b0, b0 + 4)] if isinstance(c, str) else [(c[0], b0, b0 + 2), (c[1], b0 + 2, b0 + 4)]
        for cn, x0, x1 in parts:
            r, p = CHD[cn]
            CHORDS.append((x0, x1, (r + sh) % 12, tuple((q + sh) % 12 for q in p), cn))


def chord_at(b):
    for c in CHORDS:
        if c[0] <= b < c[1]:
            return c
    return CHORDS[-1]


def voice(root, pcs, mel, prev):
    third = pcs[1]
    bass = min([x for x in range(40, 54) if x % 12 == root], key=lambda x: abs(x - prev[0]) + (.6 if x > 51 else 0))
    best = None
    for b in range(45, 65):
        if b % 12 not in pcs or b < bass:
            continue
        for t in range(50, 70):
            if t % 12 not in pcs or t < b or t > mel + 8 or (mel >= 57 and t > mel):
                continue
            allp = [bass % 12, b % 12, t % 12, mel % 12]
            c = .6 * (abs(b - prev[1]) + abs(t - prev[2])) + 1.2 * max(0, mel - t - 7) + .8 * max(0, t - b - 7)
            c += 8 * (third not in allp) + 1.5 * (pcs[2] not in allp) + 1.5 * (allp.count(third) > 1)
            c += 3 * (t == b) + 2 * (t == mel) + 2.5 * (t > mel)
            c += 3 * (b - bass < 4 and b < 50) + 5 * (b == bass)
            if best is None or c < best[0]:
                best = (c, b, t)
    return bass, best[1], best[2]


RV = [(0, .5), (.5, .5), (1, 1), (2, .5), (2.5, 1.25), (4, .5), (4.5, .5), (5, 1), (6, .5), (6.5, 1.25)]
VP = {1: 'B3 B3 D4 B3 A3 G3 G3 B3 A3 G3', 2: 'B3 B3 D4 B3 D4 E4 D4 B3 A3 A3',
      3: 'B3 B3 D4 B3 E4 E4 D4 E4 D4 C4', 4: 'B3 B3 D4 D4 B3 A3 B3 D4 E4 D4'}
VL = {
    'v1a': ['w EH n', 'dh AX', 'n AY', 't IH z', 'l AO ng', 'AE n', 'dh AX', 'r OW', 'd IH z', 'f AA'],
    'v1b': ['w IY', 'w IH l', 'l AY t', 'dh AX', 'w EY', 'w IY l', 'b IY', 'h UW', 'w IY', 'AA'],
    'v1c': ['EH', 'v r IY', 'v OY', 's AX', 'f l EY m', 'EH', 'v r IY', 'h AA', 't AX', 'd r AH m'],
    'v1d': ['AE n d', 'w IH r', 'n AA', 't AX', 'l OW n', 'l UH k', 'h AW', 'f AA', 'w IY v', 'k AH m'],
    'v2a': ['EH', 'v r IY', 'sh EY', 'd AH v', 'l AH v', 'EH', 'v r IY', 's t AO', 'r IY', 't OW l d'],
    'v2b': ['s AY d', 'b AY', 's AY d', 'w IY', 's t AE n d', 'b r EY v', 'AE n', 'b r AY t', 'AE n', 'b OW l d'],
}
PRE = [(0, .5, 'E4', 's OW'), (.5, 1, 'G4', 'r EY'), (1.5, .5, 'E4', 'z IH'), (2, 1.75, 'E4', 't AH p'),
       (4.5, 1, 'F#4', 'r EY'), (5.5, .5, 'F#4', 'z IH t'), (6, 1, 'A4', 'h AY'), (7, .75, 'F#4', 'ER'),
       (8, .5, 'G4', 'EH'), (8.5, .5, 'G4', 'v r IY'), (9, .5, 'G4', 'b AA'), (9.5, 1, 'E4', 'd IY'),
       (10.5, 1.25, 'G4', 'n AW'), (12, 1, 'A4', 'OW'), (13, 1, 'A4', '-'), (14, 1.5, 'A4', '-')]
PRE_DYN = lambda b: np.interp(b, [0, 4, 8, 12, 13, 14], [.72, .8, .88, .8, .9, 1.0])
CHO = [(0, .5, 'D4', 's IH'), (.5, .5, 'E4', 'ng IH t'), (1, 1.25, 'G4', 'l AW d'),
       (4, .5, 'D4', 's IH'), (4.5, .5, 'E4', 'ng IH t'), (5, 1.25, 'F#4', 'p r AW d'),
       (8, .5, 'E4', 'l EH t'), (8.5, .5, 'E4', 'dh AX'), (9, 1, 'G4', 'h OW l'), (10, 1, 'E4', 'w ER l d'),
       (11, .5, 'D4', 'h IY'), (11.5, .5, 'D4', 'r AH s'), (12, 2.75, 'E4', 'n AW'),
       (16, .5, 'D4', 's IH'), (16.5, .5, 'E4', 'ng IH t'), (17, 1.25, 'G4', 'l AW d'),
       (20, .5, 'D4', 's IH'), (20.5, .5, 'E4', 'ng IH t'), (21, 1.25, 'F#4', 'p r AW d'),
       (24, .5, 'E4', 'w IY'), (24.5, .5, 'E4', 'AA'), (25, 1, 'G4', 'h IY r'), (26, .5, 'D4', 'AE n'),
       (26.5, .5, 'D4', 'w IH r'), (27, .5, 'F#4', 's IH'), (27.5, .5, 'F#4', 'ng IH ng')]
CHO_END = [(28, 3, 'G4', 'AW t')]
CHO_END_FINAL = [(28, 3, 'G4', 'AW t'), (31, 2, 'G4', '-'), (33, 1.9, 'G4', '-'), (36, .6, 'G4', 'h EY')]
RESP = {'G': ('D4 E4 D4', 'B3 C4 B3', 'G3 G3 G3'), 'D': ('F#4 G4 F#4', 'D4 E4 D4', 'D3 D3 D3'),
        'C': ('E4 F#4 E4', 'C4 D4 C4', 'C3 C3 C3')}
BRI = ([(4 * j + b, d, p, 'l AA') for j, (lo, hi) in enumerate([('E4', 'G4'), ('E4', 'G4'), ('D4', 'G4')])
        for b, d, p in ((0, .5, lo), (.5, .5, lo), (1, .5, hi), (1.5, 1, lo))]
       + [(4 * j + 3, .75, 'G4', 'h EY') for j in range(3)]
       + [(12, .5, 'D4', 'l AA'), (12.5, .5, 'D4', 'l AA'), (13, .5, 'F#4', 'l AA'), (13.5, .5, 'F#4', 'l AA'),
          (14, 1, 'G#4', 'OW'), (15, .9, 'G#4', '-')])
BRI_DYN = lambda b: np.interp(b, [0, 4, 8, 12, 14, 15], [.68, .78, .9, .95, .95, 1.0])


def build_score():
    S = {k: [] for k in SECT}

    def mk(line, bar, shift, dyn):
        return [(bar * 4 + b, d, m(p) + shift, s, float(dyn(b)) if callable(dyn) else dyn)
                for (b, d, p, s) in sorted(line)]

    def harm(t1):
        prev = (43, 52, 57)
        for (b, d, mel, s, dy) in t1:
            _, _, root, pcs, _ = chord_at(b)
            prev = voice(root, pcs, mel, prev)
            S['BS'].append((b, d, prev[0], s, dy)); S['BR'].append((b, d, prev[1], s, dy))
            S['T2'].append((b, d, prev[2], s, dy))
        S['T1'] += [(b, d, mel, s, min(1.0, dy * 1.05)) for (b, d, mel, s, dy) in t1]

    def resp(bar, shift, dyn):
        cn = chord_at(bar * 4)[4]
        for sect, line in zip(('T2', 'BR', 'BS'), RESP[cn]):
            for j, p in enumerate(line.split()):
                S[sect].append((bar * 4 + 2.5 + .5 * j, .5, m(p) + shift, 'n AA', dyn))

    def vline(lyr, pit, bar):
        return [(bar * 4 + b, d, m(p), s) for (b, d), p, s in zip(RV, VP[pit].split(), VL[lyr])]

    def pad(sect, bar, pitches, syl, dyn):
        for j, p in enumerate(pitches.split()):
            S[sect].append(((bar + j) * 4, 3.7, m(p), syl, dyn))

    # intro
    resp(1, 0, .6); resp(3, 0, .65)
    # verse 1: T2 + baritones in unison, basses "oo"
    for lyr, pit, bar in (('v1a', 1, 4), ('v1b', 2, 6), ('v1c', 3, 8), ('v1d', 4, 10)):
        for (b, d, mi, s) in vline(lyr, pit, bar):
            dy = .78 if bar < 8 else .85
            S['T2'].append((b, d, mi, s, dy)); S['BR'].append((b, d, mi, s, dy))
    pad('BS', 4, 'E3 C3 G2 D3 E3 C3 G2 D3', 'UW', .5)
    # verse 2: tenors in unison, baritones "oo", basses "doom" riff
    for lyr, pit, bar in (('v2a', 3, 24), ('v2b', 4, 26)):
        for (b, d, mi, s) in vline(lyr, pit, bar):
            S['T1'].append((b, d, mi, s, .86)); S['T2'].append((b, d, mi, s, .86))
    pad('BR', 24, 'G3 G3 G3 A3', 'UW', .5)
    for j, p in enumerate('E2 C3 G2 D3'.split()):
        for b, d in ((0, 1), (1.5, .5), (2, 1), (3, .5), (3.5, .5)):
            S['BS'].append(((24 + j) * 4 + b, d * .9, m(p), 'd UW m', .72))
    # pre-choruses and choruses
    for bar in (12, 28):
        harm(mk(PRE, bar, 0, PRE_DYN))
    for bar, sh, end, dy in ((16, 0, CHO_END, .95), (32, 0, CHO_END, .97), (44, 2, CHO_END_FINAL, 1.0)):
        harm(mk(CHO + end, bar, sh, dy))
        for rb in (0, 1, 4, 5):
            resp(bar + rb, sh, .82)
    harm(mk(BRI, 40, 0, BRI_DYN))
    return S


# =============================================================== band =====
def main():
    out_path = sys.argv[1]
    t_start = time.time()
    rng = np.random.default_rng(5)
    S = build_score()
    tasks = [(sect, i, S[sect]) for sect in SECT for i in range(PER_SECTION)]
    vox = np.zeros((N, 2))
    with Pool(min(10, cpu_count())) as pool:
        for sect, pan, mono in pool.imap_unordered(render_singer, tasks):
            th = (pan + 1) * np.pi / 4
            vox[:, 0] += mono * np.cos(th); vox[:, 1] += mono * np.sin(th)
    vox /= np.sqrt(len(tasks))
    print('voices done %.0fs' % (time.time() - t_start), flush=True)

    stems = {k: np.zeros((N, 2)) for k in ('drums', 'bass', 'piano', 'strings', 'claps', 'crowd')}

    def add(stem, t, sig, gain=1.0, pan=0.0):
        i0 = int(t * SR)
        if i0 < 0:
            return
        sig = sig[:max(0, N - i0)]
        th = (pan + 1) * np.pi / 4
        stems[stem][i0:i0 + len(sig), 0] += sig * gain * np.cos(th) * 1.414
        stems[stem][i0:i0 + len(sig), 1] += sig * gain * np.sin(th) * 1.414

    def tarr(d):
        return np.arange(int(d * SR)) / SR

    def bp(x, lo, hi):
        return sosfilt(butter(2, [lo, hi], 'bandpass', fs=SR, output='sos'), x)

    def hp(x, lo):
        return sosfilt(butter(3, lo, 'high', fs=SR, output='sos'), x)

    def norm(x):
        return x / np.abs(x).max()

    t = tarr(.35)
    KICK = np.sin(2 * np.pi * np.cumsum(48 + 130 * np.exp(-t / .028)) / SR) * np.exp(-t / .13)
    KICK[:200] += rng.normal(0, .3, 200) * np.linspace(1, 0, 200)
    KICK = norm(KICK)
    t = tarr(.25)
    SNARE = norm(.6 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / .05) + .3 * np.sin(2 * np.pi * 290 * t) * np.exp(-t / .035)
                 + norm(bp(rng.standard_normal(len(t)), 1200, 9000)) * np.exp(-t / .07) * .9)
    env = sum(np.exp(-np.clip(t - o, 0, None) / .006) * (t >= o) for o in (0, .011, .022, .031))
    env = env + .5 * np.exp(-np.clip(t - .031, 0, None) / .06) * (t >= .031)
    KCLAP = norm(bp(rng.standard_normal(len(t)), 900, 3200) * env)
    t = tarr(.08); HATC = norm(hp(rng.standard_normal(len(t)), 7000) * np.exp(-t / .018))
    t = tarr(.3); HATO = norm(hp(rng.standard_normal(len(t)), 6500) * np.exp(-t / .09))
    t = tarr(.15); TAMB = norm(hp(rng.standard_normal(len(t)), 5500) * np.exp(-t / .035) * (1 + .5 * np.sin(2 * np.pi * 90 * t)))
    t = tarr(2.6); CRASH = norm(hp(rng.standard_normal(len(t)), 3500) * np.exp(-t / .7) * np.minimum(1, t / .002))
    t = tarr(.05); STICK = norm((np.sin(2 * np.pi * 2100 * t) + .6 * np.sin(2 * np.pi * 3300 * t)) * np.exp(-t / .006))
    CLAPPOOL = norm(bp(rng.standard_normal(SR * 2), 800, 3000))

    def tom(f):
        t = tarr(.4)
        return np.sin(2 * np.pi * np.cumsum(f * (1 + .6 * np.exp(-t / .03))) / SR) * np.exp(-t / .14)

    def kick(b, v=1.0): add('drums', T(b), KICK, v)
    def snare(b, v=.8): add('drums', T(b), SNARE, v * .85, .05)
    def kclap(b, v=.5): add('drums', T(b), KCLAP, v, -.1)
    def hatc(b, v=.25): add('drums', T(b), HATC, v, .3)
    def hato(b, v=.3): add('drums', T(b), HATO, v * .65, .3)
    def tamb(b, v=.2): add('drums', T(b), TAMB, v * .6, -.4)
    def crash(b, v=.5): add('drums', T(b), CRASH, v * .7, -.2)

    def gclap(b, v=1.0):
        t = tarr(.12)
        e = np.exp(-t / .012) + .15 * np.exp(-t / .05)
        for _ in range(20):
            o = rng.integers(0, len(CLAPPOOL) - len(t))
            add('claps', T(b) + rng.normal(0, .012), CLAPPOOL[o:o + len(t)] * e, v * rng.uniform(.5, 1), rng.uniform(-.85, .85))

    def piano(midi, tsec, vel, dur=1.6):
        f0 = 440 * 2 ** ((midi - 69) / 12)
        t = tarr(dur)
        sig = np.zeros(len(t))
        for k in range(1, 16):
            fk = k * f0 * np.sqrt(1 + .00035 * k * k)
            if fk > 8000:
                break
            sig += (1 / k ** (1.7 - .7 * vel)) * np.exp(-t * (1.0 + .5 * k) * (f0 / 200) ** .45) * np.sin(2 * np.pi * fk * t + rng.uniform(0, 6.28))
        sig[:176] *= np.linspace(0, 1, 176); sig[-2000:] *= np.linspace(1, 0, 2000)
        add('piano', tsec, sig, vel, float(np.clip((midi - 62) / 50, -.4, .4)))

    def bassn(midi, b, dur, vel=.8):
        f0 = 440 * 2 ** ((midi - 69) / 12)
        t = tarr(dur * BEAT + .06)
        sig = .5 * np.sin(2 * np.pi * f0 * t)
        for k in range(1, 14):
            if k * f0 > 3000:
                break
            sig += (1 / k ** 1.2) * np.exp(-t * (.8 + .5 * k)) * np.sin(2 * np.pi * k * f0 * t)
        sig *= np.minimum(1, t / .004) * np.minimum(1, (t[-1] - t) / .05)
        add('bass', T(b), np.tanh(1.5 * sig), vel)

    def padn(midi, b, dur, vel=.5):
        t = tarr(dur * BEAT + .4)
        sig = np.zeros(len(t))
        for det in (-7, 0, 6):
            f = 440 * 2 ** ((midi - 69) / 12 + det / 1200)
            for k in range(1, 30):
                if k * f > 4500:
                    break
                sig += (1 / k) / (1 + (k * f / 2200) ** 2) * np.sin(2 * np.pi * k * f * t + rng.uniform(0, 6.28))
        sig *= np.clip(t / .15, 0, 1) * np.clip((t[-1] - t) / .35, 0, 1)
        add('strings', T(b), sig, vel, rng.uniform(-.5, .5))

    def pchord(b, vel, dur=1.6, lh=False, bright=False):
        _, _, root, pcs, _ = chord_at(b)
        rh = [x for x in range(57, 69) if x % 12 in pcs]
        for x in rh:
            piano(x, T(b), vel, dur)
        if bright:
            piano(rh[-1] + 12, T(b), vel * .7, dur)
        if lh:
            lo = [x for x in range(36, 48) if x % 12 == root][0]
            piano(lo, T(b), vel * 1.1, dur + .6); piano(lo - 12, T(b), vel * .8, dur + .6)

    def broot(b):
        root = chord_at(b)[2]
        return [x for x in range(28, 40) if x % 12 == root][0]

    def strings(b, dur, vel=.5):
        pcs = chord_at(b)[3]
        for x in [x for x in range(62, 77) if x % 12 in pcs]:
            padn(x, b, dur, vel)

    for j in range(4):  # drummer's count-in
        add('drums', T(-4 + j), STICK, .5, .1)

    for bar in range(53):
        kind, j, nb, sh = SEC[bar]
        b0 = bar * 4
        halves = [b0] if chord_at(b0)[1] - b0 >= 4 else [b0, b0 + 2]
        if kind == 'intro':
            for e in range(8):
                pchord(b0 + e / 2, .5 if e in (0, 3, 6) else .32, 1.0, lh=e in (0, 5))
            if j >= 2:
                for q in range(4):
                    kick(b0 + q, .9); hatc(b0 + q + .5, .3)
                for b, d in ((0, 1.4), (1.5, .45), (2, 1.4), (3.5, .45)):
                    bassn(broot(b0 + b), b0 + b, d)
            if j == 3:
                snare(b0 + 3, .6); snare(b0 + 3.5, .7); snare(b0 + 3.75, .8)
        elif kind in ('verse8', 'verse4'):
            v2 = kind == 'verse4'
            for q in range(4):
                kick(b0 + q, .85)
                hatc(b0 + q, .16); hatc(b0 + q + .5, .28)
                if v2:
                    hatc(b0 + q + .25, .1); hatc(b0 + q + .75, .1)
            snare(b0 + 1, .65 if v2 else .55); snare(b0 + 3, .65 if v2 else .55)
            if j == nb - 1:
                snare(b0 + 3.5, .6); snare(b0 + 3.75, .7)
            for b, v in ((0, .4), (1.5, .33), (2.5, .26), (3.5, .33)):
                pchord(b0 + b, v, 1.4, lh=b == 0)
            for b, d in ((0, 1.4), (1.5, .45), (2, 1.4), (3.5, .45)):
                bassn(broot(b0 + b), b0 + b, d)
        elif kind == 'pre':
            last = j == nb - 1
            for q in range(4):
                kick(b0 + q, .9); hatc(b0 + q, .18); hatc(b0 + q + .5, .3)
            if last:
                for e in range(4):
                    snare(b0 + e / 2, .45 + .06 * e)
                for e in range(8):
                    snare(b0 + 2 + e / 4, .6 + .05 * e)
                strings(b0, 3.5, .5)
            else:
                snare(b0 + 1, .7); snare(b0 + 3, .7)
            for e in range(8):
                v = .34 + .04 * j + (.08 if e % 2 == 0 else 0)
                pchord(b0 + e / 2, v, .9, lh=e == 0)
                bassn(broot(b0), b0 + e / 2, .45, .7 + .05 * j)
        elif kind == 'chorus':
            final = sh == 2
            if j in (0, 4):
                crash(b0, .55)
            for q in range(4):
                kick(b0 + q, 1.0); hato(b0 + q + .5, .3)
                for s16 in range(4):
                    tamb(b0 + q + s16 / 4, .2 if s16 % 2 == 0 else .11)
            for q in (1, 3):
                snare(b0 + q, .85); kclap(b0 + q, .5)
                if bar >= 32:
                    gclap(b0 + q, 1.0)
            if j == nb - 1 and not final:
                for b, f in ((3, 190), (3.25, 190), (3.5, 145), (3.75, 105)):
                    add('drums', T(b0 + b), tom(f), .8, -.2)
            for hb in halves:
                pchord(hb, .6, 1.6, lh=True, bright=True)
                strings(hb, 4 if len(halves) == 1 else 2, .5)
            for q in range(4):
                pchord(b0 + q + .5, .5, .6, bright=True)
                bassn(broot(b0 + q), b0 + q, .45, .85); bassn(broot(b0 + q) + 12, b0 + q + .5, .4, .7)
        elif kind == 'bridge':
            for q in range(4):
                kick(b0 + q, 1.0)
            gclap(b0 + 1, 1.2); gclap(b0 + 3, 1.2)
            if j == 2:
                snare(b0 + 1, .6); snare(b0 + 3, .6)
                bassn(broot(b0), b0, 3.8, .8)
            if j == 3:
                for e in range(4):
                    snare(b0 + e / 2, .5 + .06 * e)
                for e in range(8):
                    snare(b0 + 2 + e / 4, .65 + .05 * e)
                bassn(broot(b0), b0, 1.9, .85); bassn(broot(b0 + 2), b0 + 2, 1.9, .9)
                strings(b0 + 2, 1.8, .6)
                for e in range(4):
                    pchord(b0 + 2 + e / 2, .45 + .06 * e, .8, lh=e == 0, bright=True)
        elif kind == 'ext':
            crash(b0, .5)
            pchord(b0, .65, 3.0, lh=True, bright=True)
            bassn(broot(b0), b0, 2.9, .9)
            strings(b0, 2.8, .6)
            for e in range(24):
                snare(b0 + e / 8, .3 + .7 * e / 24)
            for q in range(3):
                kick(b0 + q, 1.0); crash(b0 + q + .5, .15 + .08 * q)
    kick(STAB, 1.1); snare(STAB, 1.0); crash(STAB, .7); gclap(STAB, 1.2)
    pchord(STAB, .75, 2.5, lh=True, bright=True)
    bassn(broot(STAB), STAB, 1.0, 1.0); strings(STAB, .5, .6)

    # ------------------------------------------------------------- crowd --
    a0 = T(STAB) + .3
    alen = 10.0
    ncl = 7000
    ct = a0 + alen * rng.beta(1.15, 2.6, ncl)
    for c in range(2):
        imp = np.zeros(N)
        idx = (ct * SR).astype(int) + rng.integers(0, 400, ncl)
        idx = idx[idx < N]
        np.add.at(imp, idx, rng.uniform(.2, 1, len(idx)))
        t = tarr(.02)
        ker = bp(rng.standard_normal(len(t)) * np.exp(-t / .0035), 900, 3800)
        stems['crowd'][:, c] += fftconvolve(imp, ker)[:N]
    stems['crowd'] /= np.abs(stems['crowd']).max()
    cheer = np.zeros(N, np.float32)
    for i in range(16):  # "woo!" cheers through the same voice engine
        P = dict(pan=0, fs=rng.uniform(1.05, 1.2), det=rng.normal(0, 150), vr=6, vd=0, lag=0, scoop=0,
                 port=rng.uniform(25, 45), fsig=6, cs=1, gain=1)
        b = (a0 + rng.beta(1.1, 2.5) * (alen - 3) - T0) / BEAT
        base = rng.integers(69, 76)
        ph = [(b, .5, base, 'w UW', .9), (b + .5, rng.uniform(1, 2.2), base + rng.integers(5, 9), '-', .95),
              (b + 3, .8, base + 1, '-', .6)]
        ph[2] = (ph[1][0] + ph[1][1], .8, base + 1, '-', .6)
        tmp = np.zeros(N, np.float32)
        render_phrase(ph, P, rng, tmp)
        th = (rng.uniform(-.9, .9) + 1) * np.pi / 4
        stems['crowd'][:, 0] += tmp * np.cos(th) * .25 * rng.uniform(.5, 1)
        stems['crowd'][:, 1] += tmp * np.sin(th) * .25 * rng.uniform(.5, 1)
    for i in range(4):  # whistles
        d = rng.uniform(.5, .9)
        t = tarr(d)
        f = np.interp(t, [0, d * .5, d], [rng.uniform(1500, 1900), rng.uniform(2500, 3000), rng.uniform(1800, 2200)])
        w = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / d) ** .5
        add('crowd', a0 + rng.uniform(.3, alen - 4), w, .06, rng.uniform(-.8, .8))

    # ------------------------------------------------------ hall and mix --
    def make_ir(seed, rt_lo=1.6, rt_hi=1.0):
        r = np.random.default_rng(seed)
        n = int(2.2 * SR)
        t = np.arange(n) / SR
        x = r.normal(0, 1, n)
        lo = sosfilt(butter(2, 1200, 'low', fs=SR, output='sos'), x)
        hi = sosfilt(butter(2, [1200, 10000], 'bandpass', fs=SR, output='sos'), x)
        ir = (lo * np.exp(-6.91 * t / rt_lo) + .8 * hi * np.exp(-6.91 * t / rt_hi)) * np.clip(t / .04, 0, 1) ** 1.5
        for tt, g in zip(r.uniform(.006, .06, 7), np.linspace(.9, .3, 7)):
            ir[int(tt * SR)] += g * r.choice([-1, 1]) * 12
        ir = np.concatenate([np.zeros(int(.015 * SR)), ir])
        return ir / np.sqrt((ir ** 2).sum())

    IRS = [make_ir(100), make_ir(101)]

    def hall(x):
        return np.stack([fftconvolve(x[:, c], IRS[c])[:N] for c in range(2)], axis=1)

    def rms(x, b0, b1):
        seg = x[int(T(b0) * SR):int(T(b1) * SR)]
        return np.sqrt((seg ** 2).mean()) + 1e-12

    vox_m = .7 * vox + .45 * hall(vox)
    ref = rms(vox_m, 128, 160)                      # second chorus
    wet = {'drums': .15, 'bass': .03, 'piano': .2, 'strings': .35, 'claps': .3}
    target = {'drums': .42, 'bass': .36, 'piano': .30, 'strings': .15, 'claps': .22}
    band = np.zeros((N, 2))
    for k in wet:
        s = stems[k] + wet[k] * hall(stems[k])
        g = target[k] * ref / rms(s, 128, 160)
        print('%-8s gain %.3f' % (k, g))
        band += g * s
    blk = SR // 50                                   # ride the band under the singers

    def envl(x):
        p = (x ** 2).mean(1)
        return np.sqrt(gf(p[:len(p) // blk * blk].reshape(-1, blk).mean(1), 50, mode='nearest'))

    ev, eb = envl(vox_m), envl(band)
    g = np.where(ev > .12 * ref, np.clip(.9 * ev / np.maximum(eb, 1e-9), .45, 1.0), 1.0)
    g = gf(g, 20, mode='nearest')
    gs = np.interp(np.arange(N), (np.arange(len(g)) + .5) * blk, g)
    band *= gs[:, None]
    for nm, b0, b1 in (('intro', 0, 16), ('verse1', 16, 48), ('pre1', 48, 64), ('chorus1', 64, 96), ('verse2', 96, 112),
                       ('chorus2', 128, 160), ('bridge', 160, 176), ('final', 176, 208)):
        print('%-8s vox %.1f dB  band %.1f dB' % (nm, 20 * np.log10(rms(vox_m, b0, b1)), 20 * np.log10(rms(band, b0, b1))))
    mix = vox_m + band
    cr = .5 * stems['crowd'] + .5 * hall(stems['crowd'])
    i0 = int(a0 * SR)
    w = cr[i0:i0 + 8 * SR]
    peak1s = np.sqrt((w[:len(w) // SR * SR] ** 2).mean(axis=1).reshape(-1, SR).mean(axis=1)).max()
    mix += cr * (1.0 * ref / peak1s)

    if len(sys.argv) > 2:  # dry vocal stem for inspection
        v = vox / np.abs(vox).max() * .9
        with wave.open(sys.argv[2], 'wb') as wv:
            wv.setnchannels(2); wv.setsampwidth(2); wv.setframerate(SR)
            wv.writeframes((v * 32767).astype('<i2').tobytes())

    mix = sosfilt(butter(2, 35, 'high', fs=SR, output='sos'), mix, axis=0)
    end = int((a0 + alen + .5) * SR)
    mix = mix[:end]
    nf = int(3.0 * SR)
    mix[-nf:] *= np.linspace(1, 0, nf)[:, None] ** 2
    mix /= np.percentile(np.abs(mix), 99.9)
    mix = np.tanh(1.1 * mix)                         # gentle bus limiting
    mix *= .93 / np.abs(mix).max()
    with wave.open(out_path, 'wb') as wv:
        wv.setnchannels(2); wv.setsampwidth(2); wv.setframerate(SR)
        wv.writeframes((mix * 32767).astype('<i2').tobytes())
    print('wrote %s  %.1fs  (%.0fs to render)' % (out_path, len(mix) / SR, time.time() - t_start))


if __name__ == '__main__':
    main()
