"""Sheet music in, a sung rendering out.

    python -m choral MUSIC [--part baritone] [--accompaniment TRACK] [--out DIR]
                           [--balanced TRACK --predominant TRACK | --muted TRACK] [--tune]

MUSIC is a score file (docs/score-format.md) or a PDF exported from notation software.

  --part            tenor1, tenor2, baritone or bass (or several, with commas): also write that
                    part predominant (the others quiet behind it), muted (everyone else, to sing
                    against) and alone.  In three-part music "bass" is baritones and basses together
  --accompaniment   a recording of the accompaniment to sing over, instead of the built-in piano
  --balanced, --predominant, --muted
                    practice tracks of the same piece, if you have them (--predominant may list one
                    track per part named in --part, separated by commas).  They are only listened
                    to: the tempo and its bends, the hall and the balance are measured from them
  --tune            let a speech recognizer choose how close the microphones are (needs whisper-cli)
  --only            write just one version, e.g. --only "Baritone predominant"

What was estimated for the piece is saved beside the score as NAME.preset.json and reused.
"""
import argparse, json, os, re, subprocess, sys, time
import numpy as np
from . import render as R, score as scoremod, presets, reference, voice

PARTS = {'tenor1': 'T1', 't1': 'T1', 'tenor2': 'T2', 't2': 'T2', 'baritone': 'BR', 'br': 'BR', 'bari': 'BR', 'bass': 'BS', 'bs': 'BS', 'solo': 'SOLO'}


def read_music(path, log):
    """A .score file as it is; a PDF through the reader that suits it: tools/pdf2score.py when the notes are
    drawn as shapes (exported from notation software), tools/scan2score.py when the pages are pictures."""
    if not path.lower().endswith('.pdf'):
        return path
    out = os.path.splitext(path)[0] + '.score'
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
        log(f'using {out}, read from this PDF earlier (delete it to read the PDF again)')
        return out
    tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')
    import pymupdf
    doc = pymupdf.open(path)
    drawn = sum(len(p.get_drawings()) for p in doc) / max(len(doc), 1)
    if drawn > 200:                                  # vector: hundreds of shapes a page
        r = subprocess.run([sys.executable, os.path.join(tools, 'pdf2score.py'), path, out], capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out):
            log(r.stdout.strip()); log(f'read {path} -> {out}')
            return out
    log('this PDF is a scan: recognizing the notes (about half a minute a page)...')
    r = subprocess.run([sys.executable, os.path.join(tools, 'scan2score.py'), path, out])
    if r.returncode or not os.path.exists(out):
        raise SystemExit('Could not read the music out of this PDF.')
    log(f'read {path} -> {out}  (check it: a misread note or word is easier to fix there than to hear)')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('music'); ap.add_argument('--out'); ap.add_argument('--part')
    ap.add_argument('--accompaniment'); ap.add_argument('--balanced'); ap.add_argument('--predominant'); ap.add_argument('--muted')
    ap.add_argument('--tune', action='store_true'); ap.add_argument('--only'); ap.add_argument('--singers', type=int)
    ap.add_argument('--preset', help='a preset file to use instead of NAME.preset.json')
    ap.add_argument('--fresh', action='store_true', help='ignore a saved preset and estimate again')
    a = ap.parse_args()
    log = lambda *s: print(*s, flush=True)
    t0 = time.time()
    path = read_music(a.music, log)
    sc = scoremod.load(path, warn=log)
    same = lambda p, q: [(n['beat'], n['dur'], n['midi']) for n in sc.parts[p]] == [(n['beat'], n['dur'], n['midi']) for n in sc.parts[q]]
    groups = []                                    # (name, [sections]) for every part asked for
    for word in filter(None, (a.part or '').lower().replace(' ', '').split(',')):
        p = PARTS.get(word)
        if not p or not sc.parts[p]:
            raise SystemExit(f'--part takes tenor1, tenor2, baritone, bass or solo (several with commas), and the part must be in the score; got "{word}"')
        if p in ('BR', 'BS') and same('BR', 'BS'):          # three-part music: baritones and basses sing one line
            groups.append(('Bass', ['BR', 'BS']))
        elif p in ('T1', 'T2') and same('T1', 'T2'):
            groups.append(('Tenor', ['T1', 'T2']))
        else:
            groups.append((R.NAMES[p], [p]))
    part = groups[0][1][-1] if groups else None    # the part a --predominant track belongs to
    title = sc.title or os.path.splitext(os.path.basename(path))[0]
    log(f'{title}: {len(sc.measures)} measures, {sum(len(v) for v in sc.parts.values())} sung notes, {len(sc.piano)} piano notes')

    # ---- the piece's preset: saved, or estimated from the score, then from whatever recordings there are
    pfile = a.preset or os.path.splitext(path)[0] + '.preset.json'
    P = dict(R.PRESET, **presets.from_score(sc))
    log(f"the quick syllables last {P['quick_syllable']}s: starting from leaders' mics {P['spot']}, hall {P['hall']}")
    saved = json.load(open(pfile)) if os.path.exists(pfile) and not a.fresh else {}
    P.update(saved)
    if a.singers:
        P['singers'] = a.singers
    L = lambda f: reference.load_audio(f) if f else None
    track = L(a.accompaniment)
    ref_voices = None
    if a.balanced and (a.accompaniment or a.muted or a.predominant):
        if not a.accompaniment:
            raise SystemExit('to learn from practice tracks I also need the accompaniment-only track (--accompaniment)')
        preds = [L(f) for f in (a.predominant or '').split(',') if f]
        more = {g[1][-1]: x for g, x in zip(groups[1:], preds[1:])}
        est, iso = presets.from_recordings(sc, part or 'BR', L(a.balanced), track, preds[0] if preds else None, L(a.muted), log, more)
        P.update(est)
        ref_voices = iso['voices'] if iso['clean'] >= 15 else None
    elif track is not None and 'timing' not in P and not sc.timing:
        from . import timing
        P['timing'] = timing.from_accompaniment(sc, track.mean(1), R.SR, log)

    # ---- sing
    clock = R.clock_for(sc, P.get('timing'), absolute=track is not None)
    total = float(np.interp(sc.beats, *clock)) + 4.0
    if track is not None:
        total = max(total, len(track) / R.SR)
    stems = R.sing(sc, (*clock, total), P['singers'], log, tune={'TUNE.note_decay': P.get('note_decay', 0.)})
    if ref_voices is not None and ('hall_from' not in saved or a.fresh):
        got = presets.match_hall(stems, P, ref_voices, log)
        P.update(got, **({'hall_from': 'recording'} if got else {}))
    if a.tune:
        P.update(presets.tune_for_words(stems, sc, clock, P, keep_hall=P.get('hall_from') == 'recording', log=log))
    json.dump(P, open(pfile, 'w'), indent=1)
    log(f"preset: leaders' mics {P['spot']}, hall {P['hall']} ({P['hall_rt']}s), accompaniment {P['backing']}, note decay {P.get('note_decay', 0.)}  -> {pfile}")

    # ---- mix and write
    vox = R.mix_voices(stems, P) if part else {'all': R.choir(stems, P)}
    N = next(iter(vox.values())).shape[0]
    out = R.versions(vox, R.backing(sc, N, voice.T, P, track), P, groups)
    outdir = a.out or 'out'
    os.makedirs(outdir, exist_ok=True)
    safe = re.sub(r'[^\w \-]', '', title).strip()
    for name, x in out.items():
        if a.only and a.only.lower() != name.lower():
            continue
        f = os.path.join(outdir, f'{safe} - {name}.wav')
        R.write_wav(f, x)
        log(f'  wrote {f}')
    log('done in %.0fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
