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
  --voice           a recording of 15-30 seconds of someone singing alone: the singers are given that
                    voice's sound (several recordings, with commas, are shared out among them).  Needs
                    the optional voice model - docs/how-it-works.md - and takes about half as long as
                    all the singing lasts.  Use your own voice, or one whose owner has agreed
  --language        latin, when a scanned score's words are Latin (English is assumed otherwise)
  --only            write just one version, e.g. --only "Baritone predominant"

What was estimated for the piece is saved beside the score as NAME.preset.json and reused.
"""
import argparse, json, os, re, subprocess, sys, time
import numpy as np
from . import render as R, score as scoremod, presets, reference, voice

PARTS = {'tenor1': 'T1', 't1': 'T1', 'tenor2': 'T2', 't2': 'T2', 'baritone': 'BR', 'br': 'BR', 'bari': 'BR', 'bass': 'BS', 'bs': 'BS', 'solo': 'SOLO',
         'trio1': 'TR1', 'trio2': 'TR2', 'trio3': 'TR3'}


STAMP = re.compile(r'^// read from the PDF by reader (\w+), text (\w+)')


def _digest(data):
    import hashlib
    return hashlib.sha1(data if isinstance(data, bytes) else data.encode()).hexdigest()[:10]


def _stamp(out, reader):
    """Sign a score the program has just read, so that a later run can tell whether anyone has corrected it since."""
    text = open(out).read().rstrip('\n') + '\n'
    open(out, 'w').write(text + f'// read from the PDF by reader {reader}, text {_digest(text)} - correct anything here: a corrected score is kept as it is\n')


def read_music(path, log, language=None, again=False):
    """A .score file as it is; a PDF through the reader that suits it: tools/pdf2score.py when the notes are
    drawn as shapes (exported from notation software), tools/scan2score.py when the pages are pictures.
    A score read from the PDF earlier is used again - unless nobody has touched it and the reader has changed
    since (or `again` asks for it): a reading that could now be better is not kept out of habit."""
    if not path.lower().endswith('.pdf'):
        return path
    out = os.path.splitext(path)[0] + '.score'
    tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')
    reader = _digest(b''.join(open(os.path.join(tools, f), 'rb').read() for f in ('scan2score.py', 'vector2score.py', 'pdf2score.py')))
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
        text = open(out).read()
        body, _, last = text.rstrip('\n').rpartition('\n')
        m = STAMP.match(last)
        untouched = bool(m) and _digest(body + '\n') == m.group(2)
        if again and (untouched or not m):
            log(f'reading the PDF again, as asked ({out} is replaced)')
        elif again:
            log(f'{out} has been corrected by hand since it was read: kept (delete it to read the PDF again)'); return out
        elif untouched and m.group(1) != reader:
            log(f'the reader has changed since {out} was read, and nobody has edited that score: reading the PDF again')
        else:
            log(f'using {out}, read from this PDF earlier (delete it, or say --reread, to read the PDF again)')
            return out
    import pymupdf
    doc = pymupdf.open(path)
    drawn = sum(len(p.get_drawings()) for p in doc) / max(len(doc), 1)
    fonts = {f[3] for p in doc for f in p.get_fonts()}
    if drawn > 200 and any('Maestro' in f for f in fonts):      # an older Finale export
        # first the reader that takes the notes off the symbols and checks that its measures add up ...
        r = subprocess.run([sys.executable, os.path.join(tools, 'scan2score.py'), path, out, '--exact-only'] + (['--language', language] if language else []))
        if r.returncode == 0 and os.path.exists(out):
            log(f'read {path} -> {out}  (check it: a misread note or word is easier to fix there than to hear)')
            _stamp(out, reader)
            return out
        # ... then the older one made for this font, which guesses more
        r = subprocess.run([sys.executable, os.path.join(tools, 'pdf2score.py'), path, out], capture_output=True, text=True)
        sung = 0
        if r.returncode == 0 and os.path.exists(out):
            try:
                sung = sum(len(v) for v in scoremod.load(out).parts.values())
            except Exception:
                sung = 0
        if sung >= 8:
            log(r.stdout.strip()); log(f'read {path} -> {out}')
            _stamp(out, reader)
            return out
        if os.path.exists(out):
            os.remove(out)
    # Everything else goes to one reader, which reads the notes exactly where the PDF is drawn with a standard music
    # font, and otherwise recognizes them from the page images (about half a minute a page).
    log('reading the music from this PDF...')
    r = subprocess.run([sys.executable, os.path.join(tools, 'scan2score.py'), path, out] + (['--language', language] if language else []))
    if r.returncode or not os.path.exists(out):
        raise SystemExit('Could not read the music out of this PDF.')
    log(f'read {path} -> {out}  (check it: a misread note or word is easier to fix there than to hear)')
    _stamp(out, reader)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('music'); ap.add_argument('--out'); ap.add_argument('--part')
    ap.add_argument('--accompaniment'); ap.add_argument('--balanced'); ap.add_argument('--predominant'); ap.add_argument('--muted')
    ap.add_argument('--tune', action='store_true'); ap.add_argument('--only'); ap.add_argument('--singers', type=int)
    ap.add_argument('--preset', help='a preset file to use instead of NAME.preset.json')
    ap.add_argument('--language', help='the language of the words when a scan is read (latin, or leave out for English)')
    ap.add_argument('--fresh', action='store_true', help='ignore a saved preset and estimate again')
    ap.add_argument('--voice', help='recording(s) of a real voice for the singers to sound like')
    ap.add_argument('--reread', action='store_true', help='read the PDF again even if a score read from it earlier is there (one corrected by hand is kept)')
    a = ap.parse_args()
    log = lambda *s: print(*s, flush=True)
    t0 = time.time()
    path = read_music(a.music, log, a.language, a.reread)
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
    usual = dict(P)                                # what the program would choose for this score with nothing else to go on
    log(f"the quick syllables last {P['quick_syllable']}s: starting from leaders' mics {P['spot']}, hall {P['hall']}")
    saved = json.load(open(pfile)) if os.path.exists(pfile) and not a.fresh else {}
    if saved.get('backing') == .22 and 'timing' not in saved:      # (an earlier version saved its own defaults: this one was never measured)
        saved.pop('backing')
    P.update(saved)
    if a.singers:
        P['singers'] = a.singers
    L = lambda f: reference.load_audio(f) if f else None
    track = L(a.accompaniment)
    ref_voices = real_voice = None
    if a.balanced and a.predominant and not a.accompaniment:          # unaccompanied music: voices only
        preds = [L(f) for f in a.predominant.split(',') if f]
        est, iso = presets.from_voice_tracks(sc, [g[1][-1] for g in groups][:len(preds)] or ['BR'], L(a.balanced), preds, log)
        P.update(est)
        ref_voices = L(a.balanced)
        real_voice = next(((p, x, R.SR // 2) for p, x in iso.items()), None)       # one real singer alone, to compare with
    elif a.balanced and (a.accompaniment or a.muted or a.predominant):
        if not a.accompaniment:
            raise SystemExit('to learn from practice tracks I also need the accompaniment-only track (--accompaniment)')
        preds = [L(f) for f in (a.predominant or '').split(',') if f]
        more = {g[1][-1]: x for g, x in zip(groups[1:], preds[1:])}
        est, iso = presets.from_recordings(sc, part or 'BR', L(a.balanced), track, preds[0] if preds else None, L(a.muted), log, more)
        P.update(est)
        ref_voices = iso['voices'] if iso['clean'] >= 15 else None
        if iso['clean'] >= 15 and 'part' in iso:
            real_voice = (part or 'BR', iso['part'].mean(1), R.SR)
    elif track is not None and 'timing' not in P and not sc.timing:
        from . import timing
        P['timing'] = timing.from_accompaniment(sc, track.mean(1), R.SR, log)

    # ---- sing
    clock = R.clock_for(sc, P.get('timing'), absolute=track is not None)
    total = float(np.interp(sc.beats, *clock)) + 4.0
    if track is not None:
        total = max(total, len(track) / R.SR)
    voices = [v for v in (a.voice or '').split(',') if v]
    for v in voices:
        if not os.path.exists(v):
            raise SystemExit(f'--voice: there is no file {v}')
    if voices:
        from . import revoice
        if revoice.command() is None:
            raise SystemExit('--voice needs the optional voice model, which is not set up here: see docs/how-it-works.md, "A real voice\'s sound".')
    stems = R.sing(sc, (*clock, total), P['singers'], log, tune=R.tune_of(P), voices=voices or None)
    if ref_voices is not None and ('hall_from' not in saved or a.fresh):
        got = presets.match_hall(stems, P, ref_voices, log)
        P.update(got, **({'hall_from': 'recording'} if got else {}))
    if a.tune:
        P.update(presets.tune_for_words(stems, sc, clock, P, keep_hall=P.get('hall_from') == 'recording', log=log))
    # only what was measured or chosen for this piece is kept: a default that improves later should reach it
    json.dump({k: v for k, v in P.items() if k not in usual or usual[k] != v}, open(pfile, 'w'), indent=1)
    log(f"preset: leaders' mics {P['spot']}, hall {P['hall']} ({P['hall_rt']}s), accompaniment {P['backing']}, note decay {P.get('note_decay', 0.)}, swell {P.get('swell', 'by rule')}  -> {pfile}")

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
    if real_voice is not None and P.get('timing'):      # a real singer was isolated: say where the simulated one differs
        from . import compare
        rp, rx, rsr = real_voice
        c = compare.run(sc, rp, rx, rsr, P['timing'], settings=R.tune_of(P))
        if 'tone' in c['diff']:
            f = os.path.join(outdir, f'{safe} - compared with the real {R.NAMES.get(rp, rp).lower()}.txt')
            open(f, 'w').write(compare.report(c, f'the real {R.NAMES.get(rp, rp).lower()}', top=12) + '\n')
            log(f'compared with the real {R.NAMES.get(rp, rp).lower()} (spectra, note by note; model minus real):')
            for _, text in compare.findings(c['diff'], c['real'], c['model'])[:5]:
                log('   ' + text)
            log(f'  wrote {f}')
    log('done in %.0fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
