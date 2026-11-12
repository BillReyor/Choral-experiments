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


def stretches(x, sr=SR, floor=-48., gap=1.5, pad=.3):
    """Where a singer sings -> [(first sample, last sample)]: silences shorter than `gap` seconds stay inside a stretch,
    and each stretch takes a little of the silence around it."""
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
    return [(max(0, a - int(pad * sr)), min(len(x), b + int(pad * sr))) for a, b in out]


def _write(path, x, sr=SR):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())


def _read(path):
    with wave.open(path) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()).mean(1) / 32768
    if sr != SR:
        from scipy.signal import resample_poly
        x = resample_poly(x, SR, sr)
    return x


def _fit(y, src):
    """A re-voiced stretch, put where its original was: the same length, lined up with it, and as loud at every moment."""
    n = len(src)
    y = np.pad(y, (0, max(0, n - len(y))))[:n]
    a, b = _env(src, .01), _env(y, .01)                           # line up: the loudness of the two, compared at lags up to 60 ms
    a = a - a.mean(); b = b - b.mean()
    lags = range(-int(.06 * SR / HOP), int(.06 * SR / HOP) + 1)
    k = max(lags, key=lambda k: float(np.dot(a[max(0, -k):len(a) - max(0, k)], b[max(0, k):len(b) - max(0, -k)]))) * HOP
    y = np.pad(y, (0, k))[k:] if k > 0 else np.pad(y, (-k, 0))[:n]
    # the engine shaped every note's loudness against real singers; the model has ideas of its own.  The engine's are kept.
    g = np.clip(_env(src, .06) / _env(y, .06), 10 ** (-30 / 20), 10 ** (10 / 20))
    out = y * np.interp(np.arange(n), (np.arange(len(g)) + .5) * HOP, gf(g, .02 * SR / HOP))
    fade = min(int(.02 * SR), n // 2)
    out[:fade] *= np.linspace(0, 1, fade); out[-fade:] *= np.linspace(1, 0, fade)
    return out


def revoice(tracks, voices, log=print, seed=0):
    """tracks: one dry mono track (at 44100 Hz) per singer.  voices: one reference recording per track.
    -> the tracks again, in those voices."""
    cmd = command()
    if cmd is None:
        raise SystemExit('No voice-conversion model is set up (looked for .svc/command.json): see docs/how-it-works.md, "A real voice\'s sound".')
    work = tempfile.mkdtemp(prefix='choral_revoice_')
    try:
        jobs, where = [], []
        for i, (x, ref) in enumerate(zip(tracks, voices)):
            x = np.asarray(x, np.float64)
            for k, (a, b) in enumerate(stretches(x)):
                seg = x[a:b]; peak = float(np.abs(seg).max()) or 1.
                src = os.path.join(work, f's{i:03d}_{k:03d}.wav')
                _write(src, seg / peak * .8)
                jobs.append(dict(source=src, reference=os.path.abspath(ref), out=src[:-4] + '_v.wav', seed=seed + i))
                where.append((i, a, b))
        total = sum(b - a for _, a, b in where) / SR
        log(f're-voicing {len(tracks)} singers: {total / 60:.0f} minutes of singing in {len(jobs)} stretches, in {len(set(voices))} voice(s) ...')
        jf = os.path.join(work, 'jobs.json')
        json.dump(jobs, open(jf, 'w'))
        r = subprocess.run(cmd + [jf], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in r.stdout.splitlines():
            if 're-voiced' in line or 'loaded' in line:
                log(line.rstrip())
        missing = [j for j in jobs if not os.path.exists(j['out'])]
        if r.returncode or missing:
            raise SystemExit('The voice-conversion model failed' + (f' ({len(missing)} of {len(jobs)} stretches missing)' if missing else '') + ':\n' + r.stderr[-1500:])
        out = [np.zeros(len(x), np.float32) for x in tracks]
        for j, (i, a, b) in zip(jobs, where):
            out[i][a:b] += _fit(_read(j['out']), np.asarray(tracks[i][a:b], np.float64)).astype(np.float32)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
