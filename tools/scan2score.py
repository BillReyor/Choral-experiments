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
    staves = sorted(staves)
    return sorted(staves + missed_staves(img, staves))


def missed_staves(img, staves):
    """Staves the staff finder did not report (it happens to a staff with long slurs drawn through it): five lines,
    spaced like the page's other staves, standing between two staves it did find."""
    if len(staves) < 3:
        return []
    sp = float(np.median([(s[1] - s[0]) / 4 for s in staves]))       # from one line to the next
    tol = max(2., .2 * sp)
    out = []
    for prev, cur in zip(staves, staves[1:]):
        g0, g1 = int(prev[1] + 1.5 * sp), int(cur[0] - 1.5 * sp)
        x0, x1 = int(max(prev[2], cur[2])), int(min(prev[3], cur[3]))
        if g1 - g0 < 4 * sp or x1 - x0 < 20 * sp:
            continue
        hit = None
        for f in (.5, .3, .7, .2, .8):                               # narrow strips: scans are never level, and one may be crossed by a slur
            a = int(x0 + (f - .06) * (x1 - x0)); b = int(x0 + (f + .06) * (x1 - x0))
            rows = np.where((img[g0:g1, a:b] < 150).mean(1) > .6)[0]
            ys = []
            for r in rows:
                if ys and r - ys[-1][-1] <= 2:
                    ys[-1].append(r)
                else:
                    ys.append([r])
            ys = [float(np.mean(l)) for l in ys]
            for y in ys:
                five = [min(ys, key=lambda z: abs(z - y - k * sp)) for k in range(5)]
                if all(abs(z - y - k * sp) <= tol for k, z in enumerate(five)) and \
                        not any(y - 1.6 * sp < z < y - tol or five[4] + tol < z < five[4] + 1.6 * sp for z in ys):     # five lines, not six
                    hit = (g0 + five[0], g0 + five[4]); break
            if hit:
                break
        if hit:
            out.append((hit[0], hit[1], x0, x1, 'v'))
    return out


def group_systems(img, staves):
    """Staves joined at their left end by one unbroken vertical line belong to one system."""
    groups = [[staves[0]]] if staves else []
    for prev, cur in zip(staves, staves[1:]):
        gap0, gap1 = int(prev[1]) + 2, int(cur[0]) - 2
        here = int(min(prev[2], cur[2]))
        joined = False
        # the line stands where the staves begin - but a staff's found beginning can be late (a long slur, a clef
        # missed), so every earlier beginning seen on the page is tried as well
        # ... and never more than two and a half spaces to their right: three spaces in stands the clef, whose stem and
        # tail, the 8 under it, a measure number and the next clef's top can fill a column nearly as well as a line
        # does (0.65 of it, on one page; over nine scans every real line stood within 1.7 spaces)
        reach = int(2.5 * (prev[1] - prev[0]) / 4)
        for x in sorted({here} | {int(s_[2]) for s_ in staves if s_[2] < here}):
            dark = img[gap0:gap1, max(0, x - 42):x + reach] < 140
            near = dark[:, :-4] | dark[:, 1:-3] | dark[:, 2:-2] | dark[:, 3:-1] | dark[:, 4:]     # the line may lean a pixel or two
            joined = joined or (gap1 > gap0 and near.mean(0).max() > .6)       # measured: 0.73-1.00 within a system, under 0.4 between
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
            sig = repr([(int(s_[0]), int(s_[1])) for s_ in g])        # what was read before is kept only for the same staves
            if os.path.exists(name + '.staves') and open(name + '.staves').read() != sig or (os.path.exists(name + '.png') and not os.path.exists(name + '.staves')
                                                                                         and os.path.exists(os.path.join(work, 'layout.done'))):
                for f in os.listdir(work):
                    if f.startswith(os.path.basename(name) + '.') or f.startswith(os.path.basename(name) + '_'):
                        os.remove(os.path.join(work, f))
            open(name + '.staves', 'w').write(sig)
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
                            mine[k]['clef'] = c.findtext('sign'); mine[k]['line'] = c.findtext('line')
                    if e.findtext('key/fifths'):
                        for x in mine:
                            x.setdefault('key', int(e.findtext('key/fifths')))
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
                        midi = name = step = alter = octv = None
                    else:
                        step, alter, octv = e.findtext('pitch/step'), int(float(e.findtext('pitch/alter') or 0)), int(e.findtext('pitch/octave'))
                        midi = 12 * (octv + 1) + 'C D EF G A B'.index(step) + alter
                        name = name_of(step, alter, octv)
                    pos = next((c_.text for c_ in e if c_.tag is ET.Comment and 'imgpos' in (c_.text or '')), None)
                    xy = [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', pos)[:2]] if pos else [None, None]
                    if midi is not None or ql:
                        per[k]['notes'].append(dict(on=on, ql=ql, midi=midi, name=name, voice=e.findtext('voice') or '1', chord=chord, x=xy[0],
                                                    step=step, alter=alter, oct=octv,
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
    # Read from the symbols themselves, the two voices of a staff are known for certain (stems up, stems down): each
    # line is then its own voice, silent where that voice rests.  A recognized page's voices are not to be relied on:
    # there the upper line is whatever sounds highest, the lower whatever sounds lowest.
    known = bool(notes) and all(n.get('exact') for n in notes) and all(any(n['midi'] is not None and n['voice'] == v for n in notes) for v in ('1', '2'))
    for pick, voice in ((max, '1'), (min, '2')):
        line = []
        for a, b in zip(pts, pts[1:]):
            live = [n for n in notes if n['midi'] is not None and n['on'] <= a < n['on'] + n['ql'] and (not known or n['voice'] == voice)]
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


def instrument_lines(notes, length):
    """An instrument's measure as lines for the accompaniment (two voices of it at most).  Two things a clarinet's
    part has that a choir's does not.  A tremolo - two notes, each written as long as the whole measure, with beams
    between them - is the two played in turn.  And notes that overfill the measure by exactly half are triplets
    whose bracket was not read."""
    out = []
    for v in sorted({n['voice'] for n in notes}):
        mine = [dict(n) for n in notes if n['voice'] == v]
        heads = [n for n in mine if not n['chord']]
        total = sum((n['ql'] for n in heads), Fraction(0))
        if len(mine) == 2 and len(heads) == 2 and all(n['midi'] is not None and n['ql'] == length for n in mine) and mine[0]['midi'] != mine[1]['midi']:
            mine = [dict(mine[i % 2], on=Fraction(i, 4), ql=Fraction(1, 4), tie=False, slur=[]) for i in range(int(length * 4))]
        elif total == length * 3 / 2 and all(n['ql'] * 2 / 3 in TRIP or spell(n['ql'] * 2 / 3) for n in heads):
            for n in mine:
                n['on'] = n['on'] * 2 / 3; n['ql'] = n['ql'] * 2 / 3
        out += mine
    return piano_lines(layout(out, length), length, 'IN')[:2]


def read_systems(crops, log):
    """Pass 2: every system read on its own.  -> crops, each with 'read': its staves top to bottom."""
    need = [c['name'] + '.png' for c in crops if not os.path.exists(c['name'] + '.musicxml')]
    if need:
        log(f'reading {len(need)} system(s)...')
        run_homr(need)
    sound = lambda read, n: len(read) == n and len({len(st['measures']) for st in read}) == 1 and all(st['clef'] in ('G', 'F') for st in read)
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
    # A line of chant has no barlines, and the engine finds its staves by their barlines and clefs: where it returns
    # nothing at all for a staff that stands alone, it is shown that staff again with a barline drawn at its end.
    # (Only a staff whose five lines are really there: a ghost of the other side of the paper is left unread.)
    lost, todo = [], []
    for c in crops:
        if not c['read'] and len(c['staves']) == 1 and not os.path.exists(c['name'] + '.musicxml') and os.path.exists(c['name'] + '.png'):
            name, (top, bot) = c['name'] + '_closed', c['staves'][0]
            if not os.path.exists(name + '.png'):
                page = np.asarray(Image.open(c['name'] + '.png').convert('L')).copy()
                if len(staves_in(page, (int(c['x0']), int(top), int(c['x1']), int(bot)))) != 1:
                    continue
                page[int(top):int(bot) + 1, int(c['x1']) - 3:int(c['x1'])] = 0
                Image.fromarray(page).save(name + '.png')
            lost.append((c, name))
            todo += [name + '.png'] if not os.path.exists(name + '.musicxml') else []
    if todo:
        log(f'reading {len(todo)} staff(s) with no barlines again, closed with one...')
        run_homr(todo)
    for c, name in lost:
        c['read'] = (read_xml(name + '.musicxml') if os.path.exists(name + '.musicxml') else [])[:1]
    for c in crops:
        if len(c['read']) != len(c['staves']):
            log(f"  ! page {c['page']} system {c['system']}: {len(c['staves'])} staves on the page but {len(c['read'])} were read")
        elif c['read'] and len({len(st['measures']) for st in c['read']}) > 1:
            log(f"  ! page {c['page']} system {c['system']}: the staves were read with different numbers of measures {[len(st['measures']) for st in c['read']]}")
    return crops


# ------------------------------------------------------------------------- the words ----
def ocr_cmd(work):
    """A text recognizer for the words under the notes: macOS's own (compiled once from tools/ocr.swift), or
    Tesseract where that is not to be had - Linux, Windows, or a Mac without the developer tools.  Returns the
    program to run, 'tesseract', or None.  SCAN_OCR=tesseract (or =macos) insists on one of them."""
    want = os.environ.get('SCAN_OCR', '')
    if want != 'tesseract':
        exe = os.path.join(work, 'ocr')
        if os.path.exists(exe):
            return exe
        src = os.path.join(HERE, 'tools', 'ocr.swift')
        if shutil.which('swiftc') and not subprocess.run(['swiftc', '-O', src, '-o', exe], capture_output=True).returncode:
            return exe
        if want == 'macos':
            return None
    return 'tesseract' if shutil.which('tesseract') else None


def _tesseract(path, sparse=True):
    """Tesseract's words on an image -> [(x0, y0, x1, y1, text)] in the image's pixels."""
    r = subprocess.run(['tesseract', path, 'stdout', '--psm', '11' if sparse else '6', 'tsv'], capture_output=True, text=True)
    out = []
    for row in r.stdout.splitlines()[1:]:
        f = row.split('\t')
        if len(f) >= 12 and f[11].strip():
            try:
                left, top, wd, ht, conf = float(f[6]), float(f[7]), float(f[8]), float(f[9]), float(f[10])
            except ValueError:
                continue
            if conf >= 20:
                out.append((left, top, left + wd, top + ht, f[11].strip()))
    return out


TEXT = {'pages': {}, 'page': None, 'width': None}     # words a PDF carries as text, by page, in the page image's pixels


def pdf_words(pdf, zoom=2.6):
    """The words a PDF carries as real text (a score exported from notation software has its lyrics that way, even
    when its notes are in a font this project cannot read as shapes) -> {page number: [(x centre, y centre, x0, x1,
    text)]}.  Music-font symbols are left out.  No text recognition is needed for such a file - on any system."""
    import pymupdf
    out = {}
    for i, page in enumerate(pymupdf.open(pdf)):
        words = []
        for b in page.get_text('rawdict')['blocks']:
            for l in b.get('lines', []):
                for sp in l['spans']:
                    t = ''.join(c['c'] for c in sp['chars']).strip()
                    if not t or any(0xE000 <= ord(ch) <= 0xF8FF for ch in t) or re.search('Bravura|Maestro|Petrucci|Opus|Emmentaler|Leland|Sonata', sp['font']):
                        continue
                    cur = []                             # one run of text may hold a whole line of syllables, each set under its
                    def flush():                         # own note: every word is measured from its own letters
                        if cur:
                            x0 = min(c['bbox'][0] for c in cur) * zoom; x1 = max(c['bbox'][2] for c in cur) * zoom
                            y0 = min(c['bbox'][1] for c in cur) * zoom; y1 = max(c['bbox'][3] for c in cur) * zoom
                            words.append(((x0 + x1) / 2, (y0 + y1) / 2, x0, x1, ''.join(c['c'] for c in cur)))
                            cur.clear()
                    for c in sp['chars']:
                        if not c['c'].strip():
                            flush(); continue
                        if cur and c['bbox'][0] - cur[-1]['bbox'][2] > .3 * sp['size']:
                            flush()
                        cur.append(c)
                        if c['c'] in '-–—' and len(cur) > 1:     # "al-le-lu-ia" in one run: each syllable, with its hyphen
                            flush()
                    flush()
        # A hyphen is a text object of its own, standing between two syllables: hang it on the syllable before it,
        # which is how the rest of the reader expects to find it.
        hyph = [w for w in words if w[4] in ('-', '–', '—')]
        rest = [list(w) for w in words if w[4] not in ('-', '–', '—')]
        for h in hyph:
            before = [w for w in rest if abs(w[1] - h[1]) < .6 * (h[3] - h[2] + 8) + 6 and w[3] <= h[2] + 2 + .5 * (h[3] - h[2])]
            if before:
                w = max(before, key=lambda w: w[3])
                if h[2] - w[3] < 60 * zoom and not w[4].endswith('-'):
                    w[4] += '-'
        out[i + 1] = [tuple(w) for w in rest]
    return out


def pdf_title(pdf):
    """The piece's name as the PDF prints it: the largest words in the upper third of the first page, if they read as words."""
    import pymupdf
    page = pymupdf.open(pdf)[0]
    spans = [sp for b in page.get_text('dict')['blocks'] for l in b.get('lines', []) for sp in l['spans']
             if sp['text'].strip() and sp['bbox'][1] < page.rect.height / 3 and not re.search('Bravura|Maestro|Petrucci|Opus|Emmentaler|Leland|Sonata', sp['font'])]
    if not spans:
        return None
    big = max(sp['size'] for sp in spans)
    if big < 1.3 * float(np.median([sp['size'] for sp in spans])) and len(spans) > 3:
        return None
    line = sorted((sp for sp in spans if sp['size'] > .95 * big), key=lambda sp: (round(sp['bbox'][1] / big), sp['bbox'][0]))
    title = re.sub(r'\s+', ' ', ' '.join(sp['text'].strip() for sp in line)).strip()
    words = title.split()
    ok = 1 <= len(words) <= 12 and len(title) <= 80 and all(re.fullmatch(r"[A-Za-z0-9'’!?,.:&()-]+", w) for w in words) and sum(ch.isalpha() for ch in title) >= 3
    return title if ok else None


def on_page(n, img=None):
    """Tell the word reader which page is being looked at (it matters only when the words come from the PDF)."""
    TEXT['page'] = n
    if img is not None:
        TEXT['width'] = img.shape[1]


def as_printed(t):
    """Text recognition reads a held "oo" (in italics, as such vowels are printed) as zeros, and "I'll" as I'II."""
    t = re.sub(r'^[0oO]*0[0oO]*(?=[\W_]*$)', lambda m: 'o' * len(m.group()), t) if len(t) > 1 else t
    return re.sub(r"^([Il1][’'][Il1|]{2}|I[I1|][Il1|]|I[Il1|][I1|])(?=[\W_]*$)", "I'll", t)


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
    out, tall = [], []
    TEXT['tall'] = None
    if exe == 'tesseract':
        for x0, t0, x1, t1, text in _tesseract(path):
            out.append(((x0 + x1) / 2 / zoom, ((t0 + t1) / 2 - 120) / zoom + y0, x0 / zoom, x1 / zoom, as_printed(text)))
            tall.append((t1 - t0) / zoom)
        os.remove(path)
        TEXT['tall'] = float(np.median(tall)) if tall else None
        return out
    for line in subprocess.run([exe, path], capture_output=True, text=True).stdout.splitlines():
        box, _, text = line.partition('\t')
        f = [float(v) for v in box.split()]
        if len(f) == 4 and text.strip():
            x0, x1 = f[0] * canvas.size[0] / zoom, f[2] * canvas.size[0] / zoom
            yc = ((f[1] + f[3]) / 2 * canvas.size[1] - 120) / zoom + y0
            out.append(((x0 + x1) / 2, yc, x0, x1, as_printed(text.strip())))
            tall.append(abs(f[3] - f[1]) * canvas.size[1] / zoom)
    os.remove(path)
    TEXT['tall'] = float(np.median(tall)) if tall else None     # how tall this print is: lyrics are not sized by their staff
    return out


def ocr_multi(exe, img, y0, y1, work, tag, zooms):
    """Text recognition is moody about size: the same line can come back whole at one enlargement and empty at
    the next.  So read it at several and keep everything seen, the later (usually larger) reading winning
    where two overlap."""
    kept, talls = [], []
    for z in zooms:
        seen = ocr_words(exe, img, y0, y1, work, tag, zoom=z)
        if TEXT.get('tall'):
            talls.append(TEXT['tall'])
        same = max(14., .6 * min(talls)) if talls else 14.
        for w in seen:
            clash = [k for k in kept if abs(k[1] - w[1]) < same and min(k[3], w[3]) - max(k[2], w[2]) > .3 * min(k[3] - k[2], w[3] - w[2])]
            if not clash:
                kept.append(w)
            elif len(clash) == 1:
                letters = lambda t: len(re.sub(r"[^A-Za-z]", '', t))
                inner = lambda t: len(re.findall(r"(?<=[A-Za-z])-(?=[A-Za-z])", t))       # hyphens are dropped more often than invented
                if letters(w[4]) > letters(clash[0][4]) or (letters(w[4]) == letters(clash[0][4]) and inner(w[4]) >= inner(clash[0][4])):
                    kept[kept.index(clash[0])] = w
    TEXT['tall'] = min(talls) if talls else None
    return kept


CHORD = re.compile(r'^[A-G][b#]?(m|maj|min|dim|aug|sus|add|M)?[0-9]*(sus[0-9]*|add[0-9]*)?(/[A-G][b#]?)?$')     # Ebm7, Bbadd2, Cm7/Bb
NOT_LYRICS = re.compile(r'^(unis\.?|div\.?|cresc\.?|dim\.?|rit\.?|poco|tempo|pp|mp|mf|ff|sim\.?|[0-9]+)$', re.I)
PART_NAME = re.compile(r'^(tenors?|bass(es)?|baritones?|bari|solo|soli|trio|tutti|cantor)[.,:]?$', re.I)       # a staff's name, where it strays under another staff
PART_NUMBER = re.compile(r'^(I{1,3}|[A-Z]|[0-9]+|&|and)[.,:]?$')                 # "Tenor I", "Bass 2", and a rehearsal letter beside it


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


def find_endings(img, y0, y1, unit):
    """Brackets of numbered endings between two heights of a page: a level line with a short stroke down from its left
    end (the passes it is for are printed under that corner).  -> [(x of the stroke, y of the line, x where it ends)].
    A word's extension line has no stroke; a hairpin is not level; a beam is thick; a triplet's bracket is short."""
    from scipy import ndimage
    y0, y1 = int(max(0, y0)), int(min(img.shape[0], y1))
    if y1 - y0 < 2 * unit:
        return []
    dark = img[y0:y1] < 140
    loose = dark.copy(); loose[1:] |= dark[:-1]; loose[:-1] |= dark[1:]         # a scan is never level: a row either way
    level = ndimage.binary_opening(loose, structure=np.ones((1, int(5 * unit)), bool))
    lab, n = ndimage.label(level, structure=np.ones((3, 3)))
    out = []
    for sl in ndimage.find_objects(lab):
        xl, xr = sl[1].start, sl[1].stop
        rows = dark[sl[0], xl:xr]
        if np.median(rows.sum(0)) > max(3., .3 * unit):                          # a beam, a thick rule
            continue
        yl = sl[0].start + int(np.argmax(rows[:, :int(2 * unit)].sum(1)))        # the line's height at its left end
        strip = dark[yl:yl + int(2.2 * unit), max(0, xl - 3):xl + 4].any(1)      # the stroke down from that end
        down = int(np.argmin(strip)) if not strip.all() else len(strip)
        up = dark[max(0, yl - int(1.2 * unit)):max(0, yl - 2), max(0, xl - 3):xl + 4].any(1)
        if down >= .8 * unit and down < 2.2 * unit and (not len(up) or up.mean() < .4):
            out.append((float(xl), float(y0 + yl), float(xr)))
    return out


def ending_passes(exe, img, x, y, unit, work, tag):
    """The numbers printed under an ending bracket's corner - "1.", "1., 2.", "3." - read from that corner alone:
    with the stroke, the line and a measure number beside them in view, they are read as "T2." and "22/3.".
    Read at more than one size: a heavy "3." is seen at twice its size and not at four times."""
    x0, x1, y0, y1 = int(x + .4 * unit), int(x + 7 * unit), int(y + .3 * unit), int(y + 2.8 * unit)
    corner = np.full_like(img, 255)
    corner[y0:y1, x0:x1] = img[y0:y1, x0:x1]
    for zoom in (4, 2, 3):
        words = sorted((w for w in ocr_words(exe, corner, y0 - .5 * unit, y1 + .5 * unit, work, tag, zoom=zoom) if x0 - unit <= w[2] <= x1), key=lambda w: w[2])
        found = []
        for w in words:
            m = re.match(r'(?:[1-9][.,]{1,2}\s*)+', w[4].strip())           # "2.Te": the number, then the start of a word
            if not m:
                break
            found += [int(d) for d in re.findall(r'[1-9]', m.group(0))]
            if m.end() < len(w[4].strip()):
                break
        if found:
            return sorted(set(found))
    return []


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


def performed(n, nav, starts, ends, endings=()):
    """The order the printed measures 1..n are played in, by the usual rules: a repeated passage twice;
    D.S. / D.C. back to the sign / the top, no repeats the second time; then on to the coda at "to coda",
    or stop at "Fine".  endings: [(measure, passes)] - numbered endings: each is played on the passes it names and
    stepped over on the others, a pass being one time through the repeated passage it closes (so "1., 2." followed
    by a "1.", a "2." and a "3." is a refrain with three different continuations).
    -> list of printed measure numbers, or None when there is nothing to unroll."""
    where = lambda k: next((m for what, m in nav if what == k), None)
    jump = next(((what, m) for what, m in nav if what.startswith(('ds', 'dc'))), None)
    if not jump and not ends:
        return None
    begins = dict(endings); at = sorted(begins)
    last_of = lambda a: next((b for b in at if b > a), n + 1) - 1          # an ending lasts until the next one begins
    order, i, taken, back, second, passes = [], 1, set(), 1, False, {}
    while 1 <= i <= n and len(order) < 8 * n:
        if i in starts and not second:
            back = i
        if i in begins:
            turn = passes.get(back, 0) + 1
            # the second time through after a D.S., like any last time: the ending that leads on, not one that turns back
            skip = any(m in ends for m in range(i, last_of(i) + 1)) if second else turn not in begins[i]
            if skip and last_of(i) < n and any(b > i for b in at):
                i = last_of(i) + 1
                continue
        order.append(i)
        if i in ends and i not in taken and not second:
            taken.add(i); passes[back] = passes.get(back, 0) + 1; i = back
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
def join_split_systems(crops, log=print):
    """A system whose joining line was not found comes out as two: some voices, then the remaining staves with the
    keyboard.  Where a keyboard-less group is followed, on the same page, by one that ends with the keyboard, has
    as many measures, begins at the same place and lies no further below than staves lie within a system, they are
    one system."""
    out = []
    for c in crops:
        a = out[-1] if out else None
        if a is not None and a['page'] == c['page'] and a['read'] and c['read'] and len(a['read']) == len(a['staves']) and len(c['read']) == len(c['staves']) \
                and 'p' not in a.get('kinds', []) and c.get('kinds', [])[-2:] == ['p', 'p'] and abs(a['x0'] - c['x0']) < 12:
            ma = {len(st['measures']) for st in a['read']}; mc = {len(st['measures']) for st in c['read']}
            both = a['staves'] + c['staves']
            inner = [q[0] - p_[1] for p_, q in zip(both, both[1:])]
            gap = c['staves'][0][0] - a['staves'][-1][1]
            rest = [g for g in inner if g != gap]
            if ma == mc and len(ma) == 1 and rest and gap < 1.5 * max(rest):
                a['staves'] = both; a['kinds'] = a['kinds'] + c['kinds']; a['read'] = a['read'] + c['read']; a['bot'] = c['bot']
                a['x1'] = max(a['x1'], c['x1'])
                log(f"  page {a['page']}: two groups of staves are one system (its joining line was not found)")
                continue
        out.append(c)
    for i, c in enumerate(out):
        c['system'] = 1 + sum(1 for o in out[:i] if o['page'] == c['page'])
    return out


def label_role(text):
    """A staff's printed name -> what it is: 'T1' 'T2' 'BR' 'BS' 'TEN' 'BASS' 'SOLO', 'P' (keyboard), 'I' (an instrument
    that plays notes), 'D' (drums: nothing a piano could play), or None."""
    t = re.sub(r'[^a-z0-9 ]', ' ', text.lower()).split()
    j = ' '.join(t)
    if not t:
        return None
    if re.search(r'drum|perc|cymbal|tamb|shaker|conga|bongo', j) or re.fullmatch(r'(dr|perc)( (1|2|i|ii))?', j):
        return 'D'
    if re.search(r'clar|flute|oboe|bassoon|violin|viola|cello|horn|trumpet|trombone|sax|guitar|harp|bells|glock|timp|strings', j) or \
            re.fullmatch(r'(cl|fl|ob|bsn|vln|vn|vla|vc|hn|tpt|tbn)( (1|2|i|ii|in bb?|in a))?', j):
        return 'I'
    if re.search(r'keyb|piano|pno|organ|accomp|kbd', j):
        return 'P'
    if 'solo' in j:
        return 'SOLO'
    two = bool(re.search(r'\b(2|ii)\b', j)); one = bool(re.search(r'\b(1|i)\b', j))
    if re.search(r'\bt(en|enor|enors)?\b', j) or j in ('t1', 't2', 'ti', 'tii'):
        if one and two:                                  # "Tenor 1 2": both on this staff
            return 'TEN'
        return 'T2' if two or j in ('t2', 'tii') else 'T1' if one or j in ('t1', 'ti') else 'TEN'
    if re.search(r'\bbar', j):
        return 'LOW' if re.search(r'\bbass', j) else 'BR'      # "Baritone Bass" on one staff
    if re.search(r'\bb(ass|asses)?\b', j) or j in ('b1', 'b2', 'bi', 'bii'):
        if one and two:
            return 'LOW'
        return 'BS' if two or j in ('b2', 'bii') else 'BR' if one or j in ('b1', 'bi') else 'BASS'
    return None


def staff_labels(crops, pages, exe, work):
    """Read the names printed at the left of the staves ("Tenor 1", "B 2", "Clarinet", "Keybd.") -> c['labels'] per system.
    A system may show a different set of staves from the one before - an instrument that comes and goes, voices that
    divide - and the names are what says which is which."""
    if not exe:
        return
    for c in crops:
        if not c['read'] or len(c['staves']) != len(c['read']):
            continue
        img = np.asarray(Image.open(pages[c['page'] - 1]).convert('L'))
        on_page(c['page'], img)
        unit = float(np.mean([(b - a) / 4 for a, b in c['staves']]))
        x1 = int(c['x0'] - .4 * unit)
        if x1 < 6 * unit:
            continue
        if TEXT['pages']:
            words = [w for w in ocr_words(exe, img, c['top'], c['bot'], work, 'label') if w[3] <= x1 + unit]
        else:
            strip = np.full((img.shape[0], x1 + int(4 * unit)), 255, np.uint8)
            strip[:, int(2 * unit):int(2 * unit) + x1] = img[:, :x1]
            words = [(w[0] - 2 * unit, w[1], w[2] - 2 * unit, w[3] - 2 * unit, w[4]) for w in ocr_multi(exe, strip, c['top'], c['bot'], work, 'label', (3, 5))]
        rows = []                                        # the words of one name stand on one line
        for w in sorted(words, key=lambda w: w[1]):
            if rows and abs(w[1] - rows[-1][0]) < 1.2 * unit:
                rows[-1][1].append(w)
            else:
                rows.append([w[1], [w]])
        labels = [None] * len(c['staves'])
        centres = [(a + b) / 2 for a, b in c['staves']]
        beside = [[] for _ in centres]                   # the lines of text beside each staff, top to bottom
        for y, ws in rows:
            text = ' '.join(w[4] for w in sorted(ws, key=lambda w: w[2]))
            if label_role(text) == 'P' and len(centres) >= 2:        # a keyboard's name stands between its two staves
                gaps = [(abs(y - (c['staves'][i][1] + c['staves'][i + 1][0]) / 2), i) for i in range(len(centres) - 1)]
                d, i = min(gaps)
                if d < 3.5 * unit:
                    labels[i] = labels[i + 1] = 'P'
                    continue
            d, i = min((abs(y - cy), i) for i, cy in enumerate(centres))
            if d < 3 * unit:
                beside[i].append(text)
        for i, lines in enumerate(beside):
            if labels[i] is not None or not lines:
                continue
            role = label_role(' '.join(lines))           # "Tenor" with I above and II below it, "Baritone" over "Bass": one name in several lines
            if role is None:
                for r in filter(None, map(label_role, lines)):
                    if role is None or role == r:
                        role = r
                    elif {role, r} <= {'T1', 'T2', 'TEN'}:           # two names beside one staff: it carries both parts
                        role = 'TEN'
                    elif {role, r} <= {'BR', 'BS', 'BASS', 'LOW'}:
                        role = 'LOW'
            labels[i] = role
        c['labels'] = labels
        if 'P' in labels:                                # the names know better than the staff finder which two staves are the keyboard's
            c['kinds'] = ['p' if t == 'P' else 'v' for t in labels]
        elif c.get('kinds'):
            c['kinds'] = ['v' if t in ('T1', 'T2', 'BR', 'BS', 'TEN', 'BASS', 'LOW', 'SOLO', 'I', 'D') else k for t, k in zip(labels, c['kinds'])]


BOTTOM = {('G', 2): 30, ('G', 1): 32, ('F', 4): 18, ('F', 3): 20, ('C', 3): 24, ('C', 4): 22, ('C', 1): 28}    # each clef's bottom line, in steps up from C0


def reclef(st, sign):
    """A staff whose clef sign was misread: every note put back where it stands under the clef the staff really has.
    A note that followed the key keeps following it; one with its own accidental keeps that accidental."""
    was = BOTTOM.get((st['clef'], int(st.get('line') or 0)), BOTTOM[{'G': ('G', 2), 'F': ('F', 4)}.get(st['clef'], ('C', 3))])
    d = BOTTOM[('G', 2) if sign == 'G' else ('F', 4)] - was
    fifths = st.get('key') or 0
    in_key = lambda step: (1 if 'FCGDAEB'.index(step) < fifths else 0) if fifths > 0 else (-1 if 'BEADGCF'.index(step) < -fifths else 0)
    for m in st['measures']:
        for n in m['notes']:
            if n['midi'] is None or not n.get('step'):
                continue
            pos = n['oct'] * 7 + 'CDEFGAB'.index(n['step']) + d
            step, octv = 'CDEFGAB'[pos % 7], pos // 7
            alter = in_key(step) if n['alter'] == in_key(n['step']) else n['alter']
            n.update(step=step, oct=octv, alter=alter, midi=12 * (octv + 1) + 'C D EF G A B'.index(step) + alter, name=name_of(step, alter, octv))
    st['clef'], st['line'] = sign, None


def fix_clefs(crops, log):
    """A voice keeps its clef through a piece.  Where one system shows a part's staff under another clef than
    that part has everywhere else, the sign was misread - and every note on the staff with it, by a sixth or
    more.  The notes are moved to where the part's usual clef puts them."""
    seen = {}
    one = all(sum(r == 'I' for r in c.get('roles') or []) <= 1 for c in crops)      # (two instruments are two parts under one name here)
    for c in crops:
        for st, role in zip(c['read'], c.get('roles') or []):
            if (role in ('T1', 'T2', 'BR', 'BS', 'TEN', 'LOW') or role == 'I' and one) and st['clef']:
                seen.setdefault(role, []).append(st['clef'])
    for c in crops:
        for st, role in zip(c['read'], c.get('roles') or []):
            signs = seen.get(role)
            if not signs or not st['clef'] or len(signs) < 4:
                continue
            usual = max(sorted(set(signs)), key=signs.count)
            if st['clef'] != usual and usual in ('G', 'F') and signs.count(usual) >= .75 * len(signs) and \
                    any(n.get('step') for m in st['measures'] for n in m['notes']):
                log(f"  page {c['page']} system {c['system']}: the {role} staff was read under a {st['clef']} clef, but that part is written "
                    f"under a {usual} clef everywhere else: its notes are moved to where that clef puts them")
                reclef(st, usual)


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
    # ---- the printed names, where there are any, say it better than counting staves does
    known_sets = {}
    has_instrument = any(t in ('I', 'D') for c in crops for t in (c.get('labels') or []))
    for i, c in enumerate(crops):
        labels = c.get('labels')
        if labels:
            labels = [t for t in labels if t != 'P']     # the voices' and instruments' staves, top to bottom
        nv = voc[i]
        clefs = tuple(st['clef'] for st in c['read'][:nv])
        if not labels or not any(labels[:nv]):
            labels = known_sets.get((nv, clefs))         # no names on this system: the last system that looked like it
            if not labels:
                continue
        else:
            known_sets[(nv, clefs)] = labels
        tags = list(labels[:nv])
        if not any(t in ('I', 'D', 'T1', 'T2', 'BR', 'BS', 'TEN', 'BASS', 'LOW', 'SOLO') for t in tags):
            continue
        if has_instrument and sum(t is None for t in tags) == 1 and sum(t in ('T1', 'T2', 'BR', 'BS', 'TEN', 'BASS', 'LOW') for t in tags) >= 2:
            tags = ['I' if t is None else t for t in tags]
        sung = [k for k, t in enumerate(tags) if t not in ('I', 'D')]
        has_bar = any(t == 'BR' for t in tags); n_bass = sum(t in ('BASS', 'BS', 'BR') for t in tags)
        roles = list(c['roles'][:nv])
        if any(t in ('I', 'D') for t in tags):           # with the instruments set aside, count the voices again
            base = {1: ['ALL'], 2: ['TEN', 'LOW'], 3: ['SOLO', 'TEN', 'LOW'], 4: ['T1', 'T2', 'BR', 'BS']}.get(len(sung))
            for k in range(nv):
                roles[k] = 'D' if tags[k] == 'D' else 'I'
            for j, k in enumerate(sung):
                roles[k] = base[j] if base else '?'
        for k, t in enumerate(tags):
            if t in ('T1', 'T2', 'BR', 'BS', 'SOLO'):
                roles[k] = t
            elif t == 'TEN':
                roles[k] = 'TEN'
            elif t == 'BASS':                            # "Bass" under a "Baritone" is the second basses; alone it is all the low voices
                roles[k] = 'BS' if has_bar or n_bass > 1 else 'LOW'
            elif t == 'LOW':
                roles[k] = 'LOW'
        if len(set(r for r in roles if r not in ('I', 'D'))) == len([r for r in roles if r not in ('I', 'D')]):
            c['roles'] = roles + c['roles'][nv:]


def has_piano(crops, pages, exe, work):
    """Are the two lowest staves a piano?  Not if they are sung from: words printed under the lowest one, or between
    the two.  A treble and a bass staff joined by a brace look like a keyboard's to the staff finder, and are one
    in most music; in unaccompanied music they are the choir's, and the words between them say so."""
    seen = any('p' in ''.join(c.get('kinds') or []) for c in crops if len(c['staves']) >= 3)   # a grand staff under other staves
    big = [c for c in crops if len(c['read']) >= 3][:4]
    if not big or not exe:
        return True if seen else None
    sung = between = 0
    for c in big:
        img = np.asarray(Image.open(pages[c['page'] - 1]).convert('L'))
        on_page(c['page'], img)
        top, bot = c['staves'][-1]
        unit = (bot - top) / 4
        words = ocr_words(exe, img, bot + .6 * unit, min(c['bot'], bot + 7 * unit), work, 'piano')
        mid = ocr_words(exe, img, c['staves'][-2][1] + .6 * unit, top - 1.0 * unit, work, 'piano')
        lyric = lambda ws: sum(1 for w in ws if re.search('[aeiou]', w[4].lower()) and len(w[4]) > 1 and not NOT_LYRICS.match(w[4]) and not CHORD.match(w[4]))
        sung += lyric(words) >= 3 or lyric(mid) >= 3; between += lyric(mid) >= 3
    if seen:                                         # the staff finder saw a keyboard: only a line of words inside it says otherwise
        if between <= len(big) / 2:
            return True
        for c in crops:
            if c.get('kinds'):
                c['kinds'] = ['v'] * len(c['kinds'])
        return False
    return sung < len(big) / 2


# Words that tell Latin from English when nobody has said which is sung: the common words of the Mass and the prayers
# set most often (whole or put together from their printed syllables), against the small words no English text is without.
LATIN_WORDS = set("""sanctus dominus domini domine deus dei deo excelsis hosanna osanna benedictus benedicta gratia plena sabaoth
    pleni sunt caeli coeli terra tua tuae tui tuum agnus peccata mundi miserere nobis dona pacem kyrie eleison christe mater ora nunc
    hora mortis nostrae mulieribus fructus ventris angelus ancilla verbum caro factum habitavit secundum fiat mihi spiritu sancto
    sancta concepit nuntiavit ecce laudamus adoramus glorificamus venit nomine qui est et cum pro""".split())
ENGLISH_WORDS = set("""the and of to you that it we for on with all my be is are was this your our his her they have will not when what
    from by at as so no night day love""".split())


def assemble(crops, pages, work, title, tempo, language, log, marked=False):
    exe = 'pdf-text' if TEXT['pages'] else ocr_cmd(work)
    if not exe:
        log('  ! no text recognition here (macOS has its own; elsewhere install Tesseract): the notes will have no words')
    piano = has_piano(crops, pages, exe, work)
    if piano is False:
        log('  no piano part: words are printed under the lowest staff')
    staff_labels(crops, pages, exe, work)
    roles_for(crops, piano)
    fix_clefs(crops, log)
    lone = [c for c in crops if c['read'] and c.get('roles') and all(r in ('I', 'D') for r in c['roles'])]
    if lone and len(lone) < len(crops):
        log(f"  {len(lone)} system(s) are an instrument's part alone (printed after the score): left out")
        for c in lone:
            c['read'] = []
    # ---- an instrument's staff in the score (a clarinet over the choir): the accompaniment plays its line, which is the
    # tune wherever the choir is silent.  Not one written in another key than the choir's - a part for a transposing
    # instrument, which sounds elsewhere than it is written.
    apart = []
    for c in crops:
        rs = c.get('roles') or []
        others = [st['key'] for st, r in zip(c['read'], rs) if r not in ('I', 'D') and st.get('key') is not None]
        apart += [st['key'] - max(sorted(set(others)), key=others.count) for st, r in zip(c['read'], rs) if r == 'I' and st.get('key') is not None and others]
    n_inst = sum(r == 'I' for c in crops if c['read'] for r in c.get('roles') or [])
    play_inst = not apart or max(sorted(set(apart)), key=apart.count) == 0
    if n_inst:
        log(f"  an instrument's staff is printed in {sum(any(r == 'I' for r in c.get('roles') or []) for c in crops if c['read'])} system(s): "
            + ('the accompaniment plays its line  (the IN: lines of the score - delete them to leave it out)' if play_inst else
               "it is written in another key than the choir's (a transposing instrument), so it is left out"))
    out, num, cur_time, length = [], 0, None, Fraction(4)
    paces, mlen, holds, worded = set(), {}, {}, False       # "rall."/"a tempo" marks; each measure's length; fermatas; a tempo given in words
    imgs = {}
    def read_texts(c, img, M):
        texts = {}
        for si, role in enumerate(c['roles'][:len(c['read'])]):
            if role in ('RH', 'LH', 'I', 'D') or not exe or si >= len(c['staves']):
                continue
            top, bot = c['staves'][si]
            unit = (bot - top) / 4
            nxt = c['staves'][si + 1][0] if si + 1 < len(c['staves']) else c['bot']
            tag = f"{c['page']}_{c['system']}_{si}"
            loose = ocr_multi(exe, img, bot + .6 * unit, min(nxt - 1.2 * unit, bot + 9 * unit), work, tag, (2, 3, 6))
            tall = TEXT.get('tall') or 0.                  # large print under a small staff: a line is as tall as its letters
            near = max(1.2 * unit, .6 * tall)
            loose = [w for w in loose if re.search('[A-Za-z]', w[4]) and '(' not in w[4] and not NOT_LYRICS.match(w[4])]
            if not loose and si + 1 == len(c['staves']):       # nothing under the lowest staff as far as half way to the next system:
                under = [o['staves'][0][0] for o in crops if o['page'] == c['page'] and o['staves'] and o['staves'][0][0] > bot]
                far = min(min(under) - 2.5 * unit, bot + 9 * unit) if under else 0     # where systems stand close, the words are past half way
                if far > nxt - 1.2 * unit:
                    loose = ocr_multi(exe, img, bot + .6 * unit, far, work, tag, (2, 3, 6))
                    loose = [w for w in loose if re.search('[A-Za-z]', w[4]) and '(' not in w[4] and not NOT_LYRICS.match(w[4])]
            ys = []
            for w in sorted(loose, key=lambda w: w[1]):
                if not any(abs(w[1] - y) < near for y in ys):
                    ys.append(float(np.median([v[1] for v in loose if abs(v[1] - w[1]) < near])))
            def prose(row, more=False):  # running text - a footnote, "slide on beat": its words stand a space apart, every gap
                if len(row) < (2 if more else 3):     # alike.  Lyrics are spread under their notes, and no two gaps are the same.
                    return False
                row = sorted(row, key=lambda w: w[2])
                gaps = [b[2] - a[3] for a, b in zip(row, row[1:])]
                wide = float(np.mean([(w[3] - w[2]) / max(1, len(w[4])) for w in row]))           # of one letter
                return max(gaps) < .6 * wide and (more or max(gaps) <= 2 * max(float(np.median(gaps)), .1 * wide))
            every = list(ys)
            told = [yc for yc in ys if prose([w for w in loose if abs(w[1] - yc) < near])]
            if told:                     # beneath a line of it, a line set as tight is more of the same (the ragged end of a footnote)
                gone = [yc for yc in ys if yc in told or yc > min(told) and prose([w for w in loose if abs(w[1] - yc) < near], True)]
                log(f"  page {c['page']} system {c['system']}: {len(gone)} line(s) under the {role} staff are running text, not words to sing"
                    f"  (\"{' '.join(w[4] for w in sorted((w for w in loose if abs(w[1] - min(told)) < near), key=lambda w: w[2]))[:40]}\")")
                ys = [yc for yc in ys if yc not in gone]
                loose = [w for w in loose if any(abs(w[1] - yc) < near for yc in ys)]
            words = []
            for yc in ys:                # each line of text read again by itself, close up: that brings out the
                half = min([max(1.3 * unit, .75 * tall)] + [.5 * abs(yc - y) for y in every if y != yc])   # small syllables
                tight = [w for w in ocr_multi(exe, img, yc - half, yc + half, work, tag, (3, 4, 6)) if re.search('[aeiouyAEIOUY]', w[4]) or w[4] in '-–—']
                row = [w for w in loose if abs(w[1] - yc) < near]
                line = [w[:1] + (yc,) + w[2:] for w in tight]
                line += [w[:1] + (yc,) + w[2:] for w in row if not any(w[2] < t[3] and t[2] < w[3] for t in tight)]   # what only the first look saw
                said = [w[4] for w in line if re.search('[A-Za-z0-9]', w[4])]
                if said and any(PART_NAME.match(t) for t in said) and all(PART_NAME.match(t) or PART_NUMBER.match(t) for t in said):
                    log(f"  page {c['page']} system {c['system']}: \"{' '.join(said)}\" under the {role} staff is a staff's name, not words to sing")
                    continue
                words += line
            if 'bars' not in c:
                c['bars'] = barlines(img, c['staves'], c['x0'], c['x1'], 'RH' in c['roles'], expect=M)
                c['bars_found'] = len(c['bars']) == M + 1
                if len(c['bars']) != M + 1:
                    log(f"  ? page {c['page']} system {c['system']}: found {len(c['bars']) - 1} measures on the page but {M} were read; words placed by even spacing")
                    c['bars'] = list(np.linspace(c['x0'], c['x1'], M + 1))
            bars = c['bars']
            c.setdefault('printed', {})[si] = every       # every line of print under the staff, sung or not: where a closer look must stop
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
    if not language:                                # nobody has said what language is sung: Latin is known by its words
        lat = eng = 0
        for c in crops:
            for lines, *_ in c.get('texts', {}).values():
                for line in lines:
                    k_ = [re.sub('[^a-z]', '', t.lower()) for _, t in line]
                    whole = [not t.endswith('-') and (i == 0 or not line[i - 1][1].endswith('-')) for i, (_, t) in enumerate(line)]
                    eng += sum(w and k in ENGLISH_WORDS for k, w in zip(k_, whole))
                    lat += sum(''.join(k_[i:i + n]) in LATIN_WORDS for i in range(len(k_)) for n in (1, 2, 3, 4, 5) if i + n <= len(k_))
        if lat >= 8 and lat > 3 * eng:
            language = 'latin'
            log(f'  the words are Latin ({lat} Latin words against {eng} English ones): they will be sung as church Latin  (--language english if that is wrong)')
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
    endings = []                                    # numbered endings: (the measure each begins at, the passes it is for)
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
            if c.get('bars') is not None and len(c['bars']) == M + 1:
                bars0 = list(c['bars'])                  # known exactly
            else:
                bars0 = barlines(img, c['staves'], c['x0'], c['x1'], 'RH' in c['roles'])
                bars0 = bars0 if len(bars0) == M + 1 else list(np.linspace(c['x0'], c['x1'], M + 1))
            line = ' '.join(w[4] for w in sorted(above, key=lambda w: w[2]))
            nav += navigation(above, find_segno(img, max(c['top'], top - 9 * unit0), top - .2 * unit0, unit0), bars0, num + 1, unit0)
            over = [o['staves'][-1][1] for o in crops if o['page'] == c['page'] and o['staves'] and o['staves'][-1][1] < top]   # the staff above, on this page
            y_from = max(over) + .6 * unit0 if over else top - 9 * unit0
            for bx, by, bx1 in find_endings(img, y_from, top - .3 * unit0, unit0):
                which = ending_passes(exe, img, bx, by, unit0, work, f"{c['page']}_{c['system']}_e")
                if which:
                    endings.append((num + 1 + int(np.clip(np.searchsorted(bars0, bx + 1.5 * unit0) - 1, 0, M - 1)), tuple(which)))
            rows_t = []                              # line by line: a triplet's "3" on the staff must not come between "=" and its number
            for w in sorted(above, key=lambda w: w[1]):
                if rows_t and abs(w[1] - rows_t[-1][0]) < 1.2 * unit0:
                    rows_t[-1][1].append(w)
                else:
                    rows_t.append([w[1], [w]])
            for _, ws in rows_t:
                row = ' '.join(w[4] for w in sorted(ws, key=lambda w: w[2]))
                for mm in re.finditer(r'=\s*(?:ca\.?\s*)?(\d{2,3})', row):
                    if re.search(r'(?:^|\s)(?:p{1,3}|m[pf]|f{1,3}|s?fz?|fp)\s*$', row[:mm.start()]):
                        continue                         # after a dynamic stand hairpins, which read as "= 72" as easily as a mark does
                    if 30 <= int(mm.group(1)) <= 240:
                        num_w = next((w for w in ws if mm.group(1) in w[4]), None)
                        xw = min([w[2] for w in ws if num_w and num_w[2] - 32 * unit0 < w[2] <= num_w[2]] or [c['x0']])
                        marks[max(0, int(np.searchsorted(bars0, xw + 2 * unit0)) - 1)] = float(mm.group(1))
            if re.search(r'Tempo\s+I\b', line) and tempo:
                xw = next((w[2] for w in above if w[4].startswith('Tempo')), c['x0'])
                marks[max(0, int(np.searchsorted(bars0, xw)) - 1)] = float(tempo)
            before = [o for o in crops if o['page'] == c['page'] and o['staves'] and o['staves'][-1][1] < top]      # the system above, on this page
            ceiling = max([o['staves'][-1][1] + 2.5 * unit0 for o in before] + [top - 16 * unit0, 0])
            high = ocr_words(exe, img, ceiling, max(ceiling, top - .3 * unit0), work, 'tempo') if TEXT['pages'] else []
            rows_h = {}                              # a heading may stand well above the staff: a PDF's own text costs nothing to look through
            for w in high:
                rows_h.setdefault(round(w[1] / (1.2 * unit0)), []).append(w)
            for ws in [ws for _, ws in rows_t] + list(rows_h.values()):      # no number, but a word for it
                if not re.search(r'=\s*(?:ca\.?\s*)?\d{2,3}', ' '.join(w[4] for w in ws)):
                    for xw, bpm in tempo_words(ws):
                        marks.setdefault(max(0, int(np.searchsorted(bars0, xw + 2 * unit0)) - 1), bpm); worded = True
            if not marks and not TEXT['pages']:
                # On a scan a heading's two words can come back at different heights and with a staff's name before
                # them and a dynamic after ("Trio Quietly flowing p"): words that follow one another along a line,
                # whatever row each was put in, are tried together once more.
                run = []
                for w in sorted((w for w in above if re.search('[A-Za-z]', w[4])), key=lambda w: w[2]) + [None]:
                    if w is not None and run and 0 <= w[2] - run[-1][3] < 3 * unit0 and abs(w[1] - run[-1][1]) < 1.2 * unit0:
                        run.append(w)
                        continue
                    for xw, bpm in tempo_words(run) if len(run) > 1 else []:
                        marks.setdefault(max(0, int(np.searchsorted(bars0, xw + 2 * unit0)) - 1), bpm); worded = True
                    run = [w]
            # "rall." ... "a tempo", wherever in the system they are printed (each staff may carry its own copy)
            if TEXT['pages']:
                inside = sorted(ocr_words(exe, img, c['top'], c['bot'], work, 'pace'), key=lambda w: (round(w[1] / (2 * unit0)), w[2]))
                for k_, w in enumerate(inside):
                    t_ = w[4].lower().strip('.,')
                    kind = 'slow' if t_ in ('rall', 'rit', 'ritard', 'riten', 'ritenuto', 'rallentando', 'ritardando') else \
                        'back' if t_ == 'tempo' and k_ and inside[k_ - 1][4].lower() == 'a' and 0 <= w[2] - inside[k_ - 1][3] < 3 * unit0 else None
                    if kind:
                        xw = inside[k_ - 1][2] if kind == 'back' else w[2]
                        j_ = min(max(0, int(np.searchsorted(bars0, xw + unit0)) - 1), M - 1)
                        ons = [n['on'] for st in c['read'] if j_ < len(st['measures']) for n in st['measures'][j_]['notes'] if n.get('x') is not None and n['x'] >= xw - 2.5 * unit0]
                        paces.add((num + j_ + 1, min(ons) if ons else None, kind))
        plan = []
        for j in range(M):
            # How long is this measure?  Count it: the total most voices agree on.  (The printed time signature is
            # read too, but it is the less reliable of the two, and most systems do not print one at all.)
            # A voice that is one rest and nothing else says nothing: the reader gave that rest the length it took
            # the measure to have.  It may agree with a voice that has notes, not outvote one.
            totals, idle = [], []
            for st in c['read']:
                if j < len(st['measures']):
                    by_voice, heads = {}, {}
                    for n in st['measures'][j]['notes']:
                        if not n['chord']:
                            by_voice[n['voice']] = by_voice.get(n['voice'], Fraction(0)) + n['ql']
                            heads.setdefault(n['voice'], []).append(n['midi'])
                    for v_, t_ in by_voice.items():
                        if t_ > 0:
                            (idle if heads[v_] == [None] else totals).append(t_)
            totals += [t_ for t_ in idle if not totals or t_ in totals]
            labels = [st['measures'][j]['time'] for st in c['read'] if j < len(st['measures']) and st['measures'][j]['time']]
            as_len = lambda lab: Fraction(int(lab.split('/')[0]) * 4, int(lab.split('/')[1]))
            exact = [st['measures'][j].get('len') for st in c['read'] if j < len(st['measures'])]
            if exact and all(exact):                 # read from the PDF's own symbols: the length is known, not counted
                length = exact[0]
            elif totals:
                best = max(set(totals), key=lambda v: (totals.count(v), v == length, v))
                if best != length and (totals.count(best) >= 2 or any(as_len(l) == best for l in labels)):
                    length = best
            t = next((l for l in labels if as_len(l) == length), None) or (cur_time if cur_time and as_len(cur_time) == length else None) \
                or (f'{int(length)}/4' if length == int(length) else f'{int(length * 2)}/8')
            plan.append((length, t))
        # ---- the words of the whole system, put on its notes by where both stand on the page
        sylmap = {}
        for si, role in enumerate(c['roles'][:len(c['read'])]):
            if role in ('RH', 'LH', 'I', 'D') or si not in texts or not texts[si][0]:
                continue
            lines, bars, unit, ys = texts[si]
            for v in (0, 1):
                row = v if v < len(lines) else 0                 # one line of words serves both voices
                slots, per = [], []
                for j in range(M):
                    stm = c['read'][si]['measures']
                    if j < len(stm) and any(n['midi'] is not None for n in stm[j]['notes']):
                        line = lines_of(stm[j]['notes'], plan[j][0])[v]
                        per.append((j, [n for n, a_, b_ in line if n is not None and a_ == n['on'] and not n.get('tied_from') and n.get('x') is not None]))
                        xs_ = [n['x'] for n in per[-1][1]]
                        if c.get('bars_found') and (any(x < bars[j] - unit or x > bars[j + 1] + unit for x in xs_) or any(b_ <= a_ for a_, b_ in zip(xs_, xs_[1:]))):
                            for n in per[-1][1]:     # notes out of order or outside their measure: the reader lost its place on the
                                n['x'] = bars[j] + (.1 + .85 * float(n['on'] / plan[j][0])) * (bars[j + 1] - bars[j])     # page; when a note sounds says where it stands
                        slots += per[-1][1]
                got = place_x(slots, lines[row], unit)
                # A measure with exactly as many syllables under it as it has notes to sing them: one each, in order.
                # (Where a note stands on the page is the reader's estimate, and can be half a note off; a count is a count.)
                if c.get('bars_found'):
                    for j, mine in per:
                        here = [w for w in lines[row] if bars[j] <= w[0] < bars[j + 1]]
                        free = [n for n in mine if not n.get('melisma')]
                        to = free if len(here) == len(free) else mine if len(here) == len(mine) else None
                        if to and len(here) >= 2:
                            for n in mine:
                                got.pop(id(n), None)
                            for n, w in zip(to, here):
                                got[id(n)] = w[1]
                if exe and row < len(ys):                        # a note with no word under it: look there again, close up
                    half = min([1.3 * unit] + [.5 * abs(ys[row] - y) for y in c.get('printed', {}).get(si, ys) if y != ys[row]])
                    taken = sorted(w[0] for w in lines[row])
                    for n in slots:
                        if id(n) in got or n.get('melisma'):
                            continue
                        if any(abs(x - n['x']) < 1.3 * unit for x in taken):
                            continue
                        x_a, x_b = int(max(0, n['x'] - 3.4 * unit)), int(n['x'] + 3.4 * unit)
                        again = ocr_words(exe, img[:, x_a:x_b], ys[row] - half, ys[row] + half, work, 'note', zoom=6)
                        again = [(w[0] + x_a, w[1], w[2] + x_a, w[3] + x_a, w[4]) for w in again]
                        found = [w for l_ in syllables(again, unit, img) for w in l_ if abs(w[0] - n['x']) < 1.7 * unit and re.fullmatch(r"[A-Za-z']+[-.,;:!?]*", w[1])
                                 and not any(abs(w[0] - x) < 1.3 * unit for x in taken)]       # not a syllable the first look saw: that one is another note's
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
            mlen[num] = length
            ferm = sorted({(Fraction(a_), Fraction(a_) + Fraction(b_)) for st in c['read'] if j < len(st['measures']) for a_, b_ in st['measures'][j].get('fermata', [])})
            while ferm:                              # signs over notes that sound together are one fermata: it lasts while all of them sound
                a_, b_ = ferm.pop(0)
                while ferm and ferm[0][0] < b_:
                    a2, b2 = ferm.pop(0); a_, b_ = max(a_, a2), min(b_, b2)
                if b_ > a_:
                    extra = min(max(1.2 * float(b_ - a_), 1.), 1.6)          # a fermata adds about a beat, a beat and a half
                    holds.setdefault(num, []).append((float(a_) + 1, float(b_ - a_), 1 + extra / float(b_ - a_)))
            out.append(f'== {num}'); n_in = 0
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
                if role == 'D' or role == 'I' and not play_inst:
                    continue
                if role == 'I':                      # an instrument's staff: not sung, played (two voices of it at most, four lines a measure)
                    for _, toks in instrument_lines(notes, length):
                        if n_in < 4:
                            n_in += 1
                            out.append(('IN' if n_in == 1 else f'IN{n_in}') + ': ' + ' '.join(toks))
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
                if role == 'SOLO' and st.get('octave') == -1:        # a clef with an 8 under it (known when the symbols are read exactly)
                    shift = -1
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
    # ---- slowing down: from each "rall." to the "a tempo" that follows it (or for two measures; to the end if it is the last)
    start, total = {}, Fraction(0)
    for n_ in range(1, num + 1):
        start[n_] = total; total += mlen.get(n_, Fraction(4))
    spots = sorted({(start[m_] + (on_ if on_ is not None else 0), kind) for m_, on_, kind in paces if m_ in start})
    slowing = False
    for i_, (a_, kind) in enumerate(spots):
        if kind != 'slow' or slowing:                # (each staff may print its own "rall.": the first one counts)
            slowing = slowing and kind == 'slow'
            continue
        slowing = True
        later = [b_ for b_, k_ in spots[i_ + 1:] if b_ > a_ and k_ == 'back']
        last = not later and total - a_ <= 12
        b_ = min([later[0]] if later else [total if last else a_ + 8], key=float)
        b_ = min(b_, a_ + 12)
        step = Fraction(1) if b_ - a_ >= 3 else Fraction(1, 2)
        n_steps = max(1, int((b_ - a_) / step))
        for k_ in range(n_steps):
            s0 = a_ + k_ * step; s1 = b_ if k_ == n_steps - 1 else s0 + step
            factor = 1 + (.6 if last else .3) * (k_ + 1) / n_steps
            for m_ in range(1, num + 1):               # a step is written measure by measure
                lo_, hi_ = max(s0, start[m_]), min(s1, start[m_] + mlen[m_])
                if hi_ > lo_:
                    holds.setdefault(m_, []).append((float(lo_ - start[m_]) + 1, float(hi_ - lo_), round(factor, 3)))
    for m_, hs in holds.items():
        at_ = out.index(f'== {m_}')
        out[at_:at_] = ['stretch: %g %g %g' % h for h in sorted(hs)]
    if unit != 1 and (marked or worded):        # a metronome mark counts the beat: half notes in 2/2, dotted quarters in 6/8
        tempo *= unit
        out = [re.sub(r'^tempo: (\S+)$', lambda m_: 'tempo: %g' % (float(m_.group(1)) * unit), l) for l in out]
    one = out.index('== 1') if '== 1' in out else 0
    opening = [i_ for i_, l in enumerate(out[:one]) if re.match(r'^tempo: \S+$', l)]
    if opening:                                      # a tempo found at the very beginning is the piece's tempo
        tempo = float(out[opening[-1]].split()[1])
        out = [l for i_, l in enumerate(out) if i_ not in opening]
    head = [f'title: {title}', f'tempo: {tempo:g}', f"time: {first_time}", 'key: 0',
            'transpose: TEN -12', 'transpose: TRIO -12'] + ([f'language: {language}'] if language else []) + ['']
    first = next((i for i, l in enumerate(out) if l.startswith('time: ')), None)
    if first is not None:
        out.pop(first)
    endings = sorted(set(endings))
    order = performed(num, nav, rep_starts, rep_ends, endings)
    if nav or rep_ends:
        found = sorted(set(nav), key=lambda x: x[1]) + [('repeat', f'{a_}-{b_}') for b_ in sorted(rep_ends) for a_ in [max([x for x in rep_starts if x <= b_] or [1])]]
        found += [('ending ' + ', '.join(map(str, which)), m_) for m_, which in endings]
        log('  on the page: ' + ', '.join(f'{what} at {m}' for what, m in found))
        head.insert(-1, '// found on the page: ' + ', '.join(f'{what} at {m}' for what, m in found))
        if order and order != list(range(1, num + 1)):
            head.insert(-1, 'play: ' + ranges(order) + '      // the order the printed measures are performed in - correct it here if it is wrong')
        elif any(w.startswith('ds') for w, _ in nav) and not any(w == 'segno' for w, _ in nav):
            log('  ! a D.S. is printed but its sign was not found: add a  play:  line to the score by hand')
    return '\n'.join(head + out) + '\n'


TEMPO_WORDS = sorted({'very slow': 48, 'very slowly': 48, 'moderately slow': 72, 'moderately slowly': 72, 'slowly': 60, 'slow': 60, 'tenderly': 69,
                      'gently': 76, 'flowing': 88, 'quietly flowing': 72, 'gently flowing': 76, 'freely': 63, 'rubato': 63, 'ballad': 66, 'moderately fast': 120, 'moderately bright': 120,
                      'moderately': 96, 'moderate': 96, 'medium': 100, 'very fast': 168, 'fast': 144, 'bright': 132, 'brightly': 132, 'lively': 132,
                      'briskly': 132, 'with spirit': 126, 'majestically': 84, 'grave': 42, 'largo': 48, 'larghetto': 60, 'lento': 54, 'adagio': 63,
                      'andantino': 84, 'andante': 76, 'moderato': 104, 'allegretto': 112, 'allegro': 128, 'vivace': 152, 'presto': 176,
                      'maestoso': 84}.items(), key=lambda kv: -len(kv[0]))


def tempo_words(ws):
    """A tempo given in words at the head of a line of text ("Moderately slow", "Andante") -> [(x, beats a minute)].
    It has to begin with a capital, as such a heading does and a word of the lyrics rarely does."""
    out = []
    ws = sorted((w for w in ws if not w[4].strip('.').isdigit()), key=lambda w: w[2])
    if len(ws) > 4:                                  # a heading stands by itself; a line of many words is something else
        return out
    i = 0
    while i < len(ws):
        text = re.sub(r'[^a-z ]', '', ' '.join(w[4] for w in ws[i:i + 3]).lower())
        hit = next(((p, v) for p, v in TEMPO_WORDS if text == p or text.startswith(p + ' ')), None) if ws[i][4][:1].isupper() else None
        if hit:
            out.append((ws[i][2], float(hit[1]))); i += len(hit[0].split())
        else:
            i += 1
    return out


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
        elif exe == 'tesseract':
            text = ' '.join(w[4] for w in _tesseract(p))
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
    ap.add_argument('--exact-only', action='store_true', help='read the notes from the PDF\'s own symbols or not at all (exit code 3)')
    a = ap.parse_args()
    work = a.work or os.path.splitext(a.out)[0] + '.scan'
    os.makedirs(work, exist_ok=True)
    pages = render_pages(a.pdf, work)
    words = pdf_words(a.pdf)
    every = [w[4] for v in words.values() for w in v]
    plain = sum(1 for t in every if re.fullmatch(r"[A-Za-z][A-Za-z'’.,;:!?-]*|[-–—]|\d{1,3}", t))
    if len(every) >= 12 * len(pages) and plain >= .8 * len(every):   # a PDF with its words in it: no need to read them off the picture
        TEXT['pages'] = words
        print("the words are taken from the PDF's own text")
    elif len(every) >= 12 * len(pages):                              # text is there, but stored under codes that mean nothing outside the file
        print("the PDF's own text cannot be read as words (its fonts are stored under private codes): reading the words off the page instead")
    crops = None
    try:                                             # a PDF drawn with a standard music font is read exactly, symbol by symbol
        import vector2score
        crops = vector2score.read(a.pdf, log=print)
    except Exception as e:
        print(f'  (reading the symbols directly did not work: {e}; recognizing the pages instead)')
    if crops is None and a.exact_only:
        sys.exit(3)
    drawn = crops is not None                       # exported from notation software, not a picture of a page
    if crops is None:
        crops = join_split_systems(read_systems(cut_systems(pages, work, print), print))
    found = None if a.tempo else find_tempo(pages, work)
    # With no tempo on the page: notation software plays an unmarked score at 120 to the quarter, so that is what
    # whoever exported this heard.  A printed page with no tempo at all is rare, and 100 offends least.
    guess = 120. if drawn else 100.
    tempo = a.tempo or found or guess
    named = re.sub(r'\s+', ' ', re.sub(r'_+|(?<=\w)-(?=\w)', ' ', os.path.splitext(os.path.basename(a.pdf))[0])).strip()    # the file's name, as its owner wrote it
    title = a.title or (pdf_title(a.pdf) if TEXT['pages'] else None) or (named if named != named.lower() else named.title())
    text = assemble(crops, pages, work, title, tempo, a.language, print, marked=found is not None)
    open(a.out, 'w').write(text)
    began = re.search(r'^tempo: (\S+)', text, re.M)
    print(f'wrote {a.out}: {sum(len(c["read"][0]["measures"]) for c in crops if c["read"])} measures from {len(crops)} systems, tempo {began.group(1) if began else tempo}'
          + ('' if a.tempo or found or 'tempo: ' in text.split('== 1')[-1] or (began and float(began.group(1)) != guess) else
             f' (NO TEMPO IS PRINTED: {guess:.0f} is a guess' + (', the speed notation software plays an unmarked score at' if drawn else '') + ' - set  tempo:  in the score)'))


if __name__ == '__main__':
    main()
