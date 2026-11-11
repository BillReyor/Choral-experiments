"""The voice engine: every singer is a small simulated person.

  larynx  one glottal pulse at a time (LF/Rd voice-source model in its causal-anticausal
          spectral form), each pulse with its own timing jitter, shimmer and tension
  breath  turbulence noise gated by the open phase of every pulse and pushed through the same
          moving vocal tract; "h", the puff after p/t/k and audible inhalations come from it
  tract   moving resonances with true phase, nasal coupling, a slightly different mouth and
          head for every singer
  brain   pitch is hunted, not hit; followers enter late and quietly behind leaders;
          sections drift together

A phrase is a list of notes  (beat, beats, midi, syllable, dynamic)  where syllable is a string
of phonemes such as "s IH ng" (lower case = consonant, upper case = vowel), or "-" to carry the
previous vowel onto a new pitch.  midi may be a tuple for a divisi within the section.
"""
import os
import numpy as np
from scipy.signal import butter, sosfilt, lfilter, bilinear
from scipy.ndimage import gaussian_filter1d as gf
from numpy.lib.stride_tricks import sliding_window_view

SR = 44100
HOP = 100
CR = SR / HOP       # control rate for articulation / pitch tracks (441 Hz)
PN = 2048           # length of one glottal pulse's response
NN = 1024           # length of one breath-noise frame's response
NH = 128            # breath-noise hop
FP = np.fft.rfftfreq(PN, 1 / SR)
FN = np.fft.rfftfreq(NN, 1 / SR)
HANN = .5 - .5 * np.cos(2 * np.pi * np.arange(2 * NH) / (2 * NH))

# Diction settings, tuned by rendering and running a speech recognizer over the result
TIGHT = float(os.environ.get('CHORAL_TIGHT', .5))   # ensemble timing spread (1 = loose community choir, .5 = well drilled)
CDUR = float(os.environ.get('CHORAL_CDUR', 0.9))   # consonant length (a real singer keeps ~84% of each note on the vowel)
SEED = int(os.environ.get('SEED', 0))   # a different set of singers for every seed

# Tone settings.  tools/calibrate.py fits these to a recording of a real singer.
FIT = dict(b1=1.0,      # width of the first resonance (wider = less boxy, but blurs vowels)
           oq=1.3,      # how long the vocal folds stay open each cycle (higher = stronger fundamental)
           rd=0.0,      # overall tension of the voice (lower = brighter, more pressed)
           f4=3000., f5=3500., ring=2.6,   # the 'singer's formant' cluster and how sharply it rings
           breath=0.1,  # amount of air in the tone
           jit=0.5,     # cycle-to-cycle irregularity of the vocal folds
           alive=1.8,   # how much the mouth and larynx keep moving while a note is held
           vib=0.6,     # vibrato depth (choral blend: nearly straight)
           # overall colour of the voice + microphone as (Hz, dB) points, applied without touching the
           # vowel resonances themselves: fuller bottom, less boxy middle, more ring
           eq=((155, 3.9), (424, -5.7), (775, -5.0), (1414, 0.9), (2449, -1.1), (3464, 5.0), (4899, 3.1), (7746, 1.3)))
# Finer constants of the model, also fitted (tools/fit.py) rather than guessed.
TUNE = dict(b2=100., b3=130.,          # widths of the second and third resonances (Hz)
            rd_effort=1.25,            # how much the voice relaxes as it gets quieter
            rd_edge=1.1,               # how breathy the very start and end of a sound are
            amp_exp=.9,                # loudness range between soft and loud
            lift=.2,                   # dB louder per semitone higher
            glide_g=.25, glide_h=.10,  # share of a sliding vowel spent moving / on its second half
            attack=1., release=1.,     # speed of note starts from silence and of releases
            voicebar=.2,               # hum during b, d, g while the mouth is shut
            burst=.17, fric=.12, asp_h=.2)   # p/t/k clicks, s/sh/f hiss, h and after-click air
for _kv in filter(None, os.environ.get('CHORAL_FIT', '').split(',')):   # e.g. CHORAL_FIT=b1=1.8,vib=.6
    FIT[_kv.split('=')[0]] = float(_kv.split('=')[1])
if os.environ.get('CHORAL_NOEQ'):
    FIT['eq'] = ()

# The clock maps score beats to seconds.  render.py sets it (in every worker process too).
CLOCK = dict(beats=np.array([0., 1.]), secs=np.array([0., .5]), n=SR)


def set_clock(beats, secs, total_seconds):
    CLOCK.update(beats=np.asarray(beats, float), secs=np.asarray(secs, float), n=int(total_seconds * SR))


def T(b):
    return float(np.interp(b, CLOCK['beats'], CLOCK['secs']))


# =========================================================== phonemes =====
# Vowel targets (first three resonances, Hz).  The second resonance is set where a trained singer
# was measured to place it: further forward than textbook speech values, especially on back vowels.
VOW = {'IY': (280, 2330, 2950), 'IH': (400, 2150, 2600), 'EH': (550, 1900, 2550), 'AE': (660, 1800, 2500),
       'AA': (690, 1250, 2600), 'AH': (610, 1350, 2550), 'AO': (570, 1000, 2550), 'UH': (440, 1180, 2400),
       'UW': (320, 1100, 2400), 'ER': (480, 1480, 1800), 'AX': (500, 1530, 2550)}
DIPH = {'AY': ((700, 1300, 2600), (420, 2050, 2600)), 'AW': ((690, 1450, 2550), (450, 1100, 2400)),
        'EY': ((500, 2000, 2600), (340, 2250, 2800)), 'OW': ((530, 1050, 2500), (360, 950, 2400)),
        'OY': ((570, 1000, 2550), (400, 2050, 2600))}
# av = voicing level, nas = nose open, nz = nasal anti-resonance, damp = how muffled the upper
# resonances are, ah = glottal aspiration, noise = turbulence made at the lips/teeth/tongue
CONS = {
    'm': dict(F=(250, 1000, 2200), d=.080, av=.60, nas=1., nz=1000., damp=2.5, lp=.5),
    'n': dict(F=(250, 1500, 2600), d=.075, av=.60, nas=1., nz=1500., damp=2.5, lp=.5),
    'ng': dict(F=(250, 2100, 2600), d=.080, av=.55, nas=1., nz=2800., damp=2.5, lp=.5),
    'l': dict(F=(360, 1100, 2700), d=.060, av=.75, damp=1.4),
    'r': dict(F=(380, 1350, 1650), d=.085, av=.75, damp=1.2),
    'w': dict(F=(300, 650, 2200), d=.060, av=.65, damp=1.3),
    'y': dict(F=(270, 2200, 3000), d=.055, av=.65, damp=1.2),
    'v': dict(F=(300, 1100, 2300), d=.060, av=.40, damp=2., noise='f', na=.15),
    'z': dict(F=(300, 1600, 2600), d=.070, av=.35, damp=2., noise='s', na=.5),
    'dh': dict(F=(300, 1500, 2550), d=.045, av=.40, damp=2., noise='f', na=.06),
    's': dict(F=(300, 1700, 2600), d=.130, noise='s', na=1.0),
    'sh': dict(F=(300, 1900, 2500), d=.120, noise='sh', na=.9),
    'f': dict(F=(300, 1100, 2300), d=.080, noise='f', na=.45),
    'h': dict(F=None, d=.070, ah=1.),
    'q': dict(F=None, d=.035),                      # glottal stop: a clean break before a vowel
    'th': dict(F=(300, 1500, 2550), d=.075, noise='f', na=.3),
    'zh': dict(F=(300, 1900, 2500), d=.070, av=.35, damp=2., noise='sh', na=.5),
    'ch': dict(affr=1, voiced=0, F=(250, 1900, 2500), cl=.050, bd=.085, na=1.0),
    'jh': dict(affr=1, voiced=1, F=(250, 1900, 2500), cl=.045, bd=.080, na=1.0),
    'b': dict(stop=1, voiced=1, F=(200, 900, 2200), cl=.045, bd=.012, noise='p', na=.3),
    'd': dict(stop=1, voiced=1, F=(200, 1700, 2650), cl=.045, bd=.015, noise='t', na=.35),
    'g': dict(stop=1, voiced=1, F=(200, 2000, 2300), cl=.045, bd=.020, noise='k', na=.35),
    'p': dict(stop=1, voiced=0, F=(200, 900, 2200), cl=.100, bd=.020, noise='p', na=1.3, vot=.050),
    't': dict(stop=1, voiced=0, F=(200, 1700, 2650), cl=.050, bd=.025, noise='t', na=.9, vot=.045),
    'k': dict(stop=1, voiced=0, F=(250, 1900, 2300), cl=.055, bd=.030, noise='k', na=.8, vot=.055),
}
BLANK = dict(av=0., nas=0., nz=1000., damp=1., lp=0., ah=0., noise=None, na=0., burst=False, vot=0., f0d=0.)
F0DIP = dict(m=-10., n=-10., ng=-10., l=-8., r=-8., w=-8., y=-8., v=-35., z=-35., dh=-35., zh=-35.)   # cents
UNVOICED = {'p', 't', 'k', 's', 'sh', 'f', 'th', 'ch', 'h'}


def cons_segs(c, scale, after_s=False, final=False):
    p = CONS[c]
    if p.get('affr'):                                  # ch / j: a closure released into a hiss
        v = p['voiced']
        return [dict(BLANK, d=p['cl'] * scale, F=p['F'], av=TUNE['voicebar'] if v else 0., lp=1.5, damp=3., f0d=-45. * v),
                dict(BLANK, d=p['bd'] * scale, F=p['F'], av=.3 if v else 0., damp=2., noise='sh', na=p['na'], f0d=-30. * v)]
    if p.get('stop'):
        v = p['voiced']
        out = [dict(BLANK, d=p['cl'] * scale, F=p['F'], av=TUNE['voicebar'] if v else 0., lp=1.5, damp=3., f0d=-45. * v),   # closure
               dict(BLANK, d=p['bd'] * scale, F=p['F'], av=.45 if v else 0., lp=.3, damp=1.5,         # release
                    noise=p['noise'], na=p['na'], burst=True, vot=0. if (v or after_s) else p['vot'], f0d=-25. * v)]
        if final:   # end of a phrase: "loud-uh", "out-h"
            out.append(dict(BLANK, d=.045, F=(480, 1450, 2500), av=.35) if v else dict(BLANK, d=.05, F=None, ah=.7))
        return out
    s = dict(BLANK, d=p['d'] * scale, F=p['F'], f0d=F0DIP.get(c, 0.))
    s.update({k: p[k] for k in ('av', 'nas', 'nz', 'damp', 'lp', 'ah', 'noise', 'na') if k in p})
    return [s]


def nshape(typ, f, P):
    if typ == 's':
        return np.exp(-((f - P['scen']) / 2300) ** 2) * (f > 2500)
    if typ == 'sh':
        return np.exp(-((f - 3100) / 1200) ** 2) + .35 * np.exp(-((f - 5600) / 1600) ** 2)
    if typ == 'f':                                     # weak and flat, not a bright hiss (or it turns into "s")
        return (f > 1200) * (f < 9500) * (1.2 - f / 12000)
    if typ == 't':
        return np.exp(-((f - 5200) / 2400) ** 2) * (f > 1800)
    if typ == 'k':
        return np.exp(-((f - 2300) / 900) ** 2)
    if typ == 'p':
        return np.exp(-((f - 1200) / 1500) ** 2)
    raise KeyError(typ)


def apply_fit(P):
    """Install fitted settings, e.g. {"FIT.oq": 1.7, "VOW.AA.0": 600, "CONS.s.na": .75, "EQ.3": -2}."""
    global CDUR
    eq = list(FIT['eq'])
    for k, v in P.items():
        a = k.split('.')
        if a[0] == 'FIT':
            FIT[a[1]] = v
        elif a[0] == 'EQ':
            eq[int(a[1])] = (eq[int(a[1])][0], v)
        elif a[0] == 'TUNE':
            TUNE[a[1]] = v
        elif a[0] == 'VOW':
            t = list(VOW[a[1]]); t[int(a[2])] = v; VOW[a[1]] = tuple(t)
        elif a[0] == 'DIPH':
            d = [list(x) for x in DIPH[a[1]]]; d[int(a[2])][int(a[3])] = v
            DIPH[a[1]] = tuple(tuple(x) for x in d)
        elif a[0] == 'CONS':
            CONS[a[1]][a[2]] = v
        elif k == 'CDUR':
            CDUR = v
    FIT['eq'] = tuple(eq)


_fit_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voice_fit.json')
if os.path.exists(_fit_file) and not os.environ.get('CHORAL_NOFIT'):     # settings found by tools/fit.py
    import json
    apply_fit(json.load(open(_fit_file)))


# ====================================================== larynx and tract ==
def rd_params(rd):
    """Fant's Rd voice-quality number -> open quotient, asymmetry, return-phase ratio."""
    ra = (-1 + 4.8 * rd) / 100
    rk = (22.4 + 11.8 * rd) / 100
    rg = rk * (.5 + 1.2 * rk) / (4 * (.11 * rd - ra * (.5 + 1.2 * rk)))
    return (1 + rk) / (2 * rg), 1 / (1 + rk), ra


def glottal(f, f0, rd):
    """Spectrum of one glottal flow-derivative pulse closing at t=0: an anticausal resonance
    (the opening of the folds, which happens *before* the closure) times a causal low-pass
    (how abruptly they shut).  Low Rd = pressed and bright, high Rd = lax and breathy."""
    oq, am, ra = rd_params(rd)
    oq = np.minimum(oq * FIT['oq'], .96)
    fg = f0 / (2 * oq)
    sg = -f0 / (2 * oq * np.tan(np.pi * am))
    fa = f0 / (2 * np.pi * ra)
    return (1j * f) / ((sg * sg + fg * fg - f * f) - 2j * sg * f) / (1 + 1j * f / fa)


def upper(f, P):
    """This singer's fixed upper resonances (the part of a voice that says who it is)."""
    V = np.where(f < 15000, 1., np.where(f > 19000, 0., .5 + .5 * np.cos(np.pi * (f - 15000) / 4000))).astype(complex)
    for Fi, Bi in zip(P['hi'], P['hibw']):
        k = Bi * Bi / 4 + Fi * Fi
        V *= k / ((k - f * f) + 1j * Bi * f)
    if FIT['eq']:
        hz, db = zip(*FIT['eq'])
        V *= 10 ** (np.interp(np.log(np.maximum(f, 20.)), np.log(hz), db) / 20)
    return V


def tract(f, hi, P, F, damp, nas, nz, lp):
    """Vocal-tract transfer function for a batch of instants (rows) on frequency grid f."""
    f2 = f * f
    V = np.repeat(hi[None, :], len(F), 0)
    for i, b0 in enumerate((70., TUNE['b2'], TUNE['b3'])):
        b = (b0 * P['bws'] / 2 * (damp if i else FIT['b1'] * (1 + .25 * (damp - 1) + .3 * nas)))[:, None]
        k = b * b + F[:, i:i + 1] ** 2
        V *= k / ((k - f2) + 2j * b * f)
    fz = nz[:, None]                                   # side branch through the nose: a zero and a
    fp = fz * (1 + .3 * nas[:, None])                  # nearby pole that cancel when the nose is shut
    bp = 60. * (1 + nas[:, None])
    kz = 3600. + fz * fz
    kp = bp * bp + fp * fp
    V *= ((kz - f2) + 120j * f) / kz * kp / ((kp - f2) + 2j * bp * f)
    V /= (1 + f2 / 280. ** 2) ** lp[:, None]           # lips closed: only a low hum through the walls
    return V


# ============================================================ singers =====
SECT = {'T1': dict(x=-3.3, fs=1.04, rd=.66, comfy=67.), 'T2': dict(x=-1.1, fs=1.02, rd=.72, comfy=65.),
        'BR': dict(x=1.1, fs=.99, rd=.78, comfy=62.), 'BS': dict(x=3.3, fs=.95, rd=.88, comfy=57.)}
PER_SECTION = 12


def make_singer(sect, idx, neutral=False):
    k = list(SECT).index(sect)
    rng = np.random.default_rng(7000 + 100 * k + idx + 100000 * SEED)
    c = SECT[sect]
    row, col = idx // 4, idx % 4
    star = idx in (1, 6)                               # two per section who never quite blend
    conf = float(np.clip(rng.beta(2.2, 2.0) + (.3 if star else 0), 0, 1))   # leader <-> follower
    skill = float(np.clip(rng.beta(3, 2), 0, 1))
    P = dict(
        sect=sect, idx=idx, star=star, conf=conf, skill=skill,
        x=c['x'] + (col - 1.5) * .55 + rng.normal(0, .08), y=3.0 + row * .8 + rng.normal(0, .08),
        fs=c['fs'] * rng.normal(1, .025), fdev=1 + rng.normal(0, [.025, .03, .025]),
        hi=np.array([FIT['f4'], FIT['f5'], 4650, 5600, 6600, 7700, 8800, 9900, 11000.]) * c['fs'] * (1 + rng.normal(0, .05, 9)),
        hibw=np.array([220 / FIT['ring'], 260 / FIT['ring'], 400, 450, 500, 600, 700, 800, 900.]) * rng.uniform(.75, 1.4),
        bws=rng.uniform(.8, 1.35), vseed=int(rng.integers(1 << 30)), vcache={},
        rd0=c['rd'] * rng.uniform(.8, 1.3) - (.15 if star else 0), breath=rng.uniform(.5, 1.6),
        bias=rng.normal(0, 6), flat=rng.uniform(1.5, 5), comfy=c['comfy'] + rng.normal(0, 1.5),
        vr=rng.uniform(4.8, 6.4), vd=rng.uniform(4, 12) if rng.random() < .55 else rng.uniform(12, 30),
        vdel=rng.uniform(.2, .5), wn=2 * np.pi * rng.uniform(9.5, 12.5), zeta=rng.uniform(.42, .6),
        jit=rng.uniform(.0007, .0016), shim=rng.uniform(.008, .02),
        lag=(.035 * (1 - conf) ** 1.5 - .008 + rng.normal(0, .006)) * TIGHT,
        cs=rng.uniform(.85, 1.2) * CDUR, sib=rng.uniform(.6, 1.5), scen=rng.normal(6500, 700), fsig=rng.uniform(4, 7),
        fry=rng.uniform(0, .5) * (1.4 if sect in ('BR', 'BS') else .8),
        gain=rng.lognormal(0, .18) * (1.5 if star else 1))
    if star:                                           # section leaders: on the beat, crisp diction
        P.update(lag=rng.normal(0, .003), cs=1.2 * CDUR, skill=max(skill, .85), sib=max(P['sib'], 1.))
    if neutral:                                        # the section's average voice, for fitting
        P.update(fs=c['fs'], fdev=np.ones(3), bws=1., rd0=c['rd'], breath=1., bias=0., flat=3., comfy=c['comfy'],
                 vd=6., conf=.8, skill=.8, lag=0., cs=CDUR, sib=1., scen=6500., fry=0., gain=1., star=False, neutral=True,
                 hi=np.array([FIT['f4'], FIT['f5'], 4650, 5600, 6600, 7700, 8800, 9900, 11000.]) * c['fs'],
                 hibw=np.array([220 / FIT['ring'], 260 / FIT['ring'], 400, 450, 500, 600, 700, 800, 900.]))
    P['hiP'], P['hiN'] = upper(FP, P), upper(FN, P)
    one = np.ones(1)
    X = glottal(FP, 200., 1.) * tract(FP, P['hiP'], P, np.array([VOW['AA']]) * P['fs'], one, 0 * one, 1000 * one, 0 * one)
    P['r0'] = float(np.sqrt(2 * (np.abs(X) ** 2).sum() / PN * 200 / SR))
    return P, rng


def vowel_F(P, v):
    """Nobody shapes a vowel exactly like their neighbour."""
    if v not in P['vcache']:
        r = np.random.default_rng(P['vseed'] + 7919 * sum(map(ord, v)))
        k = 1 + r.normal(0, [.02, .025, .015]) * (0 if P.get('neutral') else 1)
        P['vcache'][v] = tuple(np.array(x) * k for x in DIPH[v]) if v in DIPH else np.array(VOW[v]) * k
    return P['vcache'][v]


def consensus(sect, t):
    """Pitch drift a whole section shares."""
    k = list(SECT).index(sect)
    return 4 * np.sin(2 * np.pi * t / 23 + 1.7 * k) + 2.5 * np.sin(2 * np.pi * t / 8.3 + 2.9 * k)


def slow(rng, M, sigma):
    return gf(rng.normal(0, 1, M), sigma, mode='nearest') * np.sqrt(2 * np.sqrt(np.pi) * sigma)


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


def render_phrase(ph, P, rng, out, gap=9.0):
    """One singer, one breath.  ph = [(beat, beats, midi, syllable or '-', dynamic)]."""
    n = len(ph)
    sk, cf = P['skill'], P['conf']
    lag = P['lag'] + (rng.normal(0, .010) + (.02 * (1 - cf) if gap > .4 else 0.)) * TIGHT
    ts = np.array([T(x[0]) for x in ph]) + lag + rng.normal(0, .007 * (1.7 - sk) * TIGHT, n)
    ts = np.maximum.accumulate(ts)
    tend = T(ph[-1][0] + ph[-1][1]) + lag + rng.normal(.012 * (1 - cf), .016 * (1.7 - sk)) * TIGHT   # ragged cut-offs
    te = np.append(ts[1:], max(tend, ts[-1] + .09))
    mids = np.array([x[2][P['idx'] % len(x[2])] if isinstance(x[2], tuple) else x[2] for x in ph], float)
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
            for j, c in enumerate(toks[:vi]):
                on[i] += cons_segs(c, P['cs'] * rng.uniform(.9, 1.1), j > 0 and toks[j - 1] == 's')
        if (i == n - 1) or ph[i + 1][3] != '-':
            for j, c in enumerate(cur_coda):
                co[i] += cons_segs(c, P['cs'] * rng.uniform(.9, 1.1), final=(i == n - 1 and j == len(cur_coda) - 1))
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

    segs, noises, vots = [], [], []

    def put(t, seglist, tv=None):
        for s in seglist:
            segs.append(dict(s, t0=t, t1=t + s['d'], F2=None))
            if s['noise']:
                noises.append((s['noise'], t, s['d'], s['na'], s['burst']))
            if s['vot'] and tv is not None:
                vots.append((t, tv, s['vot'] * rng.uniform(.8, 1.3)))
            t += s['d']

    def vseg(a, b, F, F2=None):
        segs.append(dict(BLANK, t0=a, t1=b, F=F, F2=F2, av=1.))

    kicks = []

    for i in range(n):
        if on[i]:
            put(ts[i] - sum(s['d'] for s in on[i]), on[i], ts[i])
            if on[i][-1]['av'] == 0:               # unvoiced consonant: the vowel starts a little sharp
                kicks.append(ts[i])
        vend = te[i] - sum(s['d'] for s in co[i]) - (sum(s['d'] for s in on[i + 1]) if i < n - 1 else 0)
        tgt = vowel_F(P, vow[i])
        if vow[i] in DIPH:
            A, B = tgt
            if lastflag[i]:      # hold the first vowel, glide, then land on the second
                dur = vend - ts[i]
                g = float(np.clip(TUNE['glide_g'] * dur, .06, .10)); h = float(np.clip(TUNE['glide_h'] * dur, .02, .04))
                vseg(ts[i], vend - g - h, A); vseg(vend - g - h, vend - h, A, B); vseg(vend - h, vend, B)
            else:
                vseg(ts[i], vend, A)
        else:
            vseg(ts[i], vend, tgt)
        if co[i]:
            put(vend, co[i])

    # ---- articulation tracks at control rate
    first = min(s['t0'] for s in segs)
    tl = max(s['t1'] for s in segs)
    inhale = gap > .32 and rng.random() < .85
    pre = .04
    if inhale:
        idur = min(.45, gap - .12) * rng.uniform(.55, 1.)
        igap = rng.uniform(.04, .10)
        pre = idur + igap + .04
    tA = first - pre
    M = int((tl + .22 - tA) * CR) + 2
    tc = tA + np.arange(M) / CR

    def ix(t):
        return int(np.clip(round((t - tA) * CR), 0, M - 1))

    Ft = np.full((M, 3), np.nan)
    tr = {k: np.full(M, BLANK[k]) for k in ('av', 'nas', 'nz', 'damp', 'lp', 'ah', 'f0d')}
    for s in segs:
        i0 = ix(s['t0']); i1 = max(ix(s['t1']), i0 + 1)
        if s['F'] is not None:
            if s['F2'] is None:
                Ft[i0:i1] = s['F']
            else:
                w = np.linspace(0, 1, len(Ft[i0:i1]))[:, None]
                Ft[i0:i1] = np.asarray(s['F']) * (1 - w) + np.asarray(s['F2']) * w
        for k in tr:
            tr[k][i0:i1] = s[k]
    for (tb, tv, vot) in vots:                         # p/t/k: a puff of air before the voice catches
        j0, j1, j2 = ix(tb), ix(tv), ix(tv + vot)
        if j2 > j0:
            tr['ah'][j0:j2] = np.maximum(tr['ah'][j0:j2], np.linspace(1, .3, j2 - j0))
        if j2 > j1:
            tr['av'][j1:j2] *= np.linspace(.05, 1, j2 - j1) ** 1.5
    idx = np.where(~np.isnan(Ft[:, 0]))[0]
    Ft = Ft[idx[np.clip(np.searchsorted(idx, np.arange(M)), 0, len(idx) - 1)]]
    Ft = gf(Ft, P['fsig'], axis=0, mode='nearest')
    av = gf(tr['av'], 2.5, mode='nearest')
    nas = gf(tr['nas'], 2.5, mode='nearest')           # closures switch on and off abruptly
    nz = gf(tr['nz'], 2.5, mode='nearest')
    damp = gf(tr['damp'], 2.5, mode='nearest')
    lp = gf(tr['lp'], 2.5, mode='nearest')
    ah = gf(tr['ah'], 3, mode='nearest')
    micro = gf(tr['f0d'], 3, mode='nearest')
    for tk in kicks:
        micro = micro + 28 * np.exp(-np.clip(tc - tk, 0, None) / .035) * (tc >= tk)
    if not on[0]:
        av *= np.clip((tc - (ts[0] - .005)) / (TUNE['attack'] * rng.uniform(.035, .065)), 0, 1)
    if not co[-1]:
        av *= np.clip((tl - tc) / (TUNE['release'] * rng.uniform(.07, .13)), 0, 1)
    for i in range(1, n):                              # vowel straight into vowel: a small glottal nudge
        if head[i] and not on[i] and not co[i - 1]:
            av *= 1 - .55 * np.exp(-((tc - ts[i] + .02) / .018) ** 2)

    # ---- pitch: glide between notes, hunt for the note, drift, vibrato
    ni = np.clip(np.searchsorted(ts - .012, tc, side='right') - 1, 0, n - 1)
    b_, a_ = bilinear([P['wn'] ** 2], [1, 2 * P['zeta'] * P['wn'], P['wn'] ** 2], fs=CR)
    step = mids[ni]
    mid = lfilter(b_, a_, step - step[0]) + step[0]
    leap = np.diff(mids, prepend=mids[0])
    e0 = rng.normal(-1.5 * np.clip(leap, -6, 6), (3 + 2.5 * np.minimum(np.abs(leap), 7)) * (1.5 - sk))
    e0[0] = rng.normal(-42 - 20 * (1 - cf), 18 * (1.5 - sk)) if gap > .3 else rng.normal(-10, 10 * (1.5 - sk))
    vstart = ts.copy()
    for i in range(1, n):
        if not head[i] and mids[i] == mids[i - 1]:
            vstart[i] = vstart[i - 1]; e0[i] = 0
    tau = rng.uniform(.09, .22, n) / (.5 + sk)
    tau[0] = rng.uniform(.045, .085)
    hunt = gf(e0[ni] * np.exp(-np.clip(tc - ts[ni], 0, None) / tau[ni]), 4, mode='nearest')
    dy = gf(dyns[ni], 12, mode='nearest')
    vrate = P['vr'] * (1 + .07 * slow(rng, M, 40))
    vdepth = P['vd'] * FIT['vib'] * np.clip((tc - vstart[ni] - P['vdel']) / .35, 0, 1) * (1 + .25 * slow(rng, M, 50)) * (.6 + .5 * dy)
    vib = gf(vdepth, 8, mode='nearest') * np.sin(2 * np.pi * np.cumsum(vrate) / CR + rng.uniform(0, 6.28))
    cents = (P['bias'] - P['flat'] * np.maximum(0, mid - P['comfy']) + consensus(P['sect'], tc)
             + hunt + vib + micro + 4 * slow(rng, M, 60) + 3.5 * slow(rng, M, 3))
    f0 = 440 * 2 ** ((mid - 69) / 12 + cents / 1200)

    # ---- effort: phrase arc, accents, followers sneaking in, running out of air
    u = np.clip((tc - ts[0]) / max(tl - ts[0], .1), 0, 1)
    eff = dy * (1 - .10 * u * u * (1.3 - sk)) * (1 + .12 * np.exp(-np.clip(tc - ts[ni], 0, None) / .10))
    eff *= 1 - .1 * (1 - cf) * np.exp(-np.clip(tc - ts[0], 0, None) / .06)
    eff = np.clip(eff, .05, 1.15)
    lift = 10 ** (np.clip(TUNE['lift'] * (mid - (P['comfy'] - 7)), -3, 3) / 20)        # singers get louder as they go up
    amp = av * eff ** TUNE['amp_exp'] * lift * (1 + .04 * slow(rng, M, 25))
    rd = np.clip(P['rd0'] + FIT['rd'] + FIT['alive'] * .07 * slow(rng, M, 45) + TUNE['rd_effort'] * (1 - eff)
                 + TUNE['rd_edge'] * (1 - np.clip(av / .3, 0, 1)), .45, 2.6)

    F = Ft * (P['fs'] * P['fdev']) * (1 + .002 * (mid - 60))[:, None]       # larynx rises with pitch
    for j, sd in enumerate((.022, .018, .012)):                              # nobody holds their mouth perfectly still
        F[:, j] *= 1 + FIT['alive'] * sd * slow(rng, M, rng.uniform(25, 50))
    F[:, 0] *= 1 + .10 * (eff - .7) * av                                     # jaw drops with effort
    F[:, 0] = np.maximum(F[:, 0], .95 * f0)

    inh = np.zeros(M)
    if inhale:
        uu = np.clip((tc - (first - igap - idur)) / idur, 0, 1)
        inh = np.sin(np.pi * uu ** 1.7) ** 1.2 * (uu < 1) * .025 * P['breath'] * dyns[0] * rng.uniform(.5, 1.3)
        damp = np.where(tc < first - igap, 2.2, damp)
    asp = amp * P['breath'] * FIT['breath'] * (.03 + .06 * np.clip((rd - .6) / 1.5, 0, 1)) + ah * TUNE['asp_h'] * eff * P['breath'] ** .5 + inh

    L = (M - 1) * HOP + PN + NN
    sig = np.zeros(L)

    def at(x, t):
        return np.interp(t, tc, x)

    # ---- voiced part: one glottal pulse at a time
    phi = 2 * np.pi * np.concatenate([[0], np.cumsum((f0[1:] + f0[:-1]) / 2)]) / CR
    tg = np.interp(2 * np.pi * np.arange(1, int(phi[-1] / (2 * np.pi)) + 1), phi, tc)
    ag = at(amp, tg)
    tg, ag = tg[ag > 2e-4], ag[ag > 2e-4]
    if len(tg):
        f0g = at(f0, tg)
        tg = tg + rng.normal(0, P['jit'] * FIT['jit'] * .7, len(tg)) / f0g
        ag = ag * (1 + rng.normal(0, P['shim'], len(tg)))
        rdg = at(rd, tg)
        if not on[0] and len(tg) > 8 and dyns[0] > .6 and rng.random() < P['fry']:           # creaky attack
            w = np.where(tg < tg[0] + rng.uniform(.06, .12))[0]
            odd = w[1::2]
            ag[odd] *= rng.uniform(.15, .4)
            tg[odd] += .13 / f0g[odd]
            rdg[w] = np.maximum(.45, rdg[w] - .3)
        pos = (tg - tA) * SR
        ip = np.floor(pos).astype(int)
        for a in range(0, len(tg), 512):
            sl = slice(a, a + 512)
            t_ = tg[sl]
            Fg = np.stack([at(F[:, j], t_) for j in range(3)], 1)
            X = glottal(FP, f0g[sl][:, None], rdg[sl][:, None]) * tract(
                FP, P['hiP'], P, Fg, at(damp, t_), at(nas, t_), at(nz, t_), at(lp, t_))
            pred = np.sqrt(2 * (np.abs(X) ** 2).sum(1) / PN * f0g[sl] / SR) + 1e-30
            X *= (ag[sl] / (pred ** .95 * P['r0'] ** .05))[:, None]
            X *= np.exp(-2j * np.pi * FP[None, :] * ((pos[sl] - ip[sl] + PN // 4) / SR)[:, None])
            x = np.fft.irfft(X, PN, axis=1)
            for j, i0 in enumerate(ip[sl] - PN // 4):
                if i0 >= 0:
                    sig[i0:i0 + PN] += x[j]

    # ---- breath: noise that opens and shuts with the folds, through the same tract
    if asp.max() > 1e-5:
        na_ = (M - 1) * HOP
        ta = tA + np.arange(na_) / SR
        d = .75 * np.clip(at(av, ta) * 3, 0, 1)
        src = rng.standard_normal(na_) * ((1 - d / 2) + (d / 2) * np.cos(at(phi, ta) - 1.4 * np.pi))
        src /= np.sqrt((1 - d / 2) ** 2 + d * d / 8)
        frames = sliding_window_view(src, 2 * NH)[::NH]
        tf = tA + (np.arange(len(frames)) * NH + NH) / SR
        af = at(asp, tf)
        for a in range(0, len(frames), 1024):
            sl = slice(a, a + 1024)
            if af[sl].max() < 1e-5:
                continue
            t_ = tf[sl]
            Fg = np.stack([at(F[:, j], t_) for j in range(3)], 1)
            H = tract(FN, P['hiN'], P, Fg, at(damp, t_), at(nas, t_), at(nz, t_), at(lp, t_)) * (1j * FN / 1500)
            H *= (af[sl] / np.sqrt((np.abs(H) ** 2).mean(1) + 1e-30))[:, None]
            y = np.fft.irfft(np.fft.rfft(frames[sl] * HANN, NN, axis=1) * H, NN, axis=1)
            for j in range(len(y)):
                sig[(a + j) * NH:(a + j) * NH + NN] += y[j]

    # ---- turbulence at the teeth / lips / tongue: s, sh, f and the releases of p t k b d g
    for (typ, t0, d, na, burst) in noises:
        m = int((d + (.03 if burst else .02)) * SR)
        x = rng.standard_normal(m)
        x = np.fft.irfft(np.fft.rfft(x) * nshape(typ, np.fft.rfftfreq(m, 1 / SR), P), m)
        x /= x.std() + 1e-9
        tt = np.arange(m) / SR
        if burst:
            e = np.exp(-tt / (d * .6)) * np.minimum(1, tt / .001) * TUNE['burst']
        else:
            e = np.minimum(1, tt / .02) * np.minimum(1, (m / SR - tt) / .025) * TUNE['fric'] * P['sib']
        i0 = int((t0 - tA) * SR)
        if i0 >= 0 and i0 + m <= L:
            sig[i0:i0 + m] += x * e * na * float(at(eff, t0)) ** TUNE['amp_exp']

    i0 = int(round(tA * SR))
    if i0 >= 0 and i0 + L <= len(out):
        out[i0:i0 + L] += (sig * P['gain']).astype(np.float32)


def render_singer(args):
    """Worker: one singer's whole part.  args = (section, index, notes, clock)."""
    sect, idx, notes, clock = args
    set_clock(*clock)
    P, rng = make_singer(sect, idx)
    out = np.zeros(CLOCK['n'], np.float32)
    prev_end = None
    for ph in split_phrases(notes):
        gap = 9. if prev_end is None else T(ph[0][0]) - T(prev_end)
        render_phrase(ph, P, rng, out, gap=gap)
        prev_end = ph[-1][0] + ph[-1][1]
    return sect, P['x'], P['y'], P['star'], out
