"""Spectral comparison: where does the generated voice differ from a real singer?

    python tools/compare.py SCORE PART REAL.wav --offset 1.06 --bpm 100          (a recording at one tempo)
    python tools/compare.py SCORE PART REAL.wav --timing MAP.json                (a tempo map from choral.timing)
    python tools/compare.py --jobs JOBS.json                                     (several singers: what do they share?)

REAL.wav is one real singer alone - a part isolated from practice tracks (python -m choral does the isolating).
The same part is sung by a few simulated singers on the recording's timing, both are measured note by note
(tone in 16 bands, loudness through each note, how the colour changes through a note, entries, releases, loud
against soft, steadiness) and the differences are listed, largest first.  See choral/compare.py.

--preset FILE applies a piece's saved settings (note fade, swell, entry speed, scoop) to the simulated singers.
A jobs file is a list of {"name", "score", "part", "wav", and "offset"+"bpm" or "timing", optionally "channel",
"preset"}; with several singers the report ends with the differences they have in common - the ones worth a
change to the voice itself rather than to one piece's settings.
"""
import argparse, json, os, sys, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from choral import score, compare as C, render as R


def load(path, channel=None):
    if path.endswith('.npy'):
        return np.load(path).astype(float), C.SR
    w = wave.open(path); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()) / 32768
    return (x.mean(1) if channel is None else x[:, channel]), sr


def one(job):
    sc = score.load(job['score'], warn=lambda *a: None)
    tm = job.get('timing')
    if isinstance(tm, str):
        tm = json.load(open(tm)); tm = tm.get('timing', tm)
    if not tm:
        tm = {'offset': job['offset'], 'bpm': job['bpm']}
    settings = {}
    if job.get('preset'):
        settings = R.tune_of(json.load(open(job['preset'])))
    x, sr = load(job['wav'], job.get('channel'))
    return C.run(sc, job['part'], x, sr, tm, [int(i) for i in job.get('singers', C.SINGERS)], settings, pool=job.get('pool', True))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score', nargs='?'); ap.add_argument('part', nargs='?'); ap.add_argument('wav', nargs='?')
    ap.add_argument('--offset', type=float, default=0.); ap.add_argument('--bpm', type=float)
    ap.add_argument('--timing', help='a tempo map (JSON with beats and secs), or a preset file that holds one')
    ap.add_argument('--channel', type=int); ap.add_argument('--preset'); ap.add_argument('--singers', default=','.join(map(str, C.SINGERS)))
    ap.add_argument('--jobs', help='a JSON list of singers to compare together'); ap.add_argument('--out', help='also write the report here')
    a = ap.parse_args()
    if a.jobs:
        jobs = [dict(j, pool=False) for j in json.load(open(a.jobs))]
        from multiprocessing import Pool
        with Pool(min(len(jobs), os.cpu_count() or 4), maxtasksperchild=1) as pool:      # a fresh process per singer: settings do not leak
            res = pool.map(one, jobs, chunksize=1)
        names = [j.get('name', j['part']) for j in jobs]
        text = []
        ok = [(n, r) for n, r in zip(names, res) if 'tone' in r['diff']]
        for n, r in zip(names, res):
            text.append(C.report(r, n, top=6).split('\nTone of held notes')[0])
        if len(ok) >= 2:
            med, agree, t = C.across([r for _, r in ok], [n for n, _ in ok])
            text.append(t)
            text.append('\nMedian tone difference (Hz)\n  ' + ' '.join('%5.0f' % hz for hz in C.CENTRES) + '\n  ' + ' '.join('%+5.1f' % v for v in med['tone']))
            for kind in ('first', 'middle', 'last'):
                if 'shape_' + kind in med:
                    text.append(f'Median shape difference, {kind:6s} note ' + ' '.join('%+5.0f' % v for v in med['shape_' + kind]))
        text = '\n\n'.join(text)
    else:
        if not (a.score and a.part and a.wav):
            ap.error('give SCORE PART REAL.wav, or --jobs')
        if not a.timing and not a.bpm:
            ap.error('say where the beat is: --offset and --bpm, or --timing')
        job = dict(score=a.score, part=a.part, wav=a.wav, offset=a.offset, bpm=a.bpm, timing=a.timing, channel=a.channel, preset=a.preset,
                   singers=a.singers.split(','))
        text = C.report(one(job), f'{os.path.basename(a.wav)} ({a.part})')
    print(text)
    if a.out:
        open(a.out, 'w').write(text + '\n')


if __name__ == '__main__':
    main()
