"""Give the simulated singers the sound of a real voice.

The engine decides everything about the singing - which notes, when, how each one begins, swells and ends, every
consonant - but its sound is that of a model of a larynx and a mouth, and it is heard as one.  A voice-conversion
model can take such a track and return it in the voice of a short recording of a real singer, with pitch, words and
timing kept.  This module hands every singer's part to such a model and puts what comes back in its place: lined
up with the original to the millisecond, and as loud as the original at every moment.

The model is an outside program (docs/how-it-works.md says how to set one up).  All this module asks of it is a
command that takes a list of jobs - {"source": wav, "reference": wav, "out": wav} - and writes each "out".  The
command is the JSON list in .svc/command.json beside the program, or in the file CHORAL_REVOICE names.

Whose voice: a recording of 15-30 seconds of one person singing alone.  Use your own, or that of someone who has
agreed to it."""
import json, os, shutil, subprocess, tempfile, wave
import numpy as np
from scipy.ndimage import gaussian_filter1d as gf

SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def command():
    """The converter's command line, or None if none is set up."""
    f = os.environ.get('CHORAL_REVOICE') or os.path.join(ROOT, '.svc', 'command.json')
    if not os.path.exists(f):
        return None
    cmd = json.load(open(f))
    return cmd if all(os.path.exists(c) for c in cmd[:2]) else None


HOP = 64


def _env(x, seconds):
    """Loudness of a track, smoothed over `seconds`, at one value every HOP samples (cheap on minutes of sound)."""
    n = len(x) // HOP
    p = (np.asarray(x[:n * HOP], np.float64) ** 2).reshape(n, HOP).mean(1) if n else np.zeros(1)
    return np.sqrt(gf(p, max(seconds * SR / HOP, .5), mode='constant') + 1e-14)


LONGEST, HARD = 14., 15.   # seconds of singing handed over in one piece: aimed at, and never more than
VOICE_SECONDS = 13.        # how much of a recording of a voice the model is given


def stretches(x, sr=SR, floor=-48., gap=1.5, pad=.3):
    """Where a singer sings -> [(first sample, last sample, keep from, keep to)]: what is handed over, and the part
    of it that is kept.  Silences shorter than `gap` seconds stay inside a stretch, and each stretch takes a little
    of the silence around it.

    A model works on a window of sound at a time (half a minute less the recording of the voice, for the one used
    here) and, given more, makes it in windows and crosses them over where they meet - mid-phrase, two different
    renderings at once, the level 7-8 dB down for a tenth of a second.  So a long stretch is cut into pieces of
    LONGEST seconds or less, each at the last quiet moment (a rest, a breath, the silence of a t or a k) that the
    limit allows - a little later if there is none, and only if HARD seconds pass without one, at the least loud
    moment there is.  Each piece is handed over with `pad` seconds of its neighbour as context and only the piece
    itself is kept."""
    env = _env(x, .02)
    if env.max() < 1e-6:
        return []
    top = 2. ** round(float(np.log2(env.max())))          # the loudest moment, to the nearest 6 dB.  Not as it is: one
    on = env > top * 10 ** (floor / 20)                   # corrected word in the loudest phrase would then move every
    if not on.any():                                      # edge and every cut in the part by milliseconds, and the
        return []                                         # whole part would be handed to the model as new (see _kept)
    edges = np.flatnonzero(np.diff(np.r_[0, on.astype(np.int8), 0])) * HOP
    spans = [[a, b] for a, b in zip(edges[::2], edges[1::2])]
    out = [spans[0]]
    for a, b in spans[1:]:
        if a - out[-1][1] < gap * sr:
            out[-1][1] = b
        else:
            out.append([a, b])
    p = int(pad * sr); pieces = []
    quiet = _env(x, .03) < top * 10 ** (-35 / 20)                # per HOP samples

    def cut(a, b):
        got = []
        while b - a > LONGEST * sr:
            lo, mid, hi = (a + int(2 * sr)) // HOP, (a + int(LONGEST * sr)) // HOP, min(b - sr, a + int(HARD * sr)) // HOP
            q = np.flatnonzero(quiet[lo:hi]) + lo
            if len(q):
                last = q[q <= mid][-1] if (q <= mid).any() else q[0]          # the last quiet moment in time, else the first after
                run = q[(q >= last - int(.5 * sr / HOP)) & (q <= last + int(.5 * sr / HOP))]
                run = run[np.abs(run - last) == np.abs(np.arange(len(run)) - np.searchsorted(run, last))]      # the unbroken run around it
                c = int(run[len(run) // 2]) * HOP                              # its middle
            else:
                e = _env(x[a + int(.5 * LONGEST * sr):hi * HOP], .03)
                c = a + int(.5 * LONGEST * sr) + int(np.argmin(e)) * HOP
            got.append((a, c)); a = c
        return got + [(a, b)]

    for a, b in out:
        a, b = max(0, a - p), min(len(x), b + p)
        for ka, kb in cut(a, b):
            pieces.append((max(a, ka - p), min(b, kb + p), ka, kb))
    return pieces


def _write(path, x, sr=SR):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())


def _read(path):
    """A recording -> mono at 44100 Hz.  A 16-, 24- or 32-bit WAV is read directly; anything else (a phone's .m4a,
    an .mp3, a floating-point WAV) through ffmpeg, or afconvert on a Mac."""
    try:
        with wave.open(path) as w:
            sr, nc, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False).name
        try:
            if shutil.which('ffmpeg'):
                cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', path, '-ar', str(SR), '-ac', '1', '-c:a', 'pcm_s16le', tmp]
            elif shutil.which('afconvert'):
                cmd = ['afconvert', '-f', 'WAVE', '-d', f'LEI16@{SR}', '-c', '1', path, tmp]
            else:
                raise SystemExit(f'cannot read {path}: install ffmpeg, or convert the recording to WAV first')
            if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                raise SystemExit(f'cannot read {path}: it is not a sound file ffmpeg or afconvert knows')
            return _read(tmp)
        finally:
            os.path.exists(tmp) and os.unlink(tmp)
    if _floats(path):
        x = np.frombuffer(raw, '<f4' if sw == 4 else '<f8').astype(np.float64)
    elif sw == 3:                                         # 24 bits: three bytes a sample
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        x = (b[:, 0] | b[:, 1] << 8 | (b[:, 2] ^ 0x80) - 0x80 << 16) / 2. ** 23
    else:
        x = (np.frombuffer(raw, {1: 'u1', 2: '<i2', 4: '<i4'}[sw]).astype(np.float64) - (128 if sw == 1 else 0)) / 2. ** (8 * sw - 1)
    x = x.reshape(-1, nc).mean(1)
    if sr != SR:
        from scipy.signal import resample_poly
        x = resample_poly(x, SR, sr)
    return x


def _floats(path):
    """Does this WAV hold floating-point samples?  (Python's reader opens some such files without saying.)"""
    import struct
    head = open(path, 'rb').read(4096)
    k = head.find(b'fmt ')
    if k < 0 or len(head) < k + 10:
        return False
    tag = struct.unpack('<H', head[k + 8:k + 10])[0]
    return tag == 3 or (tag == 0xFFFE and head[k + 32:k + 34] == b'\x03\x00')


def _plain(path):
    """Is this a 16-bit WAV, which any model's loader reads as it is?"""
    try:
        with wave.open(path) as w:
            return w.getsampwidth() == 2
    except (wave.Error, EOFError):
        return False


_PITCH = {}


def pitch_of(path):
    """How high a recording lies (MIDI number): the middle of everything sung in its first half minute."""
    if path not in _PITCH:
        from scipy.signal import resample_poly
        from . import pitch
        t, m = pitch.yin(resample_poly(_read(path)[:SR * 30], 1, 2), SR // 2, fmin=60., fmax=700.)
        m = m[~np.isnan(m)]
        _PITCH[path] = float(np.median(m)) if len(m) else 60.
    return _PITCH[path]


def asked(path, parts, names=None):
    """The part a recording's file name asks for, or None: 'bass 2.wav', 'Tenor 1 - Sam.wav', 'BR_x.wav' ..."""
    import re
    f = re.sub(r'[\s_]+', ' ', os.path.splitext(os.path.basename(path))[0].lower()).strip()
    for p in sorted(parts, key=lambda p: -len((names or {}).get(p, p))):          # 'tenor 1' before a shorter name
        for word in {p.lower(), (names or {}).get(p, p).lower()}:
            more = r'(?!\d)' if word[-1].isdigit() else r'(?![a-z])'               # 'bass2' and 'tenor1b' yes; 'bassoon' and 'tenor 12' no
            if re.match(re.escape(word) + more, f) or re.match(re.escape(word.replace(' ', '')) + more, f):
                return p
    return None


def _by_pitch(order, size, written):
    """Voices (lowest first) shared among parts, lowest first: {part: [voices]}."""
    sections = sorted((p for p in size if size[p] > 1), key=written.get) or sorted(size, key=written.get)
    own = {}
    for p in size:                                    # one person: whoever's own singing lies nearest these notes
        if p not in sections:
            best = min(order, key=lambda f: abs(pitch_of(f) - written[p]))
            own[p] = [best]
            if len(order) > 2 * len(sections):
                order.remove(best)
    n, k = len(order), len(sections)
    for r, p in enumerate(sections):
        own[p] = order[r * n // k:(r + 1) * n // k] if n >= k else [order[int(round(r * (n - 1) / max(k - 1, 1)))]]
    return own


SPREAD, LEAN = .6, .5            # semitones: how far copies of one voice differ in size within a section, and between sections


def deal(voices, seats, written, log=print, names=None):
    """Which voice each singer is given.  seats: (part, singer number) for every singer; written: {part: the middle
    of its written pitches}.  -> (recording, size) per seat.

    A recording whose file name begins with a part's name ('bass 2.wav', 'Tenor 1 - Sam.wav') sings in that part.
    The others are seated as a choir seats its people, by how low they sing: put in order from the lowest to the
    highest (by the pitch of what is sung in each recording), the parts that nobody was named for, lowest first,
    take them in turn - each its own share when there are at least as many voices as parts, otherwise neighbours
    share.  A part sung by one person takes the voice whose own singing lies nearest its notes, and keeps it to
    itself when that still leaves every section two voices.  Within a section the voices go round, so that
    neighbours differ.  A part left with nobody borrows the voices of the part nearest its notes.

    Size.  One recording given to six singers is one man six times over: a speaker-recognition network scores the
    six as the same voice (0.98-0.99).  So each further singer with the same recording gets it a little larger or
    smaller - the recording played up to 3.5% slower or faster, which moves every resonance as a larger or smaller
    throat and mouth would (size, in semitones; the pitch sung still comes from the engine).  And a voice that has to
    serve several sections is larger in the lower ones.  A part sung by one person keeps the voice as it is."""
    size = {}
    for part, _ in seats:
        size[part] = size.get(part, 0) + 1
    own, free = {}, []
    for f in dict.fromkeys(voices):
        p = asked(f, size, names)
        own.setdefault(p, []).append(f) if p else free.append(f)
    left = {p: size[p] for p in size if p not in own}
    if free and left:
        own.update(_by_pitch(sorted(free, key=pitch_of), left, written) if len(free) > 1 else {p: list(free) for p in left})
    for p in size:
        if p not in own:
            own[p] = own[min(own, key=lambda q: abs(written[q] - written[p]))]
    short = lambda f: os.path.splitext(os.path.basename(f))[0]
    for p in sorted(own, key=written.get, reverse=True):
        log('  %-9s %s' % ((names or {}).get(p, p), ', '.join(short(f) for f in own[p])))
    lean = {}                                         # (part, recording) -> size: larger in the lower of the sections it serves
    for f in dict.fromkeys(voices):
        serves = sorted((p for p in own if f in own[p] and size[p] > 1), key=written.get)
        for r, p in enumerate(serves):
            lean[p, f] = LEAN * (2 * r / (len(serves) - 1) - 1) if len(serves) > 1 else 0.
    given, copies = [], {}
    for p, i in seats:
        f = own[p][i % len(own[p])]
        if size[p] == 1:
            given.append((f, 0.)); continue
        n = len([j for j in range(size[p]) if own[p][j % len(own[p])] == f])       # how many in this section share the recording
        k = copies[p, f] = copies.get((p, f), -1) + 1
        half = min(SPREAD, .2 * (n - 1))
        given.append((f, round(lean[p, f] + (half * (2 * k / (n - 1) - 1) if n > 1 else 0.), 2)))
    return given


def _repitch(y, src, log=None):
    """A re-voiced stretch (already lined up with its original), put back on the original's pitch.

    The model is told the pitch only roughly - in steps of 15 cents for a first tenor's top notes, 27 around the G
    below middle C, 43 at a bass's low A - and sings somewhere inside the step it was given: a held note sits a few
    cents off, wanders, and when the engine's pitch lies near the edge of a step it flickers between two.  The
    engine's pitch is known exactly.  So the two are tracked, and wherever both are sung the re-voiced one is played
    that many cents slower or faster (at most a semitone).  Playing faster also arrives sooner - a few milliseconds
    a second.  That is set right wherever nothing is sung: in rests, and in the consonants without voice that come
    every few syllables.  (Setting it right inside a note, by dropping or repeating one period of the voice, was
    tried first: each such place is a moment without a clear period - a catch in the voice, most of a second apart.
    It is done now only if LOOSE seconds have built up with no such place in reach.)"""
    from scipy.signal import resample_poly
    from scipy.ndimage import map_coordinates
    from . import pitch
    n = len(src)
    if n < SR // 2:
        return y
    hop = 64
    ms = pitch.yin(resample_poly(src, 1, 2), SR // 2, fmin=60., fmax=700., hop=hop)[1]
    my = pitch.yin(resample_poly(y, 1, 2), SR // 2, fmin=60., fmax=700., hop=hop)[1]
    k = min(len(ms), len(my))
    if k < 8:
        return y
    d = 100. * (my[:k] - ms[:k])                                  # cents the re-voiced one is sharp, per 5.8 ms
    ok = ~np.isnan(d) & (np.abs(d) < 100)                         # further off than that is a tracker's slip, not the singer
    if ok.sum() < 8:
        return y
    at = np.flatnonzero(ok)
    near = np.abs(np.arange(k)[:, None] - at[np.searchsorted(at, np.arange(k)).clip(0, len(at) - 1)][:, None]).ravel()
    near = np.minimum(near, np.abs(np.arange(k) - at[(np.searchsorted(at, np.arange(k)) - 1).clip(0, len(at) - 1)]))
    filled = np.where(near <= 12, np.interp(np.arange(k), at, d[at]), 0.)        # carried across gaps of up to 70 ms
    filled = gf(filled, PITCH_SMOOTH)
    t = (np.arange(k) * hop + 512) * 2.                           # where each value sits, in samples at 44100
    rate = 2. ** (-np.interp(np.arange(n), t, filled) / 1200.)
    ahead = np.cumsum(rate - 1.)                                  # how far the reading has run ahead, in samples
    period = SR / (440. * 2. ** ((np.where(np.isnan(my[:k]), 60., my[:k]) - 69.) / 12.))
    step = np.zeros(n); jumps = []; off = 0.
    rest = np.convolve(np.isnan(ms[:k]).astype(float), np.ones(9), 'same') >= 9      # the original has no voice here, nor 12 ms either side
    for i in range(k):
        j = int(min(t[i], n - 1)); a = ahead[j] + off
        if rest[i] and abs(a) > 20:                               # nothing sung here (a rest, an s, the silence of a t): set it right
            off -= a; jumps.append((j, -a))
        elif ok[i] and abs(a) > LOOSE * SR:                       # sung on and on, and now this far out: drop or repeat whole periods
            by = -np.round(a / period[i]) * period[i]; off += by; jumps.append((j, by))
    for j, by in jumps:
        step[j] += by
    at_ = np.arange(n) + ahead + np.cumsum(step)
    out = map_coordinates(y, [np.clip(at_, 0, len(y) - 1)], order=3, mode='nearest')
    for j, by in jumps:                                           # each jump is crossed over in a few milliseconds
        m = min(220, n - j)
        if m > 8:
            w = np.linspace(0., 1., m)
            before = map_coordinates(y, [np.clip(at_[j:j + m] - by, 0, len(y) - 1)], order=3, mode='nearest')
            out[j:j + m] = (1 - w) * before + w * out[j:j + m]
    if log:
        log(filled, jumps)
    return out


LIFT = 10.             # dB: the most a moment of a re-voiced stretch is raised to reach its original's loudness


def _cycles(xl, a, b, f):
    """The cycles of a voice from sample a to b, found as voice-analysis programs find them: each one's waveform
    (xl: the sound below 1.2 kHz) is matched with the next.  f: roughly the pitch it has, Hz, per sample.
    -> where each cycle starts (to a fraction of a sample), and how well each matched the one before."""
    p = float(a); out = [p]; fit = [1.]
    T = SR / f[int(p)]
    while p + 2.3 * T < b:
        T0 = .5 * T + .5 * SR / f[int(p)]                 # follow the pitch it has, pulled towards the pitch it is said to have
        L = int(.12 * T0) + 2; n = int(T0); i = int(p)
        ref = xl[i:i + n]; lo = i + n - L; seg = xl[lo:lo + n + 2 * L]
        if len(seg) < n + 2 * L or len(ref) < n:
            break
        r = np.correlate(seg, ref, 'valid') / np.sqrt(np.convolve(seg ** 2, np.ones(n), 'valid') * (ref @ ref) + 1e-20)
        k = int(np.argmax(r)); d = 0.
        if 0 < k < len(r) - 1:                            # the top of the curve, between samples
            den = r[k - 1] - 2 * r[k] + r[k + 1]
            d = .5 * (r[k - 1] - r[k + 1]) / den if abs(den) > 1e-12 else 0.
        T = (lo + k + d) - i
        p += T; out.append(p); fit.append(float(r[k]))
    return np.array(out), np.array(fit)


def _pitch_of(src):
    """The engine's pitch, read from its own sound cycle by cycle -> (Hz at every sample, where it is voiced).
    A pitch tracker's reading wobbles by more than the singer does (17 cents, 3-20 times a second, on notes the engine
    holds within 7): rebuilt on such a reading, a held note flutters.  The lengths of the cycles themselves do not."""
    from scipy.signal import resample_poly, butter, sosfiltfilt
    from . import pitch
    n = len(src)
    tt, m = pitch.yin(resample_poly(src, 1, 2), SR // 2, fmin=60., fmax=700., hop=64)
    v = ~np.isnan(m)
    if v.sum() < 16:
        return None, None
    at = tt * SR
    rough = 440. * 2. ** ((np.interp(np.arange(n), at[v], m[v]) - 69.) / 12.)
    voiced = np.interp(np.arange(n), at, v.astype(float)) > .5
    f = rough.copy()
    xl = sosfiltfilt(butter(4, 1200., 'lp', fs=SR, output='sos'), src)
    e = np.flatnonzero(np.diff(np.r_[0, v.astype(np.int8), 0]))
    for i0, i1 in zip(e[::2], e[1::2]):
        a, b = int(at[i0]), int(at[i1 - 1])
        if b - a < .05 * SR:
            continue
        mk, fit = _cycles(xl, a, b, rough)
        if len(mk) < 6:
            continue
        T = np.diff(mk); ok = (fit[1:] > .8) & (np.abs(T * rough[np.minimum(mk[:-1].astype(int), n - 1)] / SR - 1) < .12)
        if ok.sum() < 4:
            continue
        mid = .5 * (mk[:-1] + mk[1:])[ok]
        f[a:b] = np.interp(np.arange(a, b), mid, gf(SR / T[ok], 1.5))          # over three cycles
    return f, voiced


CALM = .01             # seconds over which a rebuilt voice's colour and loudness are steadied everywhere
STILL = .08            # ... over which its pitch is steadied inside a held note (0: the engine's own, flutter and all)
LEVEL_HELD = .3        # ... and its loudness
HELD_CHANGE = 1.5      # dB in 20 ms: an engine colour changing faster than this is a syllable changing, not a held vowel
STOPS = True           # put the stops right in a rebuilt voice (see _stops)
CONS = 10.             # dB: the most a consonant of a rebuilt soloist is raised to the engine's strength: a listener chose 10 over 5 and
                       # none (59, 56, 53 of his 70 words to a recognizer).  Neither this nor _stops is done for section singers: the
                       # chorus was chosen without them, and a section's words read worse with them (50% against 57, 67 against 73)
CALM_HELD = .12        # ... over which its colour is steadied inside a held note


def _rebuild(y, src, alone=False):
    """A re-voiced stretch (lined up with its original) with its sung tone built again: the model's vowel colour,
    sounded at the engine's pitch.  Needs the WORLD analysis/synthesis (pip install pyworld); returns None without
    it.  Made for a voice heard alone; a listener then preferred the whole chorus this way too, though a section
    of twelve is understood less well for it (baritones 77% of their words -> 57%, first tenors 87% -> 73%).

    Heard alone, the model's held notes are rough - "a slight spasmodic dysphonia", a listener said, "most apparent
    when the voice model holds a note for an extended period".  Measured as a voice clinic measures it, successive
    cycles of the voice differ three times as much in length and twice as much in strength as in the same man's own
    recording (0.69% and 4.0% against 0.23% and 2.0%), whatever the model is given and however it is set.  It is not
    the timing of the cycles: the colour of the voice flickers from one moment to the next, and so does its loudness,
    and the model's pitch wanders.  So the sound is taken apart into what WORLD calls its spectral envelope (the
    colour, every 5 ms), its breath (how much of each band is noise) and its pitch, and put together again:
    - the pitch is the engine's, read from the engine's own sound cycle by cycle (_pitch_of);
    - the colour and the breath are steadied a little everywhere (CALM) and, inside each vowel the engine holds,
      a lot (CALM_HELD), each such vowel as a whole from 15 ms after it begins - what flutter was left sat "just
      after the attack" until then;
    - inside a held vowel the loudness (LEVEL_HELD) and the pitch (STILL) are steadied too.
    Where the engine has no voice - consonants, rests - the model's own sound is kept."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            import pyworld as pw
    except Exception:
        return None
    from scipy.signal import resample_poly
    from . import pitch
    n = len(src)
    if n < SR // 2:
        return y
    y = np.ascontiguousarray(y, np.float64); src = np.ascontiguousarray(src, np.float64)
    fp = 5.
    f, v = _pitch_of(src)
    if f is None:
        return y
    nfr = n // int(SR * fp / 1000) + 1
    t = np.arange(nfr) * fp / 1000
    k = np.minimum((t * SR).astype(int), n - 1)
    voiced = v[k]
    f0 = np.where(voiced, f[k], 0.)
    lf = np.log2(np.maximum(np.where(voiced, f[k], np.interp(k, np.flatnonzero(v), f[v])), 1.))
    sp = pw.cheaptrick(y, f0, t, SR)
    ap = np.minimum(pw.d4c(y, f0, t, SR), pw.d4c(src, f0, t, SR))  # no breathier than the engine sang it
    ls, la = np.log(sp + 1e-16), np.log(ap + 1e-16)
    if CALM:                                                       # everywhere a little: over 10 ms the flicker goes and the syllables stay
        ls, la = gf(ls, CALM * 1000 / fp, axis=0, mode='nearest'), gf(la, CALM * 1000 / fp, axis=0, mode='nearest')
    # Held vowels, as the engine sings them: voiced, the pitch not on its way to another note, the colour not changing.
    # Each is steadied as a whole, from 15 ms after it begins to 15 ms before it ends - a listener heard what was left
    # of the flutter "just after the attack", which is where a steadying that grows slowly into each note had not reached.
    le = np.log(pw.cheaptrick(src, f0, t, SR) + 1e-16)
    nb = le.shape[1]; edges = np.unique(np.geomspace(4, nb - 1, 25).astype(int))
    bands = np.stack([le[:, i:j].mean(1) for i, j in zip(edges[:-1], edges[1:])], 1)
    change = np.r_[0., 0., np.abs(bands[4:] - bands[:-4]).mean(1), 0., 0.] * 4.343      # dB the engine's colour changes in 20 ms
    moving = np.abs(np.gradient(gf(lf, 3.))) * 1200 * (1000 / fp) > 600        # the pitch on its way to another note
    steady = voiced & ~moving & (change < HELD_CHANGE)
    runs = np.flatnonzero(np.diff(np.r_[0, steady.astype(np.int8), 0]))
    for i0, i1 in zip(runs[::2], runs[1::2]):
        i0, i1 = i0 + 3, i1 - 3
        if i1 - i0 < 12:                                           # 60 ms: shorter than that is not a held note
            continue
        u = np.minimum(1., np.minimum(np.arange(i1 - i0), np.arange(i1 - i0)[::-1]) / 3.)[:, None]     # in and out over 15 ms
        if CALM_HELD:
            new = gf(ls[i0:i1], CALM_HELD * 1000 / fp, axis=0, mode='nearest')
            if LEVEL_HELD:                                         # the loudness of the whole, more slowly still: no wander 1-3 times a second
                lev = new.mean(1); new = new + (gf(lev, LEVEL_HELD * 1000 / fp, mode='nearest') - lev)[:, None]
            ls[i0:i1] = (1 - u) * ls[i0:i1] + u * new
            la[i0:i1] = (1 - u) * la[i0:i1] + u * gf(la[i0:i1], CALM_HELD * 1000 / fp, axis=0, mode='nearest')
        if STILL:
            lf[i0:i1] = (1 - u[:, 0]) * lf[i0:i1] + u[:, 0] * gf(lf[i0:i1], STILL * 1000 / fp, mode='nearest')
    f0 = np.where(voiced, 2. ** lf, 0.)
    sp, ap = np.exp(ls), np.exp(la)
    z = pw.synthesize(f0, sp, ap, SR, fp)[:n]
    z = np.pad(z, (0, max(0, n - len(z))))
    keep = np.interp(np.arange(n), t * SR, gf(voiced.astype(float), 1.6))    # 8 ms from the one to the other
    if CONS and alone:                                             # a soloist's consonants, brought to the strength the engine gave them
        sung = keep > .5
        if sung.sum() > SR // 10 and (~sung).sum() > SR // 20:
            whole = np.sqrt(np.mean(src[sung] ** 2) / (np.mean(z[sung] ** 2) + 1e-20))        # the two on one scale, by their sung parts
            g = np.clip(_env(src, .02) / (whole * _env(y, .02) + 1e-12), 10 ** (-6 / 20), 10 ** (CONS / 20))
            y = y * np.interp(np.arange(n), (np.arange(len(g)) + .5) * HOP, gf(g, .01 * SR / HOP))
    out = keep * z + (1 - keep) * y
    return _stops(out, src, keep) if STOPS and alone else out


def _stops(out, src, keep):
    """A rebuilt stretch with its stops put right - the d of "do", the b of "but".

    A stop is a moment of near silence (with a hum, for b d g) and then a click.  The model sings through the first
    and softens the second: where the engine has a closure 30-40 dB under the vowel and a click 24 dB under it, the
    model gives a murmur 14 dB under and a click 44 dB under - "the D seems to be dropped", a listener said - and the
    rebuilding, which takes a hummed closure for sung tone, smooths away what is left.  So, measured against the
    engine with the two on one scale: where the engine is in a closure (20 dB or more under the sound that follows
    within 120 ms) the stretch is turned down to the engine's level, and where the engine has a click (its sound
    above 2 kHz jumping 15 dB in 15 ms) that the stretch lacks by 6 dB or more, the engine's click is added."""
    from scipy.signal import butter, sosfiltfilt
    from scipy.ndimage import maximum_filter1d
    n = len(src)
    sung = keep > .5
    if sung.sum() < SR // 10:
        return out
    whole = np.sqrt(np.mean(src[sung] ** 2) / (np.mean(out[sung] ** 2) + 1e-20))       # the engine's scale over the stretch's
    up = lambda v: np.interp(np.arange(n), (np.arange(len(v)) + .5) * HOP, v)
    es, eo = _env(src, .008), _env(out, .008) * whole
    m = min(len(es), len(eo)); es, eo = es[:m], eo[:m]
    fps = SR / HOP
    ahead = maximum_filter1d(es, int(.12 * fps), origin=-int(.06 * fps))                 # the loudest the engine gets in the next 120 ms
    closed = (es < ahead * 10 ** (-20 / 20)) & (ahead > es.max() * 10 ** (-30 / 20))
    g = np.where(closed, np.clip(es / (eo + 1e-12), 10 ** (-30 / 20), 1.), 1.)
    out = out * up(gf(g, .003 * fps))
    hp = butter(4, 2000., 'hp', fs=SR, output='sos')
    hs, ho = sosfiltfilt(hp, src), sosfiltfilt(hp, out)
    cs, co = _env(hs, .003)[:m], _env(ho, .003)[:m] * whole
    k = int(.015 * fps)
    jump = np.r_[np.zeros(k), cs[k:] / (cs[:-k] + 1e-9 * cs.max())]
    click = (jump > 10 ** (15 / 20)) & (cs > es.max() * 10 ** (-45 / 20)) & (cs > co * 10 ** (6 / 20))
    if click.any():
        w = np.clip(gf(maximum_filter1d(click.astype(float), int(.02 * fps), origin=-int(.008 * fps)), .002 * fps) * 1.5, 0, 1)   # from the click on for 20 ms, soft-edged
        out = out + up(w) * hs / whole
    return out


def _fit_job(job):
    path, src, rebuilt, alone = job
    return _fit(_read(path), np.asarray(src, np.float64), rebuilt, alone).astype(np.float32)


def _fit(y, src, rebuilt=False, alone=False):
    """A re-voiced stretch, put where its original was: the same length, lined up with it, and as loud at every moment."""
    n = len(src)
    y = np.pad(y, (0, max(0, n - len(y))))[:n]
    a, b = _env(src, .01), _env(y, .01)                           # line up: the loudness of the two, compared at lags up to 60 ms
    a = a - a.mean(); b = b - b.mean()
    lags = range(-int(.06 * SR / HOP), int(.06 * SR / HOP) + 1)
    k = max(lags, key=lambda k: float(np.dot(a[max(0, -k):len(a) - max(0, k)], b[max(0, k):len(b) - max(0, -k)]))) * HOP
    y = np.pad(y, (0, k))[k:] if k > 0 else np.pad(y, (-k, 0))[:n]
    z = _rebuild(y, src, alone) if rebuilt else None              # the sung tone built again at the engine's pitch
    if z is not None:                                             # (its loudness is steadied there, note by note; made to follow the
        return z * np.sqrt(np.mean(src ** 2) / (np.mean(z ** 2) + 1e-20))      # engine's moment by moment, it was heard to fade oddly)
    y = _repitch(y, src)
    y = y * np.sqrt(np.mean(src ** 2) / (np.mean(y ** 2) + 1e-20))      # first as loud as the original on the whole; then moment by moment
    # the engine shaped every note's loudness against real singers; the model has ideas of its own.  The engine's are kept.
    g = np.clip(_env(src, .06) / _env(y, .06), 10 ** (-30 / 20), 10 ** (LIFT / 20))
    out = y * np.interp(np.arange(n), (np.arange(len(g)) + .5) * HOP, gf(g, .02 * SR / HOP))
    fade = min(int(.02 * SR), n // 2)
    out[:fade] *= np.linspace(0, 1, fade); out[-fade:] *= np.linspace(1, 0, fade)
    return out


def _sized(ref, size, work, made):
    """The recording at another size (semitones; + = a smaller voice): played that much faster, written into `work`."""
    if (ref, size) not in made:
        from fractions import Fraction
        from scipy.signal import resample_poly
        x = _read(ref)
        if not size and _plain(ref) and len(x) <= VOICE_SECONDS * SR:
            made[ref, size] = os.path.abspath(ref)
            return made[ref, size]
        fr = Fraction(2 ** (-size / 12)).limit_denominator(200)
        if size:
            x = resample_poly(x, fr.numerator, fr.denominator)
        if len(x) > VOICE_SECONDS * SR:                   # more leaves the model less room to work in, and tells it no more;
            x = x[:int(VOICE_SECONDS * SR)].copy(); x[-SR // 20:] *= np.linspace(1, 0, SR // 20)       # and one length for all sizes
        made[ref, size] = os.path.join(work, 'voice%03d.wav' % len(made))
        _write(made[ref, size], x)
    return made[ref, size]


PITCH_SMOOTH = 6.      # over how many pitch readings (2.9 ms each) the correction of the pitch is smoothed: quicker, and it roughens the voice
LOOSE = .03            # seconds a sung stretch may run ahead or behind before it is set right inside a note
TOP = ((3600, 5000), (5000, 8000), (8000, 12000), (12000, 20000))      # the bands of a voice's top end, Hz
_TOPS = {}


def _top(x):
    """How much of a voice's sung sound lies in each band of its top end (dB under everything below 3.6 kHz).
    A moment counts as sung when it is loud and most of it lies below 1 kHz."""
    n = (len(x) - 2048) // 1024
    if n < 8:
        return None
    fr = np.lib.stride_tricks.sliding_window_view(x, 2048)[::1024][:n] * np.hanning(2048)
    sp = np.abs(np.fft.rfft(fr, axis=1)) ** 2
    fq = np.fft.rfftfreq(2048, 1 / SR)
    e = sp.sum(1)
    k = (e > .003 * np.percentile(e, 95)) & (sp[:, (fq >= 80) & (fq < 1000)].sum(1) > .5 * e)
    if k.sum() < 8:
        return None
    body = sp[k][:, (fq >= 80) & (fq < 3600)].sum()
    return np.array([10 * np.log10(sp[k][:, (fq >= lo) & (fq < hi)].sum() / body + 1e-12) for lo, hi in TOP])


def _tame(y, ref):
    """A re-voiced singer's track with its top end brought down to that of the recording of his voice.

    The model's sound has more at the top than the voice it copies: on sung notes 8-16 dB more above 12 kHz and
    4-7 dB more from 8 to 12 kHz than the same man's own recording - a fizz on the tone - and its consonants are
    brighter still.  Each band above 3.6 kHz is lowered by what the track's sung notes have too much of there
    against the recording's (consonants come down with them), and never raised."""
    from scipy.signal import firwin2, fftconvolve
    if ref not in _TOPS:
        _TOPS[ref] = _top(_read(ref))
    a, b = _TOPS[ref], _top(np.asarray(y, np.float64))
    if a is None or b is None:
        return y
    cut = -np.clip(b - a, 0., 24.)
    if cut.min() > -1.:
        return y
    mid = [np.sqrt(lo * hi) for lo, hi in TOP]
    f = np.r_[0., 3000., mid, SR / 2]
    g = 10 ** (np.r_[0., 0., cut, cut[-1]] / 20)
    return fftconvolve(y, firwin2(511, f, g, fs=SR), mode='same').astype(np.asarray(y).dtype)


CACHE = os.path.join(ROOT, '.svc', 'cache')
CACHE_MAX = float(os.environ.get('CHORAL_CACHE_GB', 4)) * 2 ** 30     # bytes of converted singing kept for the next run (a long piece with twelve to a part is about 1 GB)


def _kept(job, cmd):
    """Where the result of this very job is kept: the same singing, the same voice, the same model, the same draw."""
    import hashlib
    more = sorted((k, v) for k, v in job.items() if k not in ('source', 'reference', 'out', 'seed'))     # settings passed on to the model
    h = hashlib.sha1(json.dumps([cmd, job.get('seed', 0)] + ([more] if more else [])).encode())
    for f in (job['source'], job['reference']):
        h.update(open(f, 'rb').read())
    return os.path.join(CACHE, h.hexdigest() + '.wav')


def _trim():
    files = sorted((os.path.join(CACHE, f) for f in os.listdir(CACHE)), key=os.path.getmtime)
    total = sum(os.path.getsize(f) for f in files)
    while files and total > CACHE_MAX:
        total -= os.path.getsize(files[0]); os.unlink(files.pop(0))


def revoice(tracks, voices, log=print, seed=0, rebuild=True, alone=None):
    """tracks: one dry mono track (at 44100 Hz) per singer.  voices: for each track a reference recording, or
    (recording, size) as deal() gives them.  rebuild: whether each voice's sung tone is built again at the engine's
    pitch (_rebuild; needs pyworld - without it the pitch and loudness are put back on the model's own sound).
    alone: for each track, whether it is a voice heard by itself, whose consonants are then put right as well.
    -> the tracks again, in those voices."""
    cmd = command()
    if cmd is None:
        raise SystemExit('No voice-conversion model is set up (looked for .svc/command.json): see docs/how-it-works.md, "A real voice\'s sound".')
    work = tempfile.mkdtemp(prefix='choral_revoice_')
    try:
        jobs, where, made = [], [], {}
        voices = [v if isinstance(v, tuple) else (v, 0.) for v in voices]
        for i, (x, (ref, size)) in enumerate(zip(tracks, voices)):
            x = np.asarray(x, np.float64)
            ref = _sized(ref, size, work, made)
            for k, (a, b, ka, kb) in enumerate(stretches(x)):
                seg = x[a:b]; peak = float(np.abs(seg).max()) or 1.
                src = os.path.join(work, f's{i:03d}_{k:03d}.wav')
                _write(src, seg / peak * .8)
                jobs.append(dict(source=src, reference=ref, out=src[:-4] + '_v.wav', seed=seed + i))
                where.append((i, a, b, ka, kb))
        total = sum(kb - ka for _, _, _, ka, kb in where) / SR
        log(f're-voicing {len(tracks)} singers: {total / 60:.0f} minutes of singing in {len(jobs)} stretches, in {len(set(v for v, _ in voices))} voice(s) ...')
        if rebuild:
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    import pyworld
            except Exception:
                log('  ! pyworld is not installed (pip install pyworld): held notes will be rougher than they need be, a soloist\'s most of all')
        os.makedirs(CACHE, exist_ok=True)
        kept = [_kept(j, cmd) for j in jobs]             # the engine sings a piece the same way every time: a second
        todo = [j for j, f in zip(jobs, kept) if not os.path.exists(f)]         # rendering finds its stretches converted
        if len(todo) < len(jobs):
            left = sum(kb - ka for (_, _, _, ka, kb), f in zip(where, kept) if not os.path.exists(f)) / SR
            log(f'  {len(jobs) - len(todo)} of the {len(jobs)} stretches were converted before and are reused'
                + ('' if not todo else ': less than a minute of singing is left to convert' if left < 60 else f': {left / 60:.0f} minutes of singing are left to convert'))
        said, code = '', 0
        if todo:
            import re
            jf = os.path.join(work, 'jobs.json')
            json.dump(todo, open(jf, 'w'))
            place = {j['out']: f for j, f in zip(jobs, kept)}
            safe = 0
            with open(os.path.join(work, 'errors.txt'), 'w+') as err:
                r = subprocess.Popen(cmd + [jf], stdout=subprocess.PIPE, stderr=err, text=True)
                try:
                    for line in r.stdout:                 # said as it happens: this is the long step
                        if 're-voiced' in line or 'model loaded' in line:
                            log(line.rstrip())
                        m = re.search(r're-voiced (\d+) of \d+ stretches', line)
                        if m:                             # a model that counts aloud has finished that many, in the order given:
                            upto = min(int(m.group(1)), len(todo))    # they are kept now, so that a render stopped half way
                            for j in todo[safe:upto]:                 # through its hour has lost a few stretches, not all of them
                                if os.path.exists(j['out']):
                                    shutil.copy(j['out'], place[j['out']] + '.part'); os.replace(place[j['out']] + '.part', place[j['out']])
                            safe = max(safe, upto)
                    code = r.wait()
                finally:
                    if r.poll() is None:                  # the render was stopped: the model is not left running by itself
                        r.kill()
                err.seek(0); said = err.read()
        for j, f in zip(jobs, kept):
            if os.path.exists(f):
                os.utime(f); j['out'] = f
            elif os.path.exists(j['out']):
                shutil.copy(j['out'], f + '.part'); os.replace(f + '.part', f)
        _trim()
        missing = [j for j in jobs if not os.path.exists(j['out'])]
        if code or missing:
            raise SystemExit('The voice-conversion model failed' + (f' ({len(missing)} of {len(jobs)} stretches missing)' if missing else '') + ':\n' + said[-1500:])
        out = [np.zeros(len(x), np.float32) for x in tracks]
        from multiprocessing import Pool, cpu_count
        try:
            few = max(1, int(os.environ['CHORAL_WORKERS']))      # (a machine short of memory: see render.at_once)
        except (KeyError, ValueError):
            few = 8
        with Pool(min(8, few, cpu_count())) as pool:
            fitted = pool.imap(_fit_job, [(j['out'], np.asarray(tracks[i][a:b], np.float32), bool(rebuild), bool(alone and alone[i])) for j, (i, a, b, ka, kb) in zip(jobs, where)], chunksize=2)
            for (i, a, b, ka, kb), y in zip(where, fitted):
                w = np.ones(kb - ka, np.float32)         # pieces cut from one stretch are crossed over: in 12 ms where
                top = float(np.abs(tracks[i]).max())     # it is quiet, in 40 ms where the cut had to be made in a held note
                loud = lambda c: float(np.abs(tracks[i][max(c - 441, 0):c + 441]).max()) > .03 * top
                if ka > a:                               # there is a piece before this one
                    f = int((.04 if loud(ka) else .012) * SR); h = min(f // 2, ka - a)
                    ka -= h; w = np.r_[np.zeros(h, np.float32), w]; w[:2 * h] = np.sin(np.linspace(0, np.pi / 2, 2 * h)) ** 2
                if kb < b:
                    f = int((.04 if loud(kb) else .012) * SR); h = min(f // 2, b - kb)
                    kb += h; w = np.r_[w, np.zeros(h, np.float32)]; w[len(w) - 2 * h:] = np.cos(np.linspace(0, np.pi / 2, 2 * h)) ** 2
                out[i][ka:kb] += y[ka - a:kb - a] * w
        heard = {}                                       # (a voice at another size is a file of its own; its top is measured once)
        for i in range(len(out)):
            ref = _sized(voices[i][0], voices[i][1], work, made)
            out[i] = _tame(out[i], heard.setdefault(ref, ref))
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
