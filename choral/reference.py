"""Practice tracks -> the pieces hidden inside them.

Learning tracks usually come as a set made from the same recording: Balanced, Accompaniment, and
"<part> predominant" (sometimes "<part> muted").  When the set really is the same takes at
different levels, the tracks can be subtracted from one another to leave the voices alone, the
accompaniment alone, and one singer's part alone - which is what the engine is checked against.
"""
import os, shutil, subprocess, tempfile, wave
import numpy as np
from scipy.signal import resample_poly

SR = 44100


def load_audio(path, sr=SR):
    """Any audio file -> float stereo at 44.1 kHz.  WAV is read directly; other formats go through
    ffmpeg (or afconvert on a Mac)."""
    tmp = None
    if not path.lower().endswith('.wav'):
        tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False).name
        if shutil.which('ffmpeg'):
            cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', path, '-ar', str(sr), '-ac', '2', tmp]
        elif shutil.which('afconvert'):
            cmd = ['afconvert', '-f', 'WAVE', '-d', f'LEI16@{sr}', '-c', '2', path, tmp]
        else:
            raise SystemExit(f'cannot read {path}: install ffmpeg, or convert the file to WAV first')
        subprocess.run(cmd, check=True)
    w = wave.open(tmp or path); r = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()) / 32768
    if tmp:
        os.unlink(tmp)
    x = x if x.shape[1] == 2 else np.repeat(x[:, :1], 2, axis=1)
    return resample_poly(x, sr, r, axis=0) if r != sr else x


def _gain(target, of, sl):
    """How much of `of` is inside `target` over the samples sl (least squares)."""
    a, b = target[sl].ravel(), of[sl].ravel()
    return float(a @ b / (b @ b + 1e-12))


def _db(x):
    return 10 * np.log10((x ** 2).mean() + 1e-12)


def isolate(sc, clock, part, balanced, accompaniment, predominant=None, muted=None, log=print):
    """-> dict with 'voices', 'accompaniment' (at its level in the balanced mix), 'part' (if it can
    be had), and 'clean': how many dB the accompaniment drops when subtracted (under ~15 dB the
    tracks are not the same takes and nothing here should be trusted)."""
    n = min(len(x) for x in (balanced, accompaniment, predominant, muted) if x is not None)
    if clock is None:               # first pass, before the timing is known: use the whole file, and the opening seconds
        a = _gain(balanced, accompaniment, slice(0, n))
        voices = balanced[:n] - a * accompaniment[:n]
        q = slice(0, 0)
        for k in range(0, n - SR, SR // 2):                 # the longest run with almost nothing left = accompaniment alone
            j = k
            while j < n - SR and _db(voices[j:j + SR // 2]) < _db(balanced[j:j + SR // 2]) - 15 and _db(balanced[j:j + SR // 2]) > -55:
                j += SR // 2
            if j - k > q.stop - q.start:
                q = slice(k, j)
        clean = _db(balanced[q]) - _db(voices[q]) if q.stop - q.start >= SR else _db(balanced[:n]) - _db(voices) 
        out = {'voices': voices, 'accompaniment': a * accompaniment[:n], 'clean': clean if q.stop - q.start >= SR else 0., 'acc_gain': a}
        if out['clean'] >= 15 and (muted is not None or predominant is not None):
            other = muted if muted is not None else predominant
            b = _gain(other, accompaniment, q)
            rest = other[:n] - b * accompaniment[:n]
            out['part'] = voices - rest if muted is not None else rest
        return out
    T = lambda b: float(np.interp(b, clock[0], clock[1]))
    span = lambda b0, b1: slice(max(0, int(T(b0) * SR)), min(n, int(T(b1) * SR)))
    sung = sorted((nt['beat'], nt['beat'] + nt['dur'], p) for p in sc.parts for nt in sc.parts[p])
    # stretches where nobody sings (the introduction, interludes): only the accompaniment sounds
    quiet, t = [], 0.
    for b0, b1, _ in sung:
        if b0 - t >= 4:
            quiet.append(span(t + 1, b0 - 1))
        t = max(t, b1)
    if not quiet:
        quiet = [slice(0, n)]
    q = max(quiet, key=lambda s: s.stop - s.start)
    a = _gain(balanced, accompaniment, q)
    voices = balanced[:n] - a * accompaniment[:n]
    clean = _db(balanced[q]) - _db(voices[q])
    out = {'voices': voices, 'accompaniment': a * accompaniment[:n], 'clean': clean, 'acc_gain': a}
    log(f'accompaniment is in the balanced mix at {a:.2f}; subtracting it leaves {clean:.0f} dB less in the introduction')
    if clean < 15:
        return out
    if muted is not None:                                   # balanced minus "part muted" = the part
        am = _gain(muted, accompaniment, q)
        rest = muted[:n] - am * accompaniment[:n]
        # The two mixes may be at different levels; the accompaniment, which is in both, says by how much.  (Scaling
        # the others by how much of the full choir they explain overshoots - the part itself is in the full choir
        # too - and leaves the others in the result upside down: on one piece that put only 56% of the part's
        # notes on pitch where taking them out level for level gives 94%.)
        k = a / am if am > 1e-6 and .5 < a / am < 2 else 1.
        out['part'] = voices - k * rest
    elif predominant is not None:                           # predominant = part + c * others + b * accompaniment
        b = _gain(predominant, accompaniment, q)
        pv = predominant[:n] - b * accompaniment[:n]
        mine = sorted((b0, b1) for b0, b1, p in sung if p == part)
        rests = []                                          # the others sing while this part is silent
        for (s0, s1), (n0, n1) in zip(mine, mine[1:] + [(sc.beats, sc.beats)]):
            if n0 - s1 >= 3 and any(o0 < n0 - 1 and o1 > s1 + 1 for o0, o1, p in sung if p != part):
                rests.append(span(s1 + 1.5, n0 - .5))
        if mine and mine[0][0] >= 3:
            rests.append(span(0, mine[0][0] - .5))
        num = sum(float(pv[s].ravel() @ voices[s].ravel()) for s in rests)
        den = sum(float(voices[s].ravel() @ voices[s].ravel()) for s in rests)
        c = num / den if den > 0 else 0.
        c = c if 0 <= c < .9 else 0.
        out['part'] = (pv - c * voices) / (1 - c)
        log(f'predominant track: accompaniment at {b:.2f}, the other parts at {c:.2f}')
    return out
