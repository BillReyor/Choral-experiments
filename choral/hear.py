"""A speech recognizer as a stand-in for ears: how many of the score's own words come through?

Needs `whisper-cli` (brew install whisper-cpp) and a model file; set WHISPER_MODEL to its path.
"""
import os, re, shutil, subprocess, tempfile, wave
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from scipy.signal import resample_poly

words = lambda s: re.sub(r"[^a-z' ]", ' ', s.lower()).split()


def model_path():
    m = os.environ.get('WHISPER_MODEL', 'models/ggml-small.en.bin')
    return m if shutil.which('whisper-cli') and os.path.exists(m) else None


def lcs(a, b):
    L = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        for j in range(len(b)):
            L[i + 1][j + 1] = L[i][j] + 1 if a[i] == b[j] else max(L[i][j + 1], L[i + 1][j])
    return L[-1][-1]


def text(sc, part, b0, b1):
    out, cur = [], ''
    for n in sc.parts[part]:
        if n['lyric'] in ('_', None) or not (b0 <= n['beat'] < b1):
            continue
        s = re.sub(r"[^A-Za-z'-]", '', n['lyric'])
        cur += s.rstrip('-')
        if not s.endswith('-'):
            out.append(cur.lower()); cur = ''
    return out


def hear(x, sr, model):
    y = resample_poly(x, 16000, sr); y = y / (np.abs(y).max() + 1e-9) * .8
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        path = f.name
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes((y * 32767).astype('<i2').tobytes())
    r = subprocess.run(['whisper-cli', '-m', model, '-f', path, '-nt', '-np', '-l', 'en'], capture_output=True, text=True)
    os.unlink(path)
    return ' '.join(r.stdout.split())


def understood(sc, x, sr, T, model=None, every=8, parts=None, log=None, detail=False):
    """Fraction of the score's words recognized, averaged over stretches of `every` measures.
    x is mono audio; T maps a beat to its time in x; parts limits whose text counts."""
    model = model or model_path()
    nums = sorted(sc.measures); jobs = []
    for i in range(0, len(nums), every):
        b0 = sc.measures[nums[i]][0]; last = nums[min(i + every, len(nums)) - 1]
        b1 = sc.measures[last][0] + sc.measures[last][1]
        targets = [t for t in (text(sc, p, b0, b1) for p in (parts or sc.parts)) if t]
        if targets:
            jobs.append((nums[i], last, targets, x[int(T(b0) * sr):int((T(b1) + .4) * sr)]))
    with ThreadPoolExecutor(4) as ex:
        heard = list(ex.map(lambda j: hear(j[3], sr, model), jobs))
    tot, near = [], []
    for (m0, m1, targets, _), h in zip(jobs, heard):
        tot.append(max(lcs(words(h), t) / len(t) for t in targets))
        near.append(max(SequenceMatcher(None, ''.join(words(h)), ''.join(t)).ratio() for t in targets))
        if log:
            log(f'  m{m0}-{m1}  {tot[-1]:.2f} | {h}')
    if detail:      # also how close the letters are: partial credit, so a steadier number for comparing settings
        return (float(np.mean(tot)), float(np.mean(near))) if tot else (0., 0.)
    return float(np.mean(tot)) if tot else 0.
