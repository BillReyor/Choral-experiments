"""Use a speech recognizer as a stand-in for ears.

    python tools/listen.py SCORE AUDIO.wav [--offset 1.0] [--bpm 100] [--every 8]

Cuts the recording into stretches of a few measures, transcribes each with whisper.cpp, and
reports how many of the score's own words came through.  Run it on a real recording of the same
piece as well: that number is the yardstick, because even real choirs are not 100% intelligible.

Needs `whisper-cli` (brew install whisper-cpp) and a model file; set WHISPER_MODEL to its path.
"""
import argparse, os, re, subprocess, sys, tempfile, wave
import numpy as np
from scipy.signal import resample_poly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from choral import score as S

words = lambda s: re.sub(r"[^a-z' ]", ' ', s.lower()).split()


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score'); ap.add_argument('audio')
    ap.add_argument('--offset', type=float, default=1.0, help='seconds before beat 1 (choral.render uses 1.0)')
    ap.add_argument('--bpm', type=float); ap.add_argument('--every', type=int, default=8)
    ap.add_argument('--model', default=os.environ.get('WHISPER_MODEL', 'models/ggml-small.en.bin'))
    a = ap.parse_args()
    sc = S.parse(open(a.score).read(), warn=lambda *x: None)
    w = wave.open(a.audio); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()).mean(1) / 32768
    spb = 60 / (a.bpm or sc.tempo[0][1])
    nums = sorted(sc.measures); tot = []
    for i in range(0, len(nums), a.every):
        b0 = sc.measures[nums[i]][0]; last = nums[min(i + a.every, len(nums)) - 1]
        b1 = sc.measures[last][0] + sc.measures[last][1]
        targets = [t for t in (text(sc, p, b0, b1) for p in sc.parts) if t]
        if not targets:
            continue
        h = hear(x[int((a.offset + b0 * spb) * sr):int((a.offset + b1 * spb + .4) * sr)], sr, a.model)
        best = max(lcs(words(h), t) / len(t) for t in targets); tot.append(best)
        print(f'  m{nums[i]}-{last}  {best:.2f} | {h}')
    print(f'words understood: {100 * np.mean(tot):.0f}%')


if __name__ == '__main__':
    main()
