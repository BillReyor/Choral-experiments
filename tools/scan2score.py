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
    """homr's staff boxes for a page -> every staff as (top, bottom, x0, x1, kind), top to bottom; kind is 'p' for
    the two staves of a grand staff (a piano), 'v' for a staff on its own."""
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
        staves += [(a, b, x0, x1, 'p' if label == 1 else 'v') for a, b in found]
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
        groups = []
        for g in group_systems(img, page_staves(img, txt)):
            # The voices' staves and the piano under them are one system even where the line that joins them at
            # the left is broken (a fold in the paper): the piano sits about as far below the last voice as the
            # voices sit from each other, where the next system would be much further off.
            if groups and all(s[4] == 'p' for s in g) and len(groups[-1]) >= 2 and all(s[4] == 'v' for s in groups[-1]):
                inner = float(np.median([b[0] - a[1] for a, b in zip(groups[-1], groups[-1][1:])]))
                if g[0][0] - groups[-1][-1][1] < 1.8 * inner:
                    groups[-1] = groups[-1] + g
                    continue
            groups.append(g)
        bounds = [(g[0][0], g[-1][1]) for g in groups]
        for si, g in enumerate(groups, 1):
            unit = np.mean([s[1] - s[0] for s in g])
            top = max(0 if si == 1 else (bounds[si - 2][1] + g[0][0]) / 2, g[0][0] - 3.5 * unit)
            bot = min(H if si == len(groups) else (g[-1][1] + bounds[si][0]) / 2, g[-1][1] + 3.5 * unit)
            name = os.path.join(work, 'p%02d_s%d' % (pi, si))
            if not os.path.exists(name + '.png'):       # the page with everything but this system blanked out:
                only = np.full_like(img, 255)           # the reader then sees one system at its normal size
                only[int(top):int(bot)] = img[int(top):int(bot)]
                Image.fromarray(only).save(name + '.png')
            crops.append(dict(name=name, page=pi, system=si, staves=[(s[0], s[1]) for s in g], kinds=[s[4] for s in g], top=int(top), bot=int(bot),
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
    root = ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))).getroot()
    segments = {}                                   # segment number -> staves, in page order
    for part in root.findall('part'):
        nst = int(part.findtext('measure/attributes/staves') or 1)
        mine = [dict(clef=None, measures=[]) for _ in range(nst)]
        div, seg, carry = 1, 0, None
        for m in part.findall('measure'):
            pr = m.find('print')
            if pr is not None and pr.get('new-system') == 'yes' and mine[0]['measures']:
                segments.setdefault(seg, []).extend(mine); seg += 1      # two staves of a choir read as a new system
                mine = [dict(clef=None, measures=[]) for _ in range(nst)]
            cur = Fraction(0); last_on = Fraction(0)
            per = [dict(len=None, time=None, notes=[]) for _ in range(nst)]
            for bl in m.findall('barline'):
                d = bl.find('repeat')
                if d is not None:
                    for x in per:
                        x['rep_start' if d.get('direction') == 'forward' else 'rep_end'] = True
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
                    pos = next((c_.text for c_ in e if c_.tag is ET.Comment and 'imgpos' in (c_.text or '')), None)
                    xy = [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', pos)[:2]] if pos else [None, None]
                    if midi is not None or ql:
                        per[k]['notes'].append(dict(on=on, ql=ql, midi=midi, name=name, voice=e.findtext('voice') or '1', chord=chord, x=xy[0],
                                                    tie=any(t.get('type') == 'start' for t in e.findall('tie')),
                                                    slur=[x.get('type') for x in e.iter('slur')]))
                    if not chord:
                        last_on = cur; cur += ql
            dyn = m.find('direction/direction-type/dynamics')
            if dyn is not None and len(dyn):
                per[0]['dyn'] = dyn[0].tag
            if m.find('note') is None:                  # only a clef and key before a repeat sign: not a measure
                carry = per[0]['time'] or carry
                continue
            for k in range(nst):
                if carry and not per[k]['time']:
                    per[k]['time'] = carry
                mine[k]['measures'].append(per[k])
            carry = None
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
    sound = lambda read, n: len(read) == n and len({len(st['measures']) for st in read}) == 1
    for c in crops:
        c['read'] = read_xml(c['name'] + '.musicxml') if os.path.exists(c['name'] + '.musicxml') else []
    # A system of many staves (each voice on its own, then the piano) is sometimes read as a pile of piano systems.
    # What is on the page is known - how many staves, and which two are the piano's - so a reading that does not
    # match is done again in parts: the voices' staves alone, the piano alone; and if the voices still come back
    # wrong, each voice's staff by itself.
    def part_image(c, i, j, tag):
        st = c['staves']
        top = c['top'] if i == 0 else (st[i - 1][1] + st[i][0]) / 2
        bot = c['bot'] if j == len(st) - 1 else (st[j][1] + st[j + 1][0]) / 2
        name = f"{c['name']}_{tag}"
        if not os.path.exists(name + '.png'):
            img = np.asarray(Image.open(c['name'] + '.png').convert('L'))
            only = np.full_like(img, 255)
            only[int(top):int(bot)] = img[int(top):int(bot)]
            Image.fromarray(only).save(name + '.png')
        return name

    def in_parts(c, groups):
        names = [part_image(c, i, j, tag) for i, j, tag in groups]
        todo = [n + '.png' for n in names if not os.path.exists(n + '.musicxml')]
        return names, todo

    bad = [c for c in crops if c['read'] and len(c['staves']) >= 3 and not sound(c['read'], len(c['staves']))]
    plans = {}
    for c in bad:
        k = c.get('kinds') or ['v'] * len(c['staves'])
        nv = sum(1 for x in k if x == 'v')
        groups = ([(0, nv - 1, 'voices')] if nv else []) + ([(nv, len(k) - 1, 'piano')] if nv < len(k) else [])
        plans[c['name']] = (groups, *in_parts(c, groups))
    todo = [t for g, names, td in plans.values() for t in td]
    if todo:
        log(f'reading {len(bad)} system(s) again in parts ({len(todo)} images)...')
        run_homr(todo)
    again = {}
    for c in bad:
        groups, names, _ = plans[c['name']]
        reads = [read_xml(n + '.musicxml') if os.path.exists(n + '.musicxml') else [] for n in names]
        if groups and groups[0][2] == 'voices' and not sound(reads[0], groups[0][1] + 1) and groups[0][1] >= 1:
            single = [(i, i, f'v{i + 1}') for i in range(groups[0][1] + 1)]
            again[c['name']] = (single, groups[1:], *in_parts(c, single))
        else:
            c['read'] = [st for r in reads for st in r]
    todo = [t for v in again.values() for t in v[3]]
    if todo:
        log(f'reading {len(again)} system(s) staff by staff ({len(todo)} images)...')
        run_homr(todo)
    for c in bad:
        if c['name'] in again:
            single, rest, names, _ = again[c['name']]
            reads = [(read_xml(n + '.musicxml') if os.path.exists(n + '.musicxml') else [])[:1] for n in names]
            reads += [read_xml(part_image(c, i, j, tag) + '.musicxml') if os.path.exists(part_image(c, i, j, tag) + '.musicxml') else [] for i, j, tag in rest]
            c['read'] = [st for r in reads for st in r]
    for c in crops:
        if len(c['read']) != len(c['staves']):
            log(f"  ! page {c['page']} system {c['system']}: {len(c['staves'])} staves on the page but {len(c['read'])} were read")
        elif c['read'] and len({len(st['measures']) for st in c['read']}) > 1:
            log(f"  ! page {c['page']} system {c['system']}: the staves were read with different numbers of measures {[len(st['measures']) for st in c['read']]}")
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


TEXT = {'pages': {}, 'page': None, 'width': None}     # words a PDF carries as text, by page, in the page image's pixels


def pdf_words(pdf, zoom=2.6):
    """The words a PDF carries as real text (a score exported from notation software has its lyrics that way, even
    when its notes are in a font this project cannot read as shapes) -> {page number: [(x centre, y centre, x0, x1,
    text)]}.  Music-font symbols are left out.  No text recognition is needed for such a file - on any system."""
    import pymupdf
    out = {}
    for i, page in enumerate(pymupdf.open(pdf)):
        words = []
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for sp in l['spans']:
                    t = sp['text'].strip()
                    if not t or any(0xE000 <= ord(ch) <= 0xF8FF for ch in t) or re.search('Bravura|Maestro|Petrucci|Opus|Emmentaler|Leland|Sonata', sp['font']):
                        continue
                    x0, y0, x1, y1 = (v * zoom for v in sp['bbox'])
                    parts = t.split()
                    if len(parts) > 1:                   # several words in one run: share its width out by their lengths
                        total = sum(len(q) for q in parts) + len(parts) - 1
                        at = x0
                        for q in parts:
                            w = (x1 - x0) * len(q) / total
                            words.append(((2 * at + w) / 2, (y0 + y1) / 2, at, at + w, q))
                            at += w + (x1 - x0) / total
                    else:
                        words.append(((x0 + x1) / 2, (y0 + y1) / 2, x0, x1, t))
        # A hyphen is a text object of its own, standing between two syllables: hang it on the syllable before it,
        # which is how the rest of the reader expects to find it.
        hyph = [w for w in words if w[4] in ('-', '–', '—')]
        rest = [list(w) for w in words if w[4] not in ('-', '–', '—')]
        for h in hyph:
            before = [w for w in rest if abs(w[1] - h[1]) < .6 * (h[3] - h[2] + 8) + 6 and w[3] <= h[2] + 2]
            if before:
                w = max(before, key=lambda w: w[3])
                if h[2] - w[3] < 60 * zoom and not w[4].endswith('-'):
                    w[4] += '-'
        out[i + 1] = [tuple(w) for w in rest]
    return out


def on_page(n, img=None):
    """Tell the word reader which page is being looked at (it matters only when the words come from the PDF)."""
    TEXT['page'] = n
    if img is not None:
        TEXT['width'] = img.shape[1]


def ocr_words(exe, img, y0, y1, work, tag, zoom=3):
    """Words between two heights of a page, read at three times the size (small print needs it; hyphens too).
    -> [(x centre, y centre, x0, x1, text)] in page pixels."""
    if TEXT['pages']:
        if img.shape[1] != TEXT['width']:               # a close-up of one spot: the PDF's text has nothing more to give
            return []
        return [w for w in TEXT['pages'].get(TEXT['page'], []) if y0 <= w[1] <= y1]
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


def ocr_multi(exe, img, y0, y1, work, tag, zooms):
    """Text recognition is moody about size: the same line can come back whole at one enlargement and empty at
    the next.  So read it at several and keep everything seen, the later (usually larger) reading winning
    where two overlap."""
    kept = []
    for z in zooms:
        for w in ocr_words(exe, img, y0, y1, work, tag, zoom=z):
            clash = [k for k in kept if abs(k[1] - w[1]) < 14 and min(k[3], w[3]) - max(k[2], w[2]) > .3 * min(k[3] - k[2], w[3] - w[2])]
            if not clash:
                kept.append(w)
            elif len(clash) == 1 and len(re.sub(r"[^A-Za-z]", '', w[4])) >= len(re.sub(r"[^A-Za-z]", '', clash[0][4])):
                kept[kept.index(clash[0])] = w
    return kept


CHORD = re.compile(r'^[A-G][b#]?(m|maj|min|dim|aug|sus|add|M)?[0-9]*(sus[0-9]*|add[0-9]*)?(/[A-G][b#]?)?$')     # Ebm7, Bbadd2, Cm7/Bb
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
    def marking(i, w):               # "poco rit.", "a tempo", "cresc." - and their misreadings ("noco")
        t = re.sub(r"[^a-z]", '', w[4].lower())
        near = lambda a, b: len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1
        if near(t, 'poco') or near(t, 'cresc') or near(t, 'tempo'):
            return True
        nxt = [v for v in words if abs(v[1] - w[1]) < 1.2 * unit and 0 < v[2] - w[3] < 4 * unit]
        return t == 'a' and any(near(re.sub(r"[^a-z]", '', v[4].lower()), 'tempo') for v in nxt)
    words = [w for i, w in enumerate(words) if not marking(i, w)]
    words = [w[:4] + (clean_word(w[4]),) for w in words if '(' not in w[4] and ')' not in w[4]
             and not (CHORD.match(w[4].strip('.,')) and (len(w[4]) > 1 and w[4] not in ('Be', 'Am', 'Em', 'Go', 'Do', 'Ad', 'Dim')))]
    words = [w for w in words if not NOT_LYRICS.match(w[4]) and re.search(r"[aeiouyAEIOUY]", w[4])
             and (len(w[4].strip(".,;:!?'-")) > 1 or w[4].strip(".,;:!?'-").lower() in ('a', 'e', 'i', 'o', 'u'))]
    if not words:
        return []
    rows = []
    for w in sorted(words, key=lambda w: w[1]):
        if rows and w[1] - np.mean([v[1] for v in rows[-1]]) < 1.2 * unit:
            rows[-1].append(w)
        else:
            rows.append([w])
    most = max(len(r) for r in rows)                 # a couple of stray words on a line of their own ("poco rit." for the
    rows = [r for r in rows if len(r) >= max(2, .4 * most) or len(r) == most]      # staff below) are not a line of lyrics
    main_y = float(np.mean([w[1] for w in next(r for r in rows if len(r) == most)]))
    rows = [r for r in rows if abs(float(np.mean([w[1] for w in r])) - main_y) <= 2.6 * unit]     # lines of lyrics sit close together
    out = []
    for r in rows[:2]:
        r = sorted(r, key=lambda w: w[2])
        yc = float(np.median([w[1] for w in r]))
        line = []
        for i, (xc, _, x0, x1, text) in enumerate(r):
            text = re.sub(r"([.,;:!?])-+$", r"\1", text)                   # punctuation ends a word, whatever dash follows
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


def _tall(img, top, bot, x0, x1, unit, grand=False):
    """Columns holding one dark run about a staff high (3.2 to 4.8 line spaces; any length from 3.2 up on a
    piano's staff, where the barline runs on into the gap) somewhere within the staff's box and a little beyond it.
    Unlike _columns this does not need the box to sit exactly on the staff's outer lines."""
    lo, hi = max(0, int(top - .7 * unit)), min(img.shape[0], int(bot + .7 * unit))
    dark = img[lo:hi, x0:x1] < 200                     # a photocopy's barlines are thin and grey, and broken here and there
    dark = dark | np.roll(dark, 1, 1) | np.roll(dark, -1, 1)
    dark[2:] = dark[2:] | (dark[1:-1] & True) | dark[:-2]         # a gap of a pixel or two does not end the line
    cur = np.zeros(dark.shape[1], int); best = cur.copy()
    for row in dark:
        cur = (cur + 1) * row
        best = np.maximum(best, cur)
    ok = (best >= 3.2 * unit) & ((best <= 4.8 * unit) | grand)
    xs, run = [], []
    for c in list(np.flatnonzero(ok)) + [10 ** 9]:
        if run and c - run[-1] > 3:
            if len(run) <= 1.2 * unit:
                xs.append(x0 + float(np.mean(run)))
            run = []
        run.append(c)
    return xs


def barlines(img, staves, x0, x1, piano, expect=None, grand=None):
    """The measure boundaries of one system, left and right edge included.  A barline is a thin vertical line;
    what tells it from a note stem is that it stands at the same place on every staff - and through the
    piano's two staves it runs unbroken, gap included, which no stem does.  Two ways of looking are tried, and
    with `expect` (the number of measures read) the one that agrees with it is believed."""
    x0, x1 = int(x0), int(x1)
    unit = float(np.mean([(b - a) / 4 for a, b in staves]))
    slope = _tilt(img, staves[0][0], unit, x0, x1)
    ways = []
    if piano and len(staves) >= 2:
        found = _columns(img, staves[-2][0] + .3 * unit, staves[-1][1] - .3 * unit, x0, x1, slope)
        ways.append([x for x, w in found if w <= 1.2 * unit])
    else:
        per = [[x for x, w in _columns(img, a + .25 * unit, b - .25 * unit, x0, x1, slope) if w <= 1.2 * unit] for a, b in staves]
        ways.append([x for x in per[0] if all(any(abs(x - y) < .7 * unit for y in other) for other in per[1:])] if len(per) > 1 else per[0])
    # Staff by staff, and a vote: a barline stands at the same place on most staves (a stem rarely fills a whole
    # staff, and never on most of them at once).  This reads a score where every voice has its own staff and the
    # barlines do not run from one to the next, and it does not mind a staff's box being a little off.
    grand = grand or [piano and i >= len(staves) - 2 for i in range(len(staves))]
    per = [_tall(img, a, b, x0, x1, unit, g) for (a, b), g in zip(staves, grand)]
    need = len(per) if len(per) <= 2 else max(2, int(np.ceil(.6 * len(per))))
    vote = []
    for x in sorted(x for q in per for x in q):
        if vote and x - vote[-1] < .7 * unit:
            continue
        if sum(any(abs(x - y) < .7 * unit for y in q) for q in per) >= need:
            vote.append(float(np.mean([y for q in per for y in q if abs(x - y) < .7 * unit])))
    ways.append(vote)

    def tidy(xs):
        inner = []
        for x in xs:
            if x - x0 < 2.5 * unit or x1 - x < 1.5 * unit:
                continue
            if inner and x - inner[-1] < 1.5 * unit:      # a double bar is one barline
                inner[-1] = x
            else:
                inner.append(x)
        return [float(x0)] + inner + [float(x1)]

    ways = [tidy(w) for w in ways]
    if expect is not None:
        ways.sort(key=lambda w: abs(len(w) - 1 - expect))
    return ways[0]


def place_x(slots, syls, unit):
    """Syllables onto notes by position.  slots: notes in order, each with its x on the page; syls: [(x, text)]
    in order.  Each syllable goes to at most one note and each note gets at most one, in order, as close
    together as possible; a syllable with no note near it is dropped, a note with none continues the vowel.
    -> {id(note): text}"""
    if not slots or not syls:
        return {}
    xs = np.array([n['x'] for n in slots]); sx = np.array([w[0] for w in syls])
    near = sx - xs[np.abs(sx[:, None] - xs[None, :]).argmin(1)]
    off = float(np.median(near)) if len(near) >= 4 and abs(np.median(near)) < 2 * unit else 0.     # words sit a little left or right of their notes
    k, n = len(syls), len(slots)
    INF = 1e9
    drop, skip = 2.6 * unit, .9 * unit
    cost = np.full((k + 1, n + 1), INF); cost[0, 0] = 0
    step = np.zeros((k + 1, n + 1), np.int8)
    for i in range(k + 1):
        for j in range(n + 1):
            if i == 0 and j == 0:
                continue
            best, how = INF, 0
            if i and j:
                d = abs(sx[i - 1] - off - xs[j - 1])
                if d <= 3.2 * unit and cost[i - 1, j - 1] + d < best:
                    best, how = cost[i - 1, j - 1] + d, 1
            if i and cost[i - 1, j] + drop < best:
                best, how = cost[i - 1, j] + drop, 2
            if j and cost[i, j - 1] + (.2 * unit if slots[j - 1].get('melisma') else skip) < best:
                best, how = cost[i, j - 1] + (.2 * unit if slots[j - 1].get('melisma') else skip), 3
            cost[i, j], step[i, j] = best, how
    out, i, j = {}, k, n
    while i or j:
        how = step[i, j]
        if how == 1:
            out[id(slots[j - 1])] = syls[i - 1][1]; i -= 1; j -= 1
        elif how == 2:
            i -= 1
        else:
            j -= 1
    return out


def find_segno(img, y0, y1, unit):
    """x of every segno sign in a band above a staff: a shape about three spaces tall with two separate dots
    beside it (an S, a slash, two dots) - nothing else printed up there looks like that."""
    from scipy import ndimage
    lab, n = ndimage.label(img[int(y0):int(y1)] < 140)
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1)) if n else []
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if 2.4 * unit <= h <= 4.3 * unit and 1.8 * unit <= w <= 3.5 * unit and .22 <= sizes[i - 1] / (h * w) <= .6:
            box = lab[max(0, sl[0].start - int(.3 * unit)):sl[0].stop + int(.3 * unit), max(0, sl[1].start - int(.8 * unit)):sl[1].stop + int(.8 * unit)]
            dots = [j for j in set(np.unique(box)) - {0, i} if 4 < sizes[j - 1] < .5 * unit * unit]
            if len(dots) == 2:
                out.append((sl[1].start + sl[1].stop) / 2)
    return out


def navigation(words, segnos, bars, first, unit):
    """Words and signs above a system -> [(what, printed measure)], measures counted from `first`.
    A jump instruction is printed at the end of the measure it follows; a section label at its start."""
    at = lambda x: first + int(np.clip(np.searchsorted(bars, x) - 1, 0, len(bars) - 2))
    words = sorted(words, key=lambda w: w[2])
    out = [('segno', at(x)) for x in segnos]
    for i, w in enumerate(words):
        t = re.sub(r"[^a-z.]", '', w[4].lower())
        rest = ' '.join(re.sub(r"[^a-z]", '', v[4].lower()) for v in words[i + 1:i + 5] if v[2] - w[3] < 22 * unit)
        end = max([w[3]] + [v[3] for v in words[i + 1:i + 6] if v[2] - w[3] < 22 * unit and abs(v[1] - w[1]) < 1.5 * unit])
        if t in ('d.s.', 'd.s', 'ds', 'ds.') or t in ('d.c.', 'd.c', 'dc', 'dc.'):
            out.append((('ds' if 's' in t else 'dc') + (' fine' if 'fine' in rest else ' coda' if 'coda' in rest else ''), at(end - 3 * unit)))
        elif t == 'coda' or t == 'coda.':
            before = ' '.join(re.sub(r"[^a-z]", '', v[4].lower()) for v in words[max(0, i - 3):i] if w[2] - v[3] < 14 * unit)
            if re.search(r'\bal\b', before):
                continue                                     # "D.S. al Coda": handled with the D.S.
            out.append(('to coda', at(w[3] - 3 * unit)) if re.search(r'\bto\b', before) else ('coda', at(w[2] + 2 * unit)))
        elif t in ('fine', 'fine.'):
            before = ' '.join(re.sub(r"[^a-z]", '', v[4].lower()) for v in words[max(0, i - 2):i])
            if not re.search(r'\bal\b', before):
                out.append(('fine', at(w[3] - 3 * unit)))
    return out


def performed(n, nav, starts, ends):
    """The order the printed measures 1..n are played in, by the usual rules: a repeated passage twice;
    D.S. / D.C. back to the sign / the top, no repeats the second time; then on to the coda at "to coda",
    or stop at "Fine".  -> list of printed measure numbers, or None when there is nothing to unroll."""
    where = lambda k: next((m for what, m in nav if what == k), None)
    jump = next(((what, m) for what, m in nav if what.startswith(('ds', 'dc'))), None)
    if not jump and not ends:
        return None
    order, i, taken, back, second = [], 1, set(), 1, False
    while 1 <= i <= n and len(order) < 6 * n:
        if i in starts and not second:
            back = i
        order.append(i)
        if i in ends and i not in taken and not second:
            taken.add(i); i = back
            continue
        if jump and not second and i == jump[1]:
            target = where('segno') if jump[0].startswith('ds') else 1
            if target:
                second = True; i = target
                continue
        if second and 'coda' in jump[0] and i == where('to coda') and where('coda'):
            i = where('coda')
            continue
        if second and 'fine' in jump[0] and i == where('fine'):
            break
        i += 1
    return order


def ranges(order):
    out, a = [], 0
    for b in range(1, len(order) + 1):
        if b == len(order) or order[b] != order[b - 1] + 1:
            out.append(f'{order[a]}-{order[b - 1]}' if b - 1 > a else str(order[a])); a = b
    return ' '.join(out)


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
def roles_for(crops, piano=None):
    """Which staff of each system is what.  With a piano, its two staves are the lowest.  Above them (or all of
    them, unaccompanied): one staff = a soloist (if the piece has solo-plus-choir systems) or the whole choir;
    two = tenors and basses; three = solo + tenors + basses; four = one staff per part - unless their clefs go
    treble, bass, treble, bass, which is a small group (two tenors on one staff, a baritone) over the choir."""
    counts = [len(c['read']) for c in crops]
    if piano is None:
        piano = max(counts, default=0) >= 3
    known = [c.get('kinds') if c.get('kinds') and len(c['kinds']) == len(c['read']) and 'p' in ''.join(c['kinds']) else None for c in crops]
    grand = [(k is not None) if any(known) else (piano and n >= 2) for k, n in zip(known, counts)]    # does this system have the piano's staves?
    voc = [(n - 2 if g else n) for g, n in zip(grand, counts)]
    double = any(k == 4 and [st['clef'] for st in c['read'][:4]] == ['G', 'F', 'G', 'F'] for k, c in zip(voc, crops))
    for i, c in enumerate(crops):
        k = voc[i]
        if k == 1:
            near = next((v for v in voc[i + 1:] if v >= 2), None) or next((v for v in reversed(voc[:i]) if v >= 2), None)
            c['roles'] = ['SOLO' if near == 3 or double else 'ALL']
        elif k == 4 and double:
            c['roles'] = ['TRIO', 'TR3', 'TEN', 'LOW']
        else:
            c['roles'] = {0: [], 2: ['TEN', 'LOW'], 3: ['SOLO', 'TEN', 'LOW'], 4: ['T1', 'T2', 'BR', 'BS']}.get(k, ['TEN', 'LOW'] + ['?'] * (k - 2))
        c['roles'] += ['RH', 'LH'] if grand[i] else []


def has_piano(crops, pages, exe, work):
    """Are the two lowest staves a piano?  Not if words are printed under the lowest one."""
    if any('p' in ''.join(c.get('kinds') or []) for c in crops if len(c['staves']) >= 3):
        return True                                  # a grand staff under other staves, as the staff finder saw it
    big = [c for c in crops if len(c['read']) >= 3][:4]
    if not big or not exe:
        return None
    sung = 0
    for c in big:
        img = np.asarray(Image.open(pages[c['page'] - 1]).convert('L'))
        on_page(c['page'], img)
        top, bot = c['staves'][-1]
        unit = (bot - top) / 4
        words = ocr_words(exe, img, bot + .6 * unit, min(c['bot'], bot + 7 * unit), work, 'piano')
        mid = ocr_words(exe, img, c['staves'][-2][1] + .6 * unit, top - 1.0 * unit, work, 'piano')
        lyric = lambda ws: sum(1 for w in ws if re.search('[aeiou]', w[4].lower()) and len(w[4]) > 1 and not NOT_LYRICS.match(w[4]) and not CHORD.match(w[4]))
        sung += lyric(words) >= 3 or lyric(mid) >= 3
    return sung < len(big) / 2


def assemble(crops, pages, work, title, tempo, language, log, marked=False):
    exe = 'pdf-text' if TEXT['pages'] else ocr_cmd(work)
    if not exe:
        log('  ! no text recognition here (it uses macOS): the notes will have no words')
    piano = has_piano(crops, pages, exe, work)
    if piano is False:
        log('  no piano part: words are printed under the lowest staff')
    roles_for(crops, piano)
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
            loose = ocr_multi(exe, img, bot + .6 * unit, min(nxt - 1.2 * unit, bot + 9 * unit), work, tag, (2, 3, 6))
            loose = [w for w in loose if re.search('[A-Za-z]', w[4]) and '(' not in w[4] and not NOT_LYRICS.match(w[4])]
            ys = []
            for w in sorted(loose, key=lambda w: w[1]):
                if not any(abs(w[1] - y) < 1.2 * unit for y in ys):
                    ys.append(float(np.median([v[1] for v in loose if abs(v[1] - w[1]) < 1.2 * unit])))
            words = []
            for yc in ys:                # each line of text read again by itself, close up: that brings out the
                half = min([1.3 * unit] + [.5 * abs(yc - y) for y in ys if y != yc])      # small syllables
                tight = [w for w in ocr_multi(exe, img, yc - half, yc + half, work, tag, (3, 4, 6)) if re.search('[aeiouyAEIOUY]', w[4]) or w[4] in '-–—']
                row = [w for w in loose if abs(w[1] - yc) < 1.2 * unit]
                words += [w[:1] + (yc,) + w[2:] for w in tight]
                words += [w for w in row if not any(w[2] < t[3] and t[2] < w[3] for t in tight)]   # what only the first look saw
            if 'bars' not in c:
                c['bars'] = barlines(img, c['staves'], c['x0'], c['x1'], 'RH' in c['roles'], expect=M)
                if len(c['bars']) != M + 1:
                    log(f"  ? page {c['page']} system {c['system']}: found {len(c['bars']) - 1} measures on the page but {M} were read; words placed by even spacing")
                    c['bars'] = list(np.linspace(c['x0'], c['x1'], M + 1))
            bars = c['bars']
            texts[si] = (syllables(words, unit, img), bars, unit, sorted(ys))
            if si == 0:              # the first tenors' own words, where they differ, are printed above the staff
                up_words = ocr_words(exe, img, max(c['top'], top - 4.4 * unit), top - .5 * unit, work, tag + 'a', zoom=4)
                rows_up = syllables(up_words, unit, img)
                c['above'] = (rows_up[-1] if rows_up else [], unit)
        return texts

    for c in crops:                                 # first the words of the whole piece ...
        if c['read']:
            counts = [len(st['measures']) for st in c['read']]
            img = imgs.setdefault(c['page'], np.asarray(Image.open(pages[c['page'] - 1]).convert('L')))
            on_page(c['page'], img)
            c['texts'] = read_texts(c, img, max(set(counts), key=counts.count))
    # ... so that the words can be checked against each other before any note gets one.
    key = lambda t: re.sub(r"[^a-z']", '', t.lower())
    words_ok = None
    if not language or language == 'english':
        try:
            import cmudict
            sys.path.insert(0, HERE)
            from choral import lyrics as _ly
            words_ok = set(cmudict.dict()) | set(_ly.FIXED)      # the sung syllables that are no dictionary's words: pum, oo, ah
        except Exception:
            words_ok = None
    seen, loose = {}, {}
    for c in crops:
        for si, (lines, bars, unit, ys) in list(c.get('texts', {}).items()):
            fixed = []
            for line in lines:
                line = [list(w) for w in line]
                if words_ok and len(line) > 1:      # divide the line into words: real words are preferred, and what
                    k_ = [key(w[1]) for w in line]  # was seen on the page (a hyphen, or none) is the tie-breaker
                    hy = [w[1].endswith('-') for w in line]
                    stop = [bool(re.search(r"[.,;:!?]$", w[1].rstrip('-'))) for w in line]
                    n_ = len(line)
                    best = [(0., [])] + [(1e9, [])] * n_          # best[i]: cheapest way to divide the first i syllables
                    for i in range(1, n_ + 1):
                        for j in range(max(0, i - 5), i):          # a word made of syllables j .. i-1
                            if any(stop[j:i - 1]):
                                continue
                            word = ''.join(k_[j:i])
                            ok = word in words_ok or (word.endswith("'s") and word[:-2] in words_ok) or not word
                            c_ = (0. if ok else 2.) + sum(0. if hy[m_] else 1. for m_ in range(j, i - 1)) + (1. if i < n_ and hy[i - 1] else 0.)
                            if best[j][0] + c_ < best[i][0]:
                                best[i] = (best[j][0] + c_, best[j][1] + [i])
                    ends_ = set(best[n_][1])
                    for m_ in range(n_):
                        line[m_][1] = line[m_][1].rstrip('-') + ('' if (m_ + 1) in ends_ else '-')
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
    nav, rep_starts, rep_ends = [], set(), set()    # what sends the music elsewhere: signs, words, repeat barlines
    last = {}                                       # (role, voice) -> (line number in out, pitch) of the note that ended the previous bar
    for c in crops:
        if not c['read']:
            continue
        img = imgs.setdefault(c['page'], np.asarray(Image.open(pages[c['page'] - 1]).convert('L')))
        on_page(c['page'], img)
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
            nav += navigation(above, find_segno(img, max(c['top'], top - 9 * unit0), top - .2 * unit0, unit0), bars0, num + 1, unit0)
            for mm in re.finditer(r'=\s*(?:ca\.?\s*)?(\d{2,3})', line):
                if 30 <= int(mm.group(1)) <= 240:
                    num_w = next((w for w in above if mm.group(1) in w[4]), None)
                    xw = min([w[2] for w in above if num_w and abs(w[1] - num_w[1]) < 1.5 * unit0 and num_w[2] - 32 * unit0 < w[2] <= num_w[2]] or [c['x0']])
                    marks[max(0, int(np.searchsorted(bars0, xw + 2 * unit0)) - 1)] = float(mm.group(1))
            if re.search(r'Tempo\s+I\b', line) and tempo:
                xw = next((w[2] for w in above if w[4].startswith('Tempo')), c['x0'])
                marks[max(0, int(np.searchsorted(bars0, xw)) - 1)] = float(tempo)
        plan = []
        for j in range(M):
            # How long is this measure?  Count it: the total most voices agree on.  (The printed time signature is
            # read too, but it is the less reliable of the two, and most systems do not print one at all.)
            totals = []
            for st in c['read']:
                if j < len(st['measures']):
                    by_voice = {}
                    for n in st['measures'][j]['notes']:
                        if not n['chord']:
                            by_voice[n['voice']] = by_voice.get(n['voice'], Fraction(0)) + n['ql']
                    totals += [v for v in by_voice.values() if v > 0]
            labels = [st['measures'][j]['time'] for st in c['read'] if j < len(st['measures']) and st['measures'][j]['time']]
            as_len = lambda lab: Fraction(int(lab.split('/')[0]) * 4, int(lab.split('/')[1]))
            if totals:
                best = max(set(totals), key=lambda v: (totals.count(v), v == length, v))
                if best != length and (totals.count(best) >= 2 or any(as_len(l) == best for l in labels)):
                    length = best
            t = next((l for l in labels if as_len(l) == length), None) or (cur_time if cur_time and as_len(cur_time) == length else None) \
                or (f'{int(length)}/4' if length == int(length) else f'{int(length * 2)}/8')
            plan.append((length, t))
        # ---- the words of the whole system, put on its notes by where both stand on the page
        sylmap = {}
        for si, role in enumerate(c['roles'][:len(c['read'])]):
            if role in ('RH', 'LH') or si not in texts or not texts[si][0]:
                continue
            lines, bars, unit, ys = texts[si]
            for v in (0, 1):
                row = v if v < len(lines) else 0                 # one line of words serves both voices
                slots = []
                for j in range(M):
                    stm = c['read'][si]['measures']
                    if j < len(stm) and any(n['midi'] is not None for n in stm[j]['notes']):
                        line = lines_of(stm[j]['notes'], plan[j][0])[v]
                        slots += [n for n, a_, b_ in line if n is not None and a_ == n['on'] and not n.get('tied_from') and n.get('x') is not None]
                got = place_x(slots, lines[row], unit)
                if exe and row < len(ys):                        # a note with no word under it: look there again, close up
                    half = min([1.3 * unit] + [.5 * abs(ys[row] - y) for y in ys if y != ys[row]])
                    taken = sorted(w[0] for w in lines[row])
                    for n in slots:
                        if id(n) in got or n.get('melisma'):
                            continue
                        if any(abs(x - n['x']) < 1.3 * unit for x in taken):
                            continue
                        x_a, x_b = int(max(0, n['x'] - 3.4 * unit)), int(n['x'] + 3.4 * unit)
                        again = ocr_words(exe, img[:, x_a:x_b], ys[row] - half, ys[row] + half, work, 'note', zoom=6)
                        again = [(w[0] + x_a, w[1], w[2] + x_a, w[3] + x_a, w[4]) for w in again]
                        found = [w for l_ in syllables(again, unit, img) for w in l_ if abs(w[0] - n['x']) < 1.7 * unit]
                        if found:
                            best = min(found, key=lambda w: abs(w[0] - n['x']))
                            got[id(n)] = best[1]; taken.append(best[0])
                if si == 0 and v == 0 and c.get('above') and c['above'][0]:
                    alone = []           # upper-voice notes that start while the lower voice does not start one of its own
                    for j in range(M):
                        stm = c['read'][si]['measures']
                        if j < len(stm) and any(n['midi'] is not None for n in stm[j]['notes']):
                            up_, lo_ = lines_of(stm[j]['notes'], plan[j][0])
                            if all(a_[0] is b_[0] for a_, b_ in zip(up_, lo_)) and len(up_) == len(lo_):
                                continue             # one voice only in this bar: what is printed above it is not words
                            lo_on = {a_: n for n, a_, b_ in lo_ if n is not None and a_ == n['on']}
                            alone += [n for n, a_, b_ in up_ if n is not None and a_ == n['on'] and not n.get('tied_from') and n.get('x') is not None
                                      and id(n) not in got and lo_on.get(a_) is not n and (a_ not in lo_on)]
                    got.update(place_x(alone, c['above'][0], unit))
                sylmap[(si, v)] = got
        for j in range(M):
            num += 1
            length, t = plan[j]
            if t != cur_time and (cur_time is None or as_len(t) != as_len(cur_time)):
                cur_time = t
                out.append('time: ' + t)
            if j in marks and (num > 1 or marks[j] != tempo):
                out.append(f'tempo: {marks[j]:g}')
            out.append(f'== {num}')
            if any(st['measures'][j].get('rep_start') for st in c['read'] if j < len(st['measures'])):
                rep_starts.add(num)
            if any(st['measures'][j].get('rep_end') for st in c['read'] if j < len(st['measures'])):
                rep_ends.add(num)
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
                    for v, line in enumerate((up, lo)):
                        if lines:           # a staff with no words under it sings the words of the staff that has them
                            starts = [n for n, a_, b_ in line if n is not None and a_ == n['on'] and not n.get('tied_from')]
                            got = {id(n): sylmap[(si, v)][id(n)] for n in starts if id(n) in sylmap.get((si, v), {})}
                            for n in starts:        # a note under a slur continues the vowel; any other note with no word of its
                                if n.get('melisma'):    # own is left open, and takes the word another part sings at that moment
                                    got.setdefault(id(n), '_')
                            # A tie drawn across the end of a line cannot be seen by a reader that takes one system at
                            # a time.  The words give it away: the same pitch again, first thing in the new system, with
                            # no syllable of its own, is the old note still sounding.
                            if j == 0 and starts and starts[0]['on'] == 0 and got.get(id(starts[0]), '_') == '_' and (lines[v] if v < len(lines) else lines[0] if lines else []):
                                k_, midi_ = last.get((role, v), (None, None))
                                if midi_ == starts[0]['midi'] and k_ is not None:
                                    head, _, toks_ = out[k_].partition(': ')
                                    tl_ = toks_.split()
                                    note_, eq_, lyr_ = tl_[-1].partition('=')
                                    if not note_.endswith('~'):
                                        tl_[-1] = note_ + '~' + eq_ + lyr_
                                        out[k_] = head + ': ' + ' '.join(tl_)
                                    got.pop(id(starts[0]), None); starts[0]['tied_from'] = True
                            syl[v] = got
                dyn = ('!' + st['measures'][j]['dyn'] + ' ') if st['measures'][j].get('dyn') in ('pp', 'p', 'mp', 'mf', 'f', 'ff') else ''
                shift = 1 if (role in ('TEN', 'T1', 'T2', 'TRIO') or role == 'ALL') and st['clef'] == 'F' else 0
                tu, tl = tokens(up, syl[0], shift if role != 'ALL' else 1 if st['clef'] == 'F' else 0), tokens(lo, syl[1], 0 if role == 'ALL' else shift)
                same = [x.split('=')[0] for x in tokens(up)] == [x.split('=')[0] for x in tokens(lo)]
                if role == 'SOLO':
                    out.append('SOLO: ' + dyn + ' '.join(tu)); where = (len(out) - 1, len(out) - 1)
                elif role == 'ALL':
                    out.append('TEN: ' + dyn + ' '.join(tu)); out.append('LOW: ' + ' '.join(tl)); where = (len(out) - 2, len(out) - 1)
                elif role in ('TEN', 'LOW', 'TRIO'):
                    a_, b_ = {'TEN': ('T1', 'T2'), 'LOW': ('BR', 'BS'), 'TRIO': ('TR1', 'TR2')}[role]
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
            'transpose: TEN -12', 'transpose: TRIO -12'] + ([f'language: {language}'] if language else []) + ['']
    first = next((i for i, l in enumerate(out) if l.startswith('time: ')), None)
    if first is not None:
        out.pop(first)
    order = performed(num, nav, rep_starts, rep_ends)
    if nav or rep_ends:
        found = sorted(set(nav), key=lambda x: x[1]) + [('repeat', f'{a_}-{b_}') for b_ in sorted(rep_ends) for a_ in [max([x for x in rep_starts if x <= b_] or [1])]]
        log('  on the page: ' + ', '.join(f'{what} at {m}' for what, m in found))
        head.insert(-1, '// found on the page: ' + ', '.join(f'{what} at {m}' for what, m in found))
        if order and order != list(range(1, num + 1)):
            head.insert(-1, 'play: ' + ranges(order) + '      // the order the printed measures are performed in - correct it here if it is wrong')
        elif any(w.startswith('ds') for w, _ in nav) and not any(w == 'segno' for w, _ in nav):
            log('  ! a D.S. is printed but its sign was not found: add a  play:  line to the score by hand')
    return '\n'.join(head + out) + '\n'


def find_tempo(pages, work):
    """The metronome mark, if the first pages print one ("= ca. 60")."""
    exe = ocr_cmd(work)
    for i, p in enumerate(pages[:3], 1):
        if TEXT['pages']:
            text = ' '.join(w[4] for w in sorted(TEXT['pages'].get(i, []), key=lambda w: (round(w[1] / 20), w[2])))
            # the note before the "=" is a music-font symbol and so not in the text: "Tempo ... = 132", or a bare number
            m = re.search(r'=\s*(?:ca\.?\s*)?(\d{2,3})', text)
            if m and 30 <= int(m.group(1)) <= 240:
                return float(m.group(1))
        elif exe:
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
    words = pdf_words(a.pdf)
    if sum(len(v) for v in words.values()) >= 12 * len(pages):       # a PDF with its words in it: no need to read them off the picture
        TEXT['pages'] = words
        print("the words are taken from the PDF's own text")
    crops = read_systems(cut_systems(pages, work, print), print)
    found = None if a.tempo else find_tempo(pages, work)
    tempo = a.tempo or found or 100.
    title = a.title or re.sub(r'[_-]+', ' ', os.path.splitext(os.path.basename(a.pdf))[0]).strip().title()
    open(a.out, 'w').write(assemble(crops, pages, work, title, tempo, a.language, print, marked=found is not None))
    print(f'wrote {a.out}: {sum(len(c["read"][0]["measures"]) for c in crops if c["read"])} measures from {len(crops)} systems, tempo {tempo:g}')


if __name__ == '__main__':
    main()
