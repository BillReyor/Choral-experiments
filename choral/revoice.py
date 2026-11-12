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


LONGEST, HARD = 11., 14.   # seconds of singing handed over in one piece: aimed at, and never more than
VOICE_SECONDS = 14.        # how much of a recording of a voice the model is given


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
    on = env > env.max() * 10 ** (floor / 20)
    if not on.any() or env.max() < 1e-6:
        return []
    edges = np.flatnonzero(np.diff(np.r_[0, on.astype(np.int8), 0])) * HOP
    spans = [[a, b] for a, b in zip(edges[::2], edges[1::2])]
    out = [spans[0]]
    for a, b in spans[1:]:
        if a - out[-1][1] < gap * sr:
            out[-1][1] = b
        else:
            out.append([a, b])
    p = int(pad * sr); pieces = []
    quiet = _env(x, .03) < env.max() * 10 ** (-35 / 20)          # per HOP samples

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
    that many cents slower or faster (at most a semitone).  Playing faster also arrives sooner: when it has run a
    whole period of the voice ahead or behind, one period is dropped or repeated, and in a silence it is set right."""
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
    filled = gf(filled, 2.5)
    t = (np.arange(k) * hop + 512) * 2.                           # where each value sits, in samples at 44100
    rate = 2. ** (-np.interp(np.arange(n), t, filled) / 1200.)
    ahead = np.cumsum(rate - 1.)                                  # how far the reading has run ahead, in samples
    period = SR / (440. * 2. ** ((np.where(np.isnan(my[:k]), 60., my[:k]) - 69.) / 12.))
    step = np.zeros(n); jumps = []; off = 0.
    for i in range(k):
        j = int(min(t[i], n - 1)); a = ahead[j] + off
        if ok[i] and abs(a) > period[i]:                          # a whole period out: drop or repeat one
            off -= np.sign(a) * period[i]; jumps.append((j, -np.sign(a) * period[i]))
        elif near[i] > 12 and abs(a) > 20:                        # nothing sung here: set it right
            off -= a; jumps.append((j, -a))
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


def _fit_job(job):
    path, src = job
    return _fit(_read(path), np.asarray(src, np.float64)).astype(np.float32)


def _fit(y, src):
    """A re-voiced stretch, put where its original was: the same length, lined up with it, and as loud at every moment."""
    n = len(src)
    y = np.pad(y, (0, max(0, n - len(y))))[:n]
    a, b = _env(src, .01), _env(y, .01)                           # line up: the loudness of the two, compared at lags up to 60 ms
    a = a - a.mean(); b = b - b.mean()
    lags = range(-int(.06 * SR / HOP), int(.06 * SR / HOP) + 1)
    k = max(lags, key=lambda k: float(np.dot(a[max(0, -k):len(a) - max(0, k)], b[max(0, k):len(b) - max(0, -k)]))) * HOP
    y = np.pad(y, (0, k))[k:] if k > 0 else np.pad(y, (-k, 0))[:n]
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
        if len(x) > VOICE_SECONDS * SR:                   # more leaves the model less room to work in, and tells it no more
            x = x[:int(VOICE_SECONDS * SR)].copy(); x[-SR // 20:] *= np.linspace(1, 0, SR // 20)
        elif not size and _plain(ref):
            made[ref, size] = os.path.abspath(ref)
            return made[ref, size]
        fr = Fraction(2 ** (-size / 12)).limit_denominator(200)
        made[ref, size] = os.path.join(work, 'voice%03d.wav' % len(made))
        _write(made[ref, size], resample_poly(x, fr.numerator, fr.denominator) if size else x)
    return made[ref, size]


CACHE = os.path.join(ROOT, '.svc', 'cache')
CACHE_MAX = 4e9                    # bytes; the oldest go first


def _kept(job, cmd):
    """Where the result of this very job is kept: the same singing, the same voice, the same model, the same draw."""
    import hashlib
    h = hashlib.sha1(json.dumps([cmd, job.get('seed', 0)]).encode())
    for f in (job['source'], job['reference']):
        h.update(open(f, 'rb').read())
    return os.path.join(CACHE, h.hexdigest() + '.wav')


def _trim():
    files = sorted((os.path.join(CACHE, f) for f in os.listdir(CACHE)), key=os.path.getmtime)
    total = sum(os.path.getsize(f) for f in files)
    while files and total > CACHE_MAX:
        total -= os.path.getsize(files[0]); os.unlink(files.pop(0))


def revoice(tracks, voices, log=print, seed=0):
    """tracks: one dry mono track (at 44100 Hz) per singer.  voices: for each track a reference recording, or
    (recording, size) as deal() gives them.  -> the tracks again, in those voices."""
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
        os.makedirs(CACHE, exist_ok=True)
        kept = [_kept(j, cmd) for j in jobs]             # the engine sings a piece the same way every time: a second
        todo = [j for j, f in zip(jobs, kept) if not os.path.exists(f)]         # rendering finds its stretches converted
        if len(todo) < len(jobs):
            log(f'  {len(jobs) - len(todo)} of the {len(jobs)} stretches were converted before and are reused')
        said, code = '', 0
        if todo:
            jf = os.path.join(work, 'jobs.json')
            json.dump(todo, open(jf, 'w'))
            with open(os.path.join(work, 'errors.txt'), 'w+') as err:
                r = subprocess.Popen(cmd + [jf], stdout=subprocess.PIPE, stderr=err, text=True)
                for line in r.stdout:                     # said as it happens: this is the long step
                    if 're-voiced' in line or 'model loaded' in line:
                        log(line.rstrip())
                code = r.wait()
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
        with Pool(min(8, cpu_count())) as pool:
            fitted = pool.imap(_fit_job, [(j['out'], np.asarray(tracks[i][a:b], np.float32)) for j, (i, a, b, ka, kb) in zip(jobs, where)], chunksize=2)
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
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
