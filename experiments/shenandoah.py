"""Synthesised TTBB men's chorus + piano in a concert hall.
Song: "Shenandoah" (traditional, public domain), original arrangement.
Verse 1 in F: unison melody over a bass hum.  Verse 2 in G: four-part harmony.
"""
import sys, wave
import numpy as np
from scipy.signal import fftconvolve, butter, sosfilt

sr = 44100
rng = np.random.default_rng(11)
OUT = sys.argv[1]

# ---------------------------------------------------------------- time ----
STEP = 0.25
LAST = 112
steps = np.arange(0, LAST + 8 + STEP, STEP)
bpm = np.interp(steps, [0, 44, 51.9, 52, 90, 100, 104, 112], [66, 66, 57, 66, 66, 54, 50, 44])
tgrid = np.concatenate([[0], np.cumsum(60 / bpm * STEP)])[:len(steps)] + 0.4


def T(b):
    return float(np.interp(b, steps, tgrid))


DYN_B = [0, 7, 23, 36, 44, 52, 55, 71, 80, 84, 88, 92, 96, 100, 104, 112, 120]
DYN_V = [.5, .45, .55, .62, .5, .45, .62, .75, .88, 1., .85, .58, .42, .32, .26, .10, .0]


def dyn_b(b):
    return float(np.interp(b, DYN_B, DYN_V))


def dyn_t(t):
    return np.interp(np.interp(t, tgrid, steps), DYN_B, DYN_V)


TOTAL = T(LAST) + 15.0
N = int(TOTAL * sr)
chorus = np.zeros((N, 2))
pno = np.zeros((N, 2))

# --------------------------------------------------------------- voices ---
VOW = {'a': (700, 1100, 2500), 'e': (500, 1700, 2450), 'i': (310, 2100, 2850),
       'o': (500, 850, 2450), 'u': (330, 800, 2300)}
FG = np.array([1.0, 0.55, 0.30, 0.24, 0.10])
FBW = np.array([90, 110, 150, 180, 220.])


def spec_env(f, vowel, scale):
    F = np.array(list(VOW[vowel]) + [3250, 3900.]) * scale
    e = 0.2 / (1 + (f / 1000) ** 2)
    for Fi, g, bw in zip(F, FG, FBW):
        e = e + g / (1 + ((f - Fi) / bw) ** 2)
    return e


SECT = {  # centre pan, formant scale, vibrato depth range (cents), level
    'T1': (-0.65, 1.05, (16, 34), 1.00),
    'T2': (-0.22, 1.02, (14, 30), 0.90),
    'BR': (0.22, 0.98, (12, 28), 0.92),
    'BS': (0.65, 0.93, (8, 22), 1.05),
}
PER_SECTION = 12
singers = {}
for name, (pan, fs, vd, lvl) in SECT.items():
    singers[name] = [dict(
        pan=np.clip(pan + rng.uniform(-.22, .22), -1, 1),
        fs=fs * rng.normal(1, 0.035),
        det=rng.normal(0, 9),
        vr=rng.uniform(4.7, 6.3),
        vd=rng.uniform(*vd),
        gain=lvl * rng.uniform(.8, 1.2),
        lag=rng.normal(0, 0.012),
        scoop=rng.uniform(0, 35),
    ) for _ in range(PER_SECTION)]


def sing(section, midi, t0, t1, vowel, dyn, level=1.0, rel=0.16, final=False):
    f0 = 440 * 2 ** ((midi - 69) / 12)
    fc = 1400 + 3600 * dyn
    for s in singers[section]:
        on = t0 + s['lag'] + rng.normal(0, 0.018)
        off = t1 + rng.normal(0, 0.02)
        if off - on < 0.12:
            off = on + 0.12
        r = rel * rng.uniform(.8, 1.3)
        n = int((off - on + r) * sr)
        t = np.arange(n) / sr
        vib = s['vd'] * np.clip((t - 0.15) / 0.4, 0, 1)
        cents = (s['det'] + rng.normal(0, 3)
                 + vib * np.sin(2 * np.pi * s['vr'] * t + rng.uniform(0, 6.28))
                 + 5 * np.sin(2 * np.pi * rng.uniform(.4, .9) * t + rng.uniform(0, 6.28))
                 - s['scoop'] * np.exp(-t / 0.045))
        phase = 2 * np.pi * np.cumsum(f0 * 2 ** (cents / 1200)) / sr
        k = np.arange(1, int(5500 / f0) + 1)
        fk = k * f0
        a = (1 / k) * spec_env(fk, vowel, s['fs']) / (1 + (fk / fc) ** 2)
        a /= np.sqrt((a ** 2).sum())
        sig = np.zeros(n)
        thr = a.max() * 2e-3
        for kk, ak in zip(k, a):
            if ak > thr:
                sig += ak * np.sin(kk * phase)
        env = np.ones(n)
        na = int(rng.uniform(.05, .09) * sr)
        env[:na] = 0.5 - 0.5 * np.cos(np.pi * np.arange(na) / na)
        nr = int(r * sr)
        env[-nr:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(nr) / nr)
        env *= 1 + 0.05 * np.sin(2 * np.pi * rng.uniform(2, 4) * t + rng.uniform(0, 6.28))
        d = dyn_t(on + t) if final else np.full(n, dyn)
        sig *= env * d ** 1.4 * s['gain'] * level
        i0 = int(on * sr)
        if i0 < 0 or i0 + n > N:
            continue
        th = (s['pan'] + 1) * np.pi / 4
        chorus[i0:i0 + n, 0] += sig * np.cos(th)
        chorus[i0:i0 + n, 1] += sig * np.sin(th)


# ---------------------------------------------------------------- piano ---
def piano(midi, t0, vel, dur=3.0):
    f0 = 440 * 2 ** ((midi - 69) / 12)
    n = int(dur * sr)
    t = np.arange(n) / sr
    sig = np.zeros(n)
    for k in range(1, 16):
        fk = k * f0 * np.sqrt(1 + 0.00035 * k * k)
        if fk > 7000:
            break
        a = 1 / k ** (1.9 - 0.7 * vel)
        dec = (0.7 + 0.45 * k) * (f0 / 200) ** 0.45
        sig += a * np.exp(-t * dec) * np.sin(2 * np.pi * fk * t + rng.uniform(0, 6.28))
    na = int(0.004 * sr)
    sig[:na] *= np.linspace(0, 1, na)
    sig[-2000:] *= np.linspace(1, 0, 2000)
    sig *= vel * 0.5
    i0 = int(t0 * sr)
    th = (np.clip((midi - 60) / 60, -.4, .4) + 1) * np.pi / 4
    pno[i0:i0 + n, 0] += sig * np.cos(th)
    pno[i0:i0 + n, 1] += sig * np.sin(th)


# ----------------------------------------------------------------- score --
CH = {'I': (0, 4, 7), 'ii': (2, 5, 9), 'iii': (4, 7, 11), 'IV': (5, 9, 0), 'V': (7, 11, 2), 'vi': (9, 0, 4)}
# (scale offset from tonic, beats, vowel, chord, breath-after)
VERSE = [
    (-5, 1, 'o', 'I', 0),
    (0, .5, 'e', 'I', 0), (0, .5, 'a', 'I', 0), (0, 1.5, 'o', 'I', 0), (2, .5, 'a', 'I', 0), (4, .5, 'o', 'I', 0), (5, .5, 'u', 'IV', 0),
    (9, 1, 'i', 'IV', 0), (7, 2, 'u', 'I', 1), (12, 1, 'a', 'I', 0),
    (11, 1.5, 'e', 'iii', 0), (9, .5, 'u', 'IV', 0), (7, .5, 'o', 'IV', 0), (9, .5, 'i', 'IV', 0), (7, 1, 'i', 'I', 0),
    (4, 2, 'a', 'vi', 1), (None, 1, '', '', 0), (7, 1, 'o', 'I', 0),
    (9, .5, 'e', 'IV', 0), (9, .5, 'a', 'IV', 0), (9, 1.5, 'o', 'IV', 0), (4, .5, 'a', 'I', 0), (7, .5, 'o', 'I', 0), (4, .5, 'u', 'I', 0),
    (2, 1, 'i', 'V', 0), (0, 2, 'u', 'vi', 1), (2, 1, 'a', 'ii', 0),
    (4, 3, 'e', 'I', 1), (0, 1, 'a', 'I', 0),
    (4, 1, 'a', 'vi', 0), (9, 1, 'a', 'IV', 0), (7, 2, 'e', 'I', 1),
    (0, 1, 'o', 'IV', 0), (2, 1, 'a', 'V', 0), (4, 2, 'a', 'vi', 1),
    (0, 1, 'i', 'IV', 0), (2, 3, 'u', 'V', 1),
    (0, 4, 'i', 'I', 1),
]
assert abs(sum(v[1] for v in VERSE) - 45) < 1e-9

beat_chord = {}  # global beat -> list of pitch classes (root first)


def set_chords(start, tonic, first=None):
    b = 0.0
    for i, (deg, dur, vow, ch, br) in enumerate(VERSE):
        if deg is not None:
            c = first if (i == 0 and first) else ch
            pcs = [(tonic + x) % 12 for x in CH[c]]
            q = np.ceil(b - 1e-9)
            while q < b + dur - 1e-9:
                beat_chord[int(start + q)] = pcs
                q += 1
        b += dur


def voice(tonic, chord, mel, prev):
    pcs = [(tonic + x) % 12 for x in CH[chord]]
    third = pcs[1]
    bass = min([m for m in range(40, 53) if m % 12 == pcs[0]], key=lambda m: abs(m - prev[0]) + (0.6 if m > 50 else 0))
    best = None
    for b in range(45, 63):
        if b % 12 not in pcs or b < bass:
            continue
        for t in range(48, 66):
            if t % 12 not in pcs or t < b or t > mel + 8 or (mel >= 57 and t > mel):
                continue
            allp = [bass % 12, b % 12, t % 12, mel % 12]
            c = 0.6 * (abs(b - prev[1]) + abs(t - prev[2])) + 1.2 * max(0, mel - t - 7) + 0.8 * max(0, t - b - 7)
            c += 8 * (third not in allp) + 1.5 * (pcs[2] not in allp) + 1.5 * (allp.count(third) > 1)
            c += 3 * (t == b) + 2 * (t == mel) + 2.5 * (t > mel) + 3 * (t - b > 9)
            c += 3 * (b - bass < 4 and b < 50) + 5 * (b == bass)
            if best is None or c < best[0]:
                best = (c, b, t)
    return bass, best[1], best[2]


def verse1(start, tonic):
    b = 0.0
    run = None  # bass hum: [chord, start_beat, end_beat]
    prev_bass = 41

    def flush():
        nonlocal prev_bass
        if run:
            pc = (tonic + CH[run[0]][0]) % 12
            m = min([x for x in range(40, 51) if x % 12 == pc], key=lambda x: abs(x - prev_bass))
            prev_bass = m
            sing('BS', m, T(start + run[1]), T(start + run[2]) - 0.05, 'u', dyn_b(start + run[1]) * 0.85)

    for deg, dur, vow, ch, br in VERSE:
        if deg is None:
            flush(); run = None
        else:
            g = start + b
            end = g + dur - (0.4 if br else 0)
            d = dyn_b(g)
            for sec in ('T2', 'BR') + (('T1',) if b >= 17 else ()):
                sing(sec, tonic + deg, T(g), T(end), vow, d)
            if run and run[0] == ch:
                run[2] = b + dur - (0.4 if br else 0)
            else:
                flush(); run = [ch, b, b + dur - (0.4 if br else 0)]
            if br:
                flush(); run = None
        b += dur
    flush()


def verse2(start, tonic):
    b = 0.0
    prev = (43, 50, 55)
    for i, (deg, dur, vow, ch, br) in enumerate(VERSE):
        if deg is not None:
            if i == 0:
                ch = 'V'
            mel = tonic + deg
            bs, br_, t2 = voice(tonic, ch, mel, prev)
            prev = (bs, br_, t2)
            g = start + b
            end = g + dur - (0.4 if br else 0)
            d = dyn_b(g)
            last = i == len(VERSE) - 1
            print(f'{b:5.1f} {ch:4s} B{bs} Br{br_} T2 {t2} T1 {mel}')
            sing('T1', mel, T(g), T(end), vow, d, 1.15)
            sing('T2', t2, T(g), T(end), vow, d)
            sing('BR', br_, T(g), T(end), vow, d)
            sing('BS', bs, T(g), T(end), vow, d)
        b += dur


F, G = 53, 55
set_chords(7, F)
set_chords(55, G, first='V')
for b, pcs in [(0, [5, 9, 0]), (1, [5, 9, 0]), (2, [10, 2, 5]), (3, [10, 2, 5]), (4, [5, 9, 0]), (5, [5, 9, 0]), (6, [0, 4, 7]),
               (52, [2, 6, 9, 0]), (53, [2, 6, 9, 0]), (54, [2, 6, 9, 0])]:
    beat_chord[b] = pcs

print('rendering chorus...', flush=True)
verse1(7, F)
verse2(55, G)
# tag: soft "oo" plagal cadence, IV -> I, fading to nothing
for sec, m1, m2 in (('BS', 48, 43), ('BR', 52, 50), ('T2', 55, 55), ('T1', 60, 59)):
    sing(sec, m1, T(100), T(104), 'u', dyn_b(100))
    sing(sec, m2, T(104), T(111.3), 'u', 1.0, final=True, rel=0.9)

print('rendering piano...', flush=True)
PAT = [0, 1, 2, 3, 2, 1, 2, 1]
prevc = None
for b in range(0, 100):
    pcs = beat_chord.get(b, prevc)
    v = 0.30 + 0.25 * dyn_b(b) if b >= 7 else 0.55
    low = [m for m in range(34, 46) if m % 12 == pcs[0]][0]
    if b % 4 == 0 or pcs != prevc:
        piano(low, T(b), v * 1.1, 4.0)
        piano(low + 12, T(b), v * 0.6, 3.0)
    else:
        piano(low + (7 if b % 2 else 12), T(b), v * 0.55)
    rh = [m for m in range(57, 77) if m % 12 in pcs]
    for j in (0, 1):
        idx = PAT[(b % 4) * 2 + j] % len(rh)
        piano(rh[idx], T(b + j * 0.5), v * (0.75 if j else 0.9), 2.5)
    prevc = pcs
for b, notes in ((100, [36, 43, 52, 55, 60, 64]), (104, [31, 43, 50, 55, 59, 62, 67]), (108, [67, 74, 79])):
    for j, m in enumerate(notes):
        piano(m, T(b) + j * (0.07 if b < 108 else 0.5), 0.33 - 0.01 * j if b < 108 else 0.2, 6.0)

# -------------------------------------------------------------- applause --
print('applause + hall...', flush=True)
app = np.zeros((N, 2))
a0 = T(111.3) + 2.3
alen = 9.5
nclap = 5200
ct = a0 + alen * rng.beta(1.25, 2.4, nclap)
imp = np.zeros((N, 2))
for c in range(2):
    idx = (ct * sr).astype(int) + rng.integers(0, 300, nclap)
    idx = idx[idx < N]
    np.add.at(imp[:, c], idx, rng.uniform(.2, 1, len(idx)))
for c in range(2):
    kn = int(0.02 * sr)
    ker = rng.normal(0, 1, kn) * np.exp(-np.arange(kn) / (0.0035 * sr))
    ker = sosfilt(butter(2, [900, 3800], 'bandpass', fs=sr, output='sos'), ker)
    app[:, c] = fftconvolve(imp[:, c], ker)[:N]
app /= np.abs(app).max()

# ------------------------------------------------------------------ hall --
def make_ir(seed):
    r = np.random.default_rng(seed)
    n = int(3.2 * sr)
    t = np.arange(n) / sr
    x = r.normal(0, 1, n)
    lo = sosfilt(butter(2, 1200, 'low', fs=sr, output='sos'), x)
    hi = sosfilt(butter(2, [1200, 9000], 'bandpass', fs=sr, output='sos'), x)
    ir = lo * np.exp(-6.91 * t / 2.7) + 0.8 * hi * np.exp(-6.91 * t / 1.6)
    ir *= np.clip(t / 0.06, 0, 1) ** 1.5
    for tt, g in zip(r.uniform(.008, .08, 7), np.linspace(.9, .3, 7)):
        ir[int(tt * sr)] += g * r.choice([-1, 1]) * 12
    pre = np.zeros(int(0.022 * sr))
    ir = np.concatenate([pre, ir])
    return ir / np.sqrt((ir ** 2).sum())


def hall(x):
    return np.stack([fftconvolve(x[:, c], make_ir(100 + c))[:N] for c in range(2)], axis=1)


chorus /= np.sqrt(PER_SECTION * 4)
mix = (0.55 * chorus + 0.65 * hall(chorus)
       + 0.55 * pno + 0.30 * hall(pno))
def win_rms(x):
    m = (x[:len(x) // sr * sr] ** 2).mean(axis=1).reshape(-1, sr).mean(axis=1)
    return np.sqrt(m)
ap = 0.4 * app + 0.6 * hall(app)
mix += ap * (0.8 * np.percentile(win_rms(mix), 97) / win_rms(ap).max())
mix = sosfilt(butter(2, 45, 'high', fs=sr, output='sos'), mix, axis=0)
mix = sosfilt(butter(1, 9500, 'low', fs=sr, output='sos'), mix, axis=0)
end = int((a0 + alen + 1.5) * sr)
mix = mix[:end]
nf = int(2.5 * sr)
mix[-nf:] *= np.linspace(1, 0, nf)[:, None] ** 2
mix *= 0.89 / np.abs(mix).max()
with wave.open(OUT, 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((mix * 32767).astype('<i2').tobytes())
print('wrote', OUT, f'{len(mix) / sr:.1f}s')
