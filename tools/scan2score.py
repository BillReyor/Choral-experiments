"""Read a scanned (or photographed) vocal score into the score format.

    python tools/scan2score.py SCAN.pdf OUT.score [--work DIR] [--tempo 100] [--title T] [--language latin]

A scan is a picture, so the notes have to be recognized.  That is done by `homr`, an open-source
optical music recognition engine, installed separately (see README); this tool does everything
around it: it cuts every page into systems, has each system read staff by staff, decides which
staves are voices and which are the piano, splits two voices sharing a staff into their parts,
and takes the words from the page by text recognition.  The result is an ordinary score file -
check it, and where practice tracks exist let tools/check_part.py check it against them.
"""
import argparse, json, os, re, shutil, subprocess, sys, xml.etree.ElementTree as ET
from fractions import Fraction
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def homr_cmd():
    for c in (os.environ.get('HOMR'), os.path.join(HERE, '.venv-omr', 'bin', 'homr'), shutil.which('homr')):
        if c and os.path.exists(c):
            return [c]
    if shutil.which('uvx'):
        return ['uvx', '--from', 'homr[cpu]', 'homr']
    raise SystemExit('This is a scan, and reading scans needs the music-recognition engine "homr".  Install it with\n'
                     '    python3.12 -m venv .venv-omr && .venv-omr/bin/pip install "homr[cpu]"\n'
                     'in the project folder (or set HOMR to its path), then run this again.')


def run_homr(images, flags=()):
    """One homr process per image, three at a time: a page it cannot read (a cover) must not stop the rest."""
    from concurrent.futures import ThreadPoolExecutor
    cmd = homr_cmd()
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(lambda im: subprocess.run(cmd + list(flags) + [im], capture_output=True), images))


# ----------------------------------------------------------------- pages, staves, systems ----
def render_pages(pdf, work, zoom=2.6):
    import pymupdf
    out = []
    for i, page in enumerate(pymupdf.open(pdf)):
        path = os.path.join(work, 'p%02d.png' % (i + 1))
        if not os.path.exists(path):
            page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY).save(path)
        out.append(path)
    return out


def staves_in(img, box):
    """The five-line staves inside one of homr's boxes (x0, y0, x1, y1 in pixels) -> [(top, bottom)]."""
    x0, y0, x1, y1 = box
    pad = int(.012 * img.shape[0])
    y0, y1 = max(0, y0 - pad), min(img.shape[0], y1 + pad)
    w = x1 - x0
    dark = (img[y0:y1, x0 + int(.44 * w):x0 + int(.56 * w)] < 150).mean(1)       # a narrow strip: scans are never level
    rows = np.where(dark > .6)[0]
    lines = []
    for r in rows:
        if lines and r - lines[-1][-1] <= 2:
            lines[-1].append(r)
        else:
            lines.append([r])
    ys = [float(np.mean(l)) for l in lines]
    out, i = [], 0
    while i + 4 < len(ys):
        d = np.diff(ys[i:i + 5])
        if d.max() < .012 * img.shape[0] and d.min() > 3 and d.max() - d.min() < max(3, .35 * d.mean()):
            out.append((y0 + ys[i], y0 + ys[i + 4])); i += 5
        else:
            i += 1
    return out


def page_staves(img, txt):
    """homr's staff boxes for a page -> every staff as (top, bottom, x0, x1), top to bottom."""
    H, W = img.shape
    staves = []
    for line in open(txt):
        f = line.split()
        if len(f) < 5:
            continue
        label, xc, yc, w, h = int(f[0]), *map(float, f[1:5])
        x0, x1 = int((xc - w / 2) * W), int((xc + w / 2) * W)
        y0, y1 = int((yc - h / 2) * H), int((yc + h / 2) * H)
        found = staves_in(img, (x0, y0, x1, y1))
        want = 2 if label == 1 else 1
        if len(found) != want:                       # fall back on the box itself
            unit = (y1 - y0) / (1 if want == 1 else 3.2)
            found = [(y0, y1)] if want == 1 else [(y0, y0 + unit), (y1 - unit, y1)]
        staves += [(a, b, x0, x1) for a, b in found]
    return sorted(staves)


def group_systems(img, staves):
    """Staves joined at their left end by one unbroken vertical line belong to one system."""
    groups = [[staves[0]]] if staves else []
    for prev, cur in zip(staves, staves[1:]):
        gap0, gap1 = int(prev[1]) + 2, int(cur[0]) - 2
        x = int(min(prev[2], cur[2]))
        dark = img[gap0:gap1, max(0, x - 42):x + 42] < 140
        near = dark[:, :-4] | dark[:, 1:-3] | dark[:, 2:-2] | dark[:, 3:-1] | dark[:, 4:]     # the line may lean a pixel or two
        joined = gap1 > gap0 and near.mean(0).max() > .6       # measured: 0.73-1.00 within a system, under 0.4 between
        if joined:
            groups[-1].append(cur)
        else:
            groups.append([cur])
    return groups


def cut_systems(pages, work, log):
    """Pass 1: where are the staves?  Then one image per system, with every staff declared on its own."""
    need = [p for p in pages if not os.path.exists(p[:-4] + '.txt')]
    if need:
        log(f'finding the staves on {len(need)} page(s)...')
        run_homr(need, ['--write-staff-positions'])
    crops = []
    for pi, p in enumerate(pages, 1):
        txt = p[:-4] + '.txt'
        if not os.path.exists(txt) or not open(txt).read().strip():
            continue                                  # a page with no music (cover, notes)
        img = np.asarray(Image.open(p).convert('L'))
        H, W = img.shape
        groups = group_systems(img, page_staves(img, txt))
        bounds = [(g[0][0], g[-1][1]) for g in groups]
        for si, g in enumerate(groups, 1):
            unit = np.mean([b - a for a, b, _, _ in g])
            top = max(0 if si == 1 else (bounds[si - 2][1] + g[0][0]) / 2, g[0][0] - 3.5 * unit)
            bot = min(H if si == len(groups) else (g[-1][1] + bounds[si][0]) / 2, g[-1][1] + 3.5 * unit)
            name = os.path.join(work, 'p%02d_s%d' % (pi, si))
            if not os.path.exists(name + '.png'):       # the page with everything but this system blanked out:
                only = np.full_like(img, 255)           # the reader then sees one system at its normal size
                only[int(top):int(bot)] = img[int(top):int(bot)]
                Image.fromarray(only).save(name + '.png')
            crops.append(dict(name=name, page=pi, system=si, staves=[(a, b) for a, b, _, _ in g], top=int(top), bot=int(bot),
                              x0=min(s[2] for s in g), x1=max(s[3] for s in g)))
    return crops


# ------------------------------------------------------------------- reading the notes ----
QL = {'whole': 4, 'half': 2, 'quarter': 1, 'eighth': Fraction(1, 2), '16th': Fraction(1, 4), '32nd': Fraction(1, 8)}
SPELL = [(Fraction(4), 'w'), (Fraction(3), 'h.'), (Fraction(2), 'h'), (Fraction(3, 2), 'q.'), (Fraction(1), 'q'), (Fraction(3, 4), 'e.'),
         (Fraction(1, 2), 'e'), (Fraction(3, 8), 's.'), (Fraction(1, 4), 's'), (Fraction(1, 8), 't')]
TRIP = {Fraction(4, 3): 'h3', Fraction(2, 3): 'q3', Fraction(1, 3): 'e3', Fraction(1, 6): 's3'}


def spell(ql):
    """A length in quarter notes -> the note values that add up to it (tied together when more than one)."""
    if ql in TRIP:
        return [TRIP[ql]]
    out = []
    for v, c in SPELL:
        while ql >= v:
            out.append(c); ql -= v
    return out


def name_of(step, alter, octave):
    return step.lower() + {1: '#', -1: 'b', 2: '##', -2: 'bb'}.get(alter, 'n') + str(octave)


def read_xml(path):
    """homr's MusicXML for one system -> staves, top to bottom: each {'clef': 'G'|'F', 'measures': [...]}.
    A measure is {'len': quarter notes or None, 'time': 'n/d' or None, 'notes': [note, ...]}; a note is a dict
    with on, ql (quarter notes), midi (None for a rest), name, tie, slur, voice."""
    root = ET.parse(path).getroot()
    segments = {}                                   # segment number -> staves, in page order
    for part in root.findall('part'):
        nst = int(part.findtext('measure/attributes/staves') or 1)
        mine = [dict(clef=None, measures=[]) for _ in range(nst)]
        div, seg = 1, 0
        for m in part.findall('measure'):
            pr = m.find('print')
            if pr is not None and pr.get('new-system') == 'yes' and mine[0]['measures']:
                segments.setdefault(seg, []).extend(mine); seg += 1      # two staves of a choir read as a new system
                mine = [dict(clef=None, measures=[]) for _ in range(nst)]
            cur = Fraction(0); last_on = Fraction(0)
            per = [dict(len=None, time=None, notes=[]) for _ in range(nst)]
            for e in m:
                if e.tag == 'attributes':
                    if e.findtext('divisions'):
                        div = int(e.findtext('divisions'))
                    if e.find('time') is not None:
                        for x in per:
                            x['time'] = e.findtext('time/beats') + '/' + e.findtext('time/beat-type')
                    for c in e.findall('clef'):
                        k = int(c.get('number') or 1) - 1
                        if k < nst and mine[k]['clef'] is None:
                            mine[k]['clef'] = c.findtext('sign')
                elif e.tag == 'backup':
                    cur -= Fraction(int(e.findtext('duration')), div)
                elif e.tag == 'forward':
                    cur += Fraction(int(e.findtext('duration')), div)
                elif e.tag == 'note':
                    if e.find('grace') is not None:
                        continue
                    ql = Fraction(int(e.findtext('duration') or 0), div)
                    chord = e.find('chord') is not None
                    on = last_on if chord else cur
                    k = min(int(e.findtext('staff') or 1) - 1, nst - 1)
                    if e.find('rest') is not None:
                        if e.findtext('type') is None:           # a whole bar of rest
                            ql = Fraction(0)
                        midi = name = None
                    else:
                        step, alter, octv = e.findtext('pitch/step'), int(float(e.findtext('pitch/alter') or 0)), int(e.findtext('pitch/octave'))
                        midi = 12 * (octv + 1) + 'C D EF G A B'.index(step) + alter
                        name = name_of(step, alter, octv)
                    if midi is not None or ql:
                        per[k]['notes'].append(dict(on=on, ql=ql, midi=midi, name=name, voice=e.findtext('voice') or '1', chord=chord,
                                                    tie=any(t.get('type') == 'start' for t in e.findall('tie')),
                                                    slur=[x.get('type') for x in e.iter('slur')]))
                    if not chord:
                        last_on = cur; cur += ql
            dyn = m.find('direction/direction-type/dynamics')
            if dyn is not None and len(dyn):
                per[0]['dyn'] = dyn[0].tag
            for k in range(nst):
                mine[k]['measures'].append(per[k])
        segments.setdefault(seg, []).extend(mine)
    return [st for k in sorted(segments) for st in segments[k]]


def layout(notes, length):
    """Put each voice's notes one after another.  The reader's own positions are kept when they fit the
    bar; a voice that would run past the barline is moved back so that it ends on it (two voices
    sharing one notehead at the start of the bar is the usual cause), and a last note that stops a
    dot short of the barline gets its dot back."""
    for v in {n['voice'] for n in notes}:
        mine = [n for n in notes if n['voice'] == v]
        runs, total = [], Fraction(0)
        for n in mine:
            if n['chord'] and runs:
                runs[-1].append(n)
            else:
                runs.append([n]); total += n['ql']
        start = mine[0]['on']
        if start + total > length:
            start = max(Fraction(0), length - total)
        cur = start
        for r in runs:
            for n in r:
                n['on'] = cur
            cur += r[0]['ql']
        if runs and runs[-1][0]['midi'] is not None and length - cur == runs[-1][0]['ql'] / 2:
            for n in runs[-1]:
                n['ql'] = n['ql'] * 3 / 2
    return notes


def lines_of(notes, length):
    """The notes sounding on one staff in one measure -> (upper line, lower line): each a list of
    (name or None, quarter-length, tied-on, is_start) covering the whole measure."""
    notes = layout(notes, length)
    pts = sorted({Fraction(0), length} | {n['on'] for n in notes} | {n['on'] + n['ql'] for n in notes})
    pts = [p for p in pts if 0 <= p <= length]
    out = []
    for pick in (max, min):
        line = []
        for a, b in zip(pts, pts[1:]):
            live = [n for n in notes if n['midi'] is not None and n['on'] <= a < n['on'] + n['ql']]
            n = None
            if live:
                best = pick(x['midi'] for x in live)
                same = [x for x in live if x['midi'] == best]
                n = line[-1][0] if line and any(line[-1][0] is x for x in same) else max(same, key=lambda x: x['on'] + x['ql'])
            if line and line[-1][0] is n:
                line[-1][2] = b
            else:
                line.append([n, a, b])
        out.append(line)
    return out


def tokens(line, syl=None, up=0):
    """One line of a measure -> score tokens.  syl maps id(note) -> its syllable; up shifts the written octave."""
    toks = []
    for n, a, b in line:
        parts = spell(b - a)
        if n is None:
            toks += ['r/' + c for c in parts]
            continue
        whole = (b == n['on'] + n['ql'])
        name = n['name'][:-1] + str(int(n['name'][-1]) + up)
        for i, c in enumerate(parts):
            t = f"{name}/{c}" + ('~' if i + 1 < len(parts) or (whole and n['tie']) else '')
            if syl is not None and i == 0 and a == n['on'] and id(n) in syl:
                t += '=' + syl[id(n)]
            toks.append(t)
    return toks


def mark_melisma(measures):
    """Along one staff: a note reached by a tie is no new syllable; a note inside a slur continues the last one."""
    tied, depth = set(), {}
    for m in measures:
        for n in sorted([x for x in m['notes'] if x['midi'] is not None], key=lambda x: (x['on'], -x['midi'])):
            v = n['voice']
            if (v, n['midi']) in tied:
                n['tied_from'] = True; tied.discard((v, n['midi']))
            if depth.get(v, 0) > 0:
                n['melisma'] = True
            depth[v] = max(0, depth.get(v, 0) + n['slur'].count('start') - n['slur'].count('stop'))
            if n['tie']:
                tied.add((v, n['midi']))


def piano_lines(notes, length, hand):
    """Piano staff: one line per voice, chords joined, gaps filled with rests; a voice that does not add up is dropped."""
    out = []
    for vi, v in enumerate(sorted({n['voice'] for n in notes if n['midi'] is not None})):
        mine = sorted([n for n in notes if n['voice'] == v and n['midi'] is not None], key=lambda n: n['on'])
        toks, cur, ok = [], Fraction(0), True
        groups = {}
        for n in mine:
            groups.setdefault(n['on'], []).append(n)
        for on in sorted(groups):
            g = groups[on]
            if on < cur:
                ok = False; break
            toks += ['r/' + c for c in spell(on - cur)]
            ql = min(n['ql'] for n in g)
            ps = spell(ql)
            if not ps:
                ok = False; break
            for i, c in enumerate(ps):
                toks.append('+'.join(n['name'] for n in sorted(g, key=lambda n: n['midi'])) + '/' + c + ('~' if i + 1 < len(ps) or all(n['tie'] for n in g) else ''))
            cur = on + ql
        if ok and cur <= length:
            toks += ['r/' + c for c in spell(length - cur)]
            out.append((hand + ('' if vi == 0 else str(vi + 1)), toks))
        if vi == 2:
            break
    return out


def read_systems(crops, log):
    """Pass 2: every system read on its own.  -> crops, each with 'read': its staves top to bottom."""
    need = [c['name'] + '.png' for c in crops if not os.path.exists(c['name'] + '.musicxml')]
    if need:
        log(f'reading {len(need)} system(s)...')
        run_homr(need)
    for c in crops:
        c['read'] = read_xml(c['name'] + '.musicxml') if os.path.exists(c['name'] + '.musicxml') else []
        if len(c['read']) != len(c['staves']):
            log(f"  ! page {c['page']} system {c['system']}: {len(c['staves'])} staves on the page but {len(c['read'])} were read")
    return crops


# ------------------------------------------------------------------------- the words ----
def ocr_cmd(work):
    """macOS text recognition, compiled once from tools/ocr.swift."""
    exe = os.path.join(work, 'ocr')
    if not os.path.exists(exe):
        src = os.path.join(HERE, 'tools', 'ocr.swift')
        if not shutil.which('swiftc') or subprocess.run(['swiftc', '-O', src, '-o', exe], capture_output=True).returncode:
            return None
    return exe


def ocr_words(exe, img, y0, y1, work, tag, zoom=3):
    """Words between two heights of a page, read at three times the size (small print needs it; hyphens too).
    -> [(x centre, y centre, x0, x1, text)] in page pixels."""
    band = Image.fromarray(img[int(y0):int(y1)])
    band = band.resize((band.size[0] * zoom, band.size[1] * zoom), Image.LANCZOS)
    canvas = Image.new('L', (band.size[0], band.size[1] + 240), 255)
    canvas.paste(band, (0, 120))
    path = os.path.join(work, f'band_{tag}.png')
    canvas.save(path)
    out = []
    for line in subprocess.run([exe, path], capture_output=True, text=True).stdout.splitlines():
        box, _, text = line.partition('\t')
        f = [float(v) for v in box.split()]
        if len(f) == 4 and text.strip():
            x0, x1 = f[0] * canvas.size[0] / zoom, f[2] * canvas.size[0] / zoom
            yc = ((f[1] + f[3]) / 2 * canvas.size[1] - 120) / zoom + y0
            out.append(((x0 + x1) / 2, yc, x0, x1, text.strip()))
    os.remove(path)
    return out


NOT_LYRICS = re.compile(r'^(unis\.?|div\.?|cresc\.?|dim\.?|rit\.?|poco|tempo|pp|mp|mf|ff|sim\.?|[0-9]+)$', re.I)


def clean_word(t):
    import unicodedata
    t = ''.join(ch for ch in unicodedata.normalize('NFKD', t) if not unicodedata.combining(ch))
    t = re.sub(r"[_—–\"“”‘`]+", '', t).replace('’', "'")
    core = re.sub(r"[^A-Za-z]", '', t)
    odd = core[1:] != core[1:].lower() and not core.isupper()          # "uS", "nIght"
    return t.lower() if odd or (t.isupper() and len(core) <= 3 and core not in ('I', 'O')) else t


def syllables(words, unit, img=None):
    """Recognized words under a staff -> text lines (top first), each [(x, syllable)]; a syllable that is not
    the end of its word keeps its hyphen.  Hyphens are looked for on the page itself: a small dash at
    mid-letter height between two words (text recognition drops most of them)."""
    words = [w[:4] + (clean_word(w[4]),) for w in words if '(' not in w[4] and ')' not in w[4]]
    words = [w for w in words if not NOT_LYRICS.match(w[4]) and re.search(r"[aeiouyAEIOUY]", w[4])
             and (len(w[4].strip(".,;:!?'-")) > 1 or w[4].strip(".,;:!?'-") in ('a', 'A', 'I', 'O'))]
    if not words:
        return []
    rows = []
    for w in sorted(words, key=lambda w: w[1]):
        if rows and w[1] - np.mean([v[1] for v in rows[-1]]) < 1.2 * unit:
            rows[-1].append(w)
        else:
            rows.append([w])
    out = []
    for r in rows[:2]:
        r = sorted(r, key=lambda w: w[2])
        yc = float(np.median([w[1] for w in r]))
        line = []
        for i, (xc, _, x0, x1, text) in enumerate(r):
            bits = [b for b in re.split(r'(?<=-)', text) if b.strip('-')]
            for k, b in enumerate(bits):
                line.append([x0 + (x1 - x0) * (k + .5) / len(bits), b])
            if img is not None and i + 1 < len(r) and not line[-1][1].endswith('-'):
                g0, g1 = int(x1) + 2, int(r[i + 1][2]) - 2
                if g1 - g0 >= 4:
                    patch = img[int(yc - .45 * unit):int(yc + .3 * unit), g0:g1] < 140
                    cols = patch.any(0)
                    runs = np.diff(np.flatnonzero(np.diff(np.r_[0, cols, 0])))[::2]
                    tall = patch.sum(0).max() if patch.size else 0
                    if len(runs) and 2 <= runs.max() <= 1.2 * unit and tall <= .45 * unit and not re.search(r"[.,;:!?]$", line[-1][1]):
                        line[-1][1] += '-'
        out.append([(x, t) for x, t in line])
    return out


def _tilt(img, top, unit, x0, x1):
    """How much the staff's top line rises or falls across the page (pixels per pixel)."""
    def top_at(x):
        lo, hi = int(top - 1.5 * unit), int(top + 1.5 * unit)
        strip = (img[lo:hi, max(x0, x - 30):min(x1, x + 30)] < 150).mean(1)
        return lo + int(np.argmax(strip)) if strip.max() > .5 else top
    return (top_at(x1 - (x1 - x0) // 8) - top_at(x0 + (x1 - x0) // 8)) / (.75 * (x1 - x0))


def _columns(img, top, bot, x0, x1, slope):
    """Columns where a thin vertical line runs unbroken from `top` to `bot` (heights at mid-page)."""
    mid, cols = (x0 + x1) // 2, []
    for x in range(x0, x1):
        d = (x - mid) * slope
        seg = img[int(top + d):int(bot + d), max(0, x - 1):x + 2] < 150
        if len(seg) and seg.any(1).mean() > .96:
            cols.append(x)
    xs, run = [], []
    for c in cols + [10 ** 9]:
        if run and c - run[-1] > 3:
            xs.append((float(np.mean(run)), len(run))); run = []
        run.append(c)
    return xs


def barlines(img, staves, x0, x1, piano):
    """The measure boundaries of one system, left and right edge included.  A barline is a thin vertical line;
    what tells it from a note stem is that it stands at the same place on every staff - and through the
    piano's two staves it runs unbroken, gap included, which no stem does."""
    x0, x1 = int(x0), int(x1)
    unit = float(np.mean([(b - a) / 4 for a, b in staves]))
    slope = _tilt(img, staves[0][0], unit, x0, x1)
    if piano and len(staves) >= 2:
        found = _columns(img, staves[-2][0] + .3 * unit, staves[-1][1] - .3 * unit, x0, x1, slope)
        xs = [x for x, w in found if w <= 1.2 * unit]
    else:
        per = [[x for x, w in _columns(img, a + .25 * unit, b - .25 * unit, x0, x1, slope) if w <= 1.2 * unit] for a, b in staves]
        xs = [x for x in per[0] if all(any(abs(x - y) < .7 * unit for y in other) for other in per[1:])] if len(per) > 1 else per[0]
    inner = []
    for x in xs:
        if x - x0 < 2.5 * unit or x1 - x < 1.5 * unit:
            continue
        if inner and x - inner[-1] < 1.5 * unit:      # a double bar is one barline
            inner[-1] = x
        else:
            inner.append(x)
    return [float(x0)] + inner + [float(x1)]


def place(slots, syls):
    """Give syllables to note slots, both in left-to-right order, so that they sit closest together.
    slots: [(x, note)], syls: [(x, text)] -> {id(note): text}; unmatched notes continue the previous vowel."""
    n, k = len(slots), len(syls)
    if not n:
        return {}
    if k >= n:
        return {id(slots[i][1]): syls[i][1] for i in range(n)}
    cost = np.full((k + 1, n + 1), np.inf); cost[0, :] = 0
    for i in range(1, k + 1):
        for j in range(i, n - (k - i) + 1):
            cost[i, j] = min(cost[i, j - 1], cost[i - 1, j - 1] + abs(slots[j - 1][0] - syls[i - 1][0]))
    out, i, j = {}, k, n
    while i > 0:
        if j > i and cost[i, j] == cost[i, j - 1]:
            j -= 1
        else:
            out[id(slots[j - 1][1])] = syls[i - 1][1]; i -= 1; j -= 1
    for x, note in slots:
        out.setdefault(id(note), '_')
    return out


# ------------------------------------------------------------------- putting it together ----
def roles_for(crops):
    """Which staff of each system is what.  The two lowest staves are the piano whenever the piece has systems
    of three or more staves; above them: one staff = a soloist (if the piece has solo-plus-choir systems
    nearby) or the whole choir, two = tenors and basses, three = solo + tenors + basses, four = one per part."""
    counts = [len(c['read']) for c in crops]
    piano = max(counts, default=0) >= 3
    voc = [(n - 2 if piano and n >= 2 else n) for n in counts]
    for i, c in enumerate(crops):
        k = voc[i]
        if k == 1:
            near = next((v for v in voc[i + 1:] if v >= 2), None) or next((v for v in reversed(voc[:i]) if v >= 2), None)
            c['roles'] = ['SOLO' if near == 3 else 'ALL']
        else:
            c['roles'] = {0: [], 2: ['TEN', 'LOW'], 3: ['SOLO', 'TEN', 'LOW'], 4: ['T1', 'T2', 'BR', 'BS']}.get(k, ['TEN', 'LOW'] + ['?'] * (k - 2))
        c['roles'] += ['RH', 'LH'] if piano and counts[i] >= 2 else []


def assemble(crops, pages, work, title, tempo, language, log, marked=False):
    exe = ocr_cmd(work)
    if not exe:
        log('  ! no text recognition here (it uses macOS): the notes will have no words')
    roles_for(crops)
    out, num, cur_time, length = [], 0, None, Fraction(4)
    imgs = {}
    def read_texts(c, img, M):
        texts = {}
        for si, role in enumerate(c['roles'][:len(c['read'])]):
            if role in ('RH', 'LH') or not exe or si >= len(c['staves']):
                continue
            top, bot = c['staves'][si]
            unit = (bot - top) / 4
            nxt = c['staves'][si + 1][0] if si + 1 < len(c['staves']) else c['bot']
            tag = f"{c['page']}_{c['system']}_{si}"
            loose = ocr_words(exe, img, bot + .6 * unit, min(nxt - 1.2 * unit, bot + 9 * unit), work, tag)
            loose = [w for w in loose if re.search('[A-Za-z]', w[4]) and '(' not in w[4] and not NOT_LYRICS.match(w[4])]
            ys = []
            for w in sorted(loose, key=lambda w: w[1]):
                if not any(abs(w[1] - y) < 1.2 * unit for y in ys):
                    ys.append(float(np.median([v[1] for v in loose if abs(v[1] - w[1]) < 1.2 * unit])))
            words = []
            for yc in ys:                # each line of text read again by itself, close up: that brings out the
                half = min([1.3 * unit] + [.5 * abs(yc - y) for y in ys if y != yc])      # small syllables
                tight = [w for w in ocr_words(exe, img, yc - half, yc + half, work, tag, zoom=4) if re.search('[aeiouyAEIOUY]', w[4])]
                row = [w for w in loose if abs(w[1] - yc) < 1.2 * unit]
                words += [w[:1] + (yc,) + w[2:] for w in tight]
                words += [w for w in row if not any(w[2] < t[3] and t[2] < w[3] for t in tight)]   # what only the first look saw
            if 'bars' not in c:
                c['bars'] = barlines(img, c['staves'], c['x0'], c['x1'], 'RH' in c['roles'])
                if len(c['bars']) != M + 1:
                    log(f"  ? page {c['page']} system {c['system']}: found {len(c['bars']) - 1} measures on the page but {M} were read; words placed by even spacing")
                    c['bars'] = list(np.linspace(c['x0'], c['x1'], M + 1))
            bars = c['bars']
            texts[si] = (syllables(words, unit, img), bars, unit, sorted(ys))
        return texts

    for c in crops:                                 # first the words of the whole piece ...
        if c['read']:
            counts = [len(st['measures']) for st in c['read']]
            img = imgs.setdefault(c['page'], np.asarray(Image.open(pages[c['page'] - 1]).convert('L')))
            c['texts'] = read_texts(c, img, max(set(counts), key=counts.count))
    # ... so that the words can be checked against each other before any note gets one.
    key = lambda t: re.sub(r"[^a-z']", '', t.lower())
    words_ok = None
    if not language or language == 'english':
        try:
            import cmudict
            words_ok = set(cmudict.dict())
        except Exception:
            words_ok = None
    seen, loose = {}, {}
    for c in crops:
        for si, (lines, bars, unit, ys) in list(c.get('texts', {}).items()):
            fixed = []
            for line in lines:
                line = [list(w) for w in line]
                if words_ok:                        # "save- us": two real words whose join is no word were never one word
                    i = 0
                    while i < len(line):
                        j = i
                        while j < len(line) - 1 and line[j][1].endswith('-'):
                            j += 1
                        if j > i:
                            parts = [key(w[1]) for w in line[i:j + 1]]
                            if ''.join(parts) not in words_ok and ''.join(parts).rstrip("'s") not in words_ok and all(p_ in words_ok for p_ in parts):
                                for w in line[i:j]:
                                    w[1] = w[1].rstrip('-')
                        i = j + 1
                run = []
                for x, t in line:
                    run.append(key(t))
                    if not t.endswith('-'):
                        if len(run) > 1 and all(run):
                            seen[tuple(run)] = seen.get(tuple(run), 0) + 1
                        run = []
                fixed.append(line)
            c['texts'][si] = (fixed, bars, unit, ys)
    for c in crops:                                 # a word seen several times with its hyphens lends them where they were missed
        for si, (lines, bars, unit, ys) in list(c.get('texts', {}).items()):
            for line in lines:
                for i in range(len(line)):
                    for word, h in seen.items():
                        n = len(word)
                        if h >= 2 and tuple(key(w[1]) for w in line[i:i + n]) == word and (not words_ok or ''.join(word) in words_ok):
                            for w in line[i:i + n - 1]:
                                if not w[1].endswith('-'):
                                    w[1] += '-'
            c['texts'][si] = ([[tuple(w) for w in line] for line in lines], bars, unit, ys)
    last = {}                                       # (role, voice) -> (line number in out, pitch) of the note that ended the previous bar
    for c in crops:
        if not c['read']:
            continue
        img = imgs.setdefault(c['page'], np.asarray(Image.open(pages[c['page'] - 1]).convert('L')))
        counts = [len(st['measures']) for st in c['read']]
        M = max(set(counts), key=counts.count)
        out.append(f"// page {c['page']}, system {c['system']}")
        texts = c.get('texts', {})
        for st in c['read']:
            mark_melisma(st['measures'])
        marks = {}
        if exe:                                      # tempo marks printed above the system: "= ca. 69", "Tempo I"
            top = c['staves'][0][0]; unit0 = (c['staves'][0][1] - top) / 4
            above = ocr_words(exe, img, max(c['top'], top - 9 * unit0), top - .3 * unit0, work, f"{c['page']}_{c['system']}_t", zoom=2)
            bars0 = barlines(img, c['staves'], c['x0'], c['x1'], 'RH' in c['roles'])
            bars0 = bars0 if len(bars0) == M + 1 else list(np.linspace(c['x0'], c['x1'], M + 1))
            line = ' '.join(w[4] for w in sorted(above, key=lambda w: w[2]))
            for mm in re.finditer(r'=\s*(?:ca\.?\s*)?(\d{2,3})', line):
                if 30 <= int(mm.group(1)) <= 240:
                    num_w = next((w for w in above if mm.group(1) in w[4]), None)
                    xw = min([w[2] for w in above if num_w and abs(w[1] - num_w[1]) < 1.5 * unit0 and num_w[2] - 32 * unit0 < w[2] <= num_w[2]] or [c['x0']])
                    marks[max(0, int(np.searchsorted(bars0, xw + 2 * unit0)) - 1)] = float(mm.group(1))
            if re.search(r'Tempo\s+I\b', line) and tempo:
                xw = next((w[2] for w in above if w[4].startswith('Tempo')), c['x0'])
                marks[max(0, int(np.searchsorted(bars0, xw)) - 1)] = float(tempo)
        for j in range(M):
            num += 1
            t = next((st['measures'][j]['time'] for st in c['read'] if j < len(st['measures']) and st['measures'][j]['time']), None)
            if t and t != cur_time:
                cur_time = t; length = Fraction(int(t.split('/')[0]) * 4, int(t.split('/')[1]))
                out.append('time: ' + t)
            if j in marks and (num > 1 or marks[j] != tempo):
                out.append(f'tempo: {marks[j]:g}')
            out.append(f'== {num}')
            for si, role in enumerate(c['roles'][:len(c['read'])]):
                st = c['read'][si]
                if j >= len(st['measures']):
                    continue
                notes = st['measures'][j]['notes']
                if not any(n['midi'] is not None for n in notes):
                    continue
                if role in ('RH', 'LH'):
                    out += [f'{name}: ' + ' '.join(toks) for name, toks in piano_lines(layout(notes, length), length, role)]
                    continue
                up, lo = lines_of(notes, length)
                syl = [None, None]
                if si in texts:
                    lines, bars, unit, ys = texts[si]
                    xa, xb = bars[j] + (5.5 * unit if j == 0 else .8 * unit), bars[j + 1] - .6 * unit
                    for v, line in enumerate((up, lo)):
                        if lines:           # a staff with no words under it sings the words of the staff that has them
                            starts = [n for n, a_, b_ in line if n is not None and a_ == n['on'] and not n.get('tied_from')]
                            slots = [(xa + float(n['on'] / length) * (xb - xa), n) for n in starts if not n.get('melisma')] or [(xa, n) for n in starts[:1]]
                            inbar = lambda w: bars[j] - .3 * unit <= w[0] < bars[j + 1] - .3 * unit
                            mine = [w for w in (lines[v] if v < len(lines) else lines[0] if lines else []) if inbar(w)]   # one line of words serves both voices
                            if len(mine) < len(slots) and v < len(ys) and exe:      # a syllable is missing: look at this bar alone, larger
                                half = min([1.3 * unit] + [.5 * abs(ys[v] - y) for y in ys if y != ys[v]])
                                x_a, x_b = int(bars[j] - .5 * unit), int(bars[j + 1])
                                again = ocr_words(exe, img[:, x_a:x_b], ys[v] - half, ys[v] + half, work, 'bar', zoom=5)
                                again = [(w[0] + x_a, w[1], w[2] + x_a, w[3] + x_a, w[4]) for w in again]
                                extra = syllables(again, unit, img)
                                if extra and len([w for w in extra[0] if inbar(w)]) > len(mine):
                                    mine = [w for w in extra[0] if inbar(w)]
                            got = place(slots, mine)
                            for n in starts:
                                got.setdefault(id(n), '_')
                            # A tie drawn across the end of a line cannot be seen by a reader that takes one system at
                            # a time.  The words give it away: the same pitch again, first thing in the new system, with
                            # no syllable of its own, is the old note still sounding.
                            if j == 0 and starts and starts[0]['on'] == 0 and got.get(id(starts[0])) == '_' and (lines[v] if v < len(lines) else lines[0] if lines else []):
                                k_, midi_ = last.get((role, v), (None, None))
                                if midi_ == starts[0]['midi'] and k_ is not None:
                                    head, _, toks_ = out[k_].partition(': ')
                                    tl_ = toks_.split()
                                    note_, eq_, lyr_ = tl_[-1].partition('=')
                                    if not note_.endswith('~'):
                                        tl_[-1] = note_ + '~' + eq_ + lyr_
                                        out[k_] = head + ': ' + ' '.join(tl_)
                                    del got[id(starts[0])]
                            syl[v] = got
                dyn = ('!' + st['measures'][j]['dyn'] + ' ') if st['measures'][j].get('dyn') in ('pp', 'p', 'mp', 'mf', 'f', 'ff') else ''
                shift = 1 if (role in ('TEN', 'T1', 'T2') or role == 'ALL') and st['clef'] == 'F' else 0
                tu, tl = tokens(up, syl[0], shift if role != 'ALL' else 1 if st['clef'] == 'F' else 0), tokens(lo, syl[1], 0 if role == 'ALL' else shift)
                same = [x.split('=')[0] for x in tokens(up)] == [x.split('=')[0] for x in tokens(lo)]
                if role == 'SOLO':
                    out.append('SOLO: ' + dyn + ' '.join(tu)); where = (len(out) - 1, len(out) - 1)
                elif role == 'ALL':
                    out.append('TEN: ' + dyn + ' '.join(tu)); out.append('LOW: ' + ' '.join(tl)); where = (len(out) - 2, len(out) - 1)
                elif role in ('TEN', 'LOW'):
                    a_, b_ = ('T1', 'T2') if role == 'TEN' else ('BR', 'BS')
                    out += [f'{role}: ' + dyn + ' '.join(tu)] if same else [f'{a_}: ' + dyn + ' '.join(tu), f'{b_}: ' + ' '.join(tl)]
                    where = (len(out) - 1, len(out) - 1) if same else (len(out) - 2, len(out) - 1)
                else:
                    out.append(f'{role}: ' + dyn + ' '.join(tu)); where = (len(out) - 1, len(out) - 1)
                for v, line in enumerate((up, lo)):          # remember how each voice left this bar
                    n_, a_, b_ = line[-1]
                    last[(role, v)] = (where[v], n_['midi']) if n_ is not None and b_ == length and n_['on'] + n_['ql'] >= length else (None, None)
    first_time = next((l[6:] for l in out if l.startswith('time: ')), '4/4')
    unit = {'2': 2., '8': 1.5 if int(first_time.split('/')[0]) % 3 == 0 else 1.}.get(first_time.split('/')[1], 1.)
    if unit != 1 and marked:        # a metronome mark counts the beat: half notes in 2/2, dotted quarters in 6/8
        tempo *= unit
        out = [re.sub(r'^tempo: (\S+)$', lambda m_: 'tempo: %g' % (float(m_.group(1)) * unit), l) for l in out]
    head = [f'title: {title}', f'tempo: {tempo:g}', f"time: {first_time}", 'key: 0',
            'transpose: TEN -12'] + ([f'language: {language}'] if language else []) + ['']
    first = next((i for i, l in enumerate(out) if l.startswith('time: ')), None)
    if first is not None:
        out.pop(first)
    return '\n'.join(head + out) + '\n'


def find_tempo(pages, work):
    """The metronome mark, if the first pages print one ("= ca. 60")."""
    exe = ocr_cmd(work)
    for p in pages[:3]:
        if exe:
            text = ' '.join(l.partition('\t')[2] for l in subprocess.run([exe, p], capture_output=True, text=True).stdout.splitlines())
            m = re.search(r'=\s*(?:ca\.?\s*)?(\d{2,3})', text)
            if m and 30 <= int(m.group(1)) <= 240:
                return float(m.group(1))
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf'); ap.add_argument('out'); ap.add_argument('--work', help='folder for page images and intermediate files')
    ap.add_argument('--tempo', type=float); ap.add_argument('--title'); ap.add_argument('--language')
    a = ap.parse_args()
    work = a.work or os.path.splitext(a.out)[0] + '.scan'
    os.makedirs(work, exist_ok=True)
    pages = render_pages(a.pdf, work)
    crops = read_systems(cut_systems(pages, work, print), print)
    found = None if a.tempo else find_tempo(pages, work)
    tempo = a.tempo or found or 100.
    title = a.title or re.sub(r'[_-]+', ' ', os.path.splitext(os.path.basename(a.pdf))[0]).strip().title()
    open(a.out, 'w').write(assemble(crops, pages, work, title, tempo, a.language, print, marked=found is not None))
    print(f'wrote {a.out}: {sum(len(c["read"][0]["measures"]) for c in crops if c["read"])} measures from {len(crops)} systems, tempo {tempo:g}')


if __name__ == '__main__':
    main()
