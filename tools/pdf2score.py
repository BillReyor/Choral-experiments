"""Read a vector PDF exported from Finale (Maestro music font) into the score format.

    python tools/pdf2score.py SHEET.pdf OUT.score --staves T1,T2,BR,BS,RH,LH [--tempo 120]

Works only on PDFs where the music is stored as positioned font symbols and line drawings, i.e.
exported straight from notation software.  Scans (pictures of pages) have to be read by eye.

How it reads: staff lines give each staff's position, so a notehead's height is its pitch;
stems tie noteheads into chords; beams and flags crossing a stem give the note value; dots,
accidentals and ties are matched to the nearest notehead; lyric syllables are matched to the note
above them and re-joined into words with a pronouncing dictionary (Finale drops the hyphens).
Every measure is checked to add up; measures that do not are listed for a human to fix.
"""
import argparse, collections, os, re, sys
import numpy as np
import pymupdf
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from choral import lyrics as L

HEADS = {'œ': 1., '˙': 2., 'w': 4.}                      # filled, half, whole
RESTS = {'Œ': 1., '‰': .5, 'Ó': 2., '∑': None, '≈': .25}   # None = whole measure
LETTERS = 'cdefgab'
TOP_LINE = {'&': 38, 'V': 38, '?': 26}                               # diatonic number of the top staff line
DURCODE = {4.: 'w', 3.: 'h.', 2.: 'h', 1.5: 'q.', 1.: 'q', .75: 'e.', .5: 'e', .25: 's', .375: 's.',
           2 / 3: 'q3', 1 / 3: 'e3', 1 / 6: 's3', 6.: 'w.'}


def load_page(page):
    g, lyr, small = [], [], []
    for b in page.get_text('rawdict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                if s['font'] == 'Maestro':
                    g += [(c['c'], c['origin'][0], c['origin'][1]) for c in s['chars'] if c['c'] != ' ']
                else:
                    t = ''.join(c['c'] for c in s['chars']).strip()
                    if not t:
                        continue
                    xs = [c['bbox'][0] for c in s['chars'] if c['c'].strip()] + [c['bbox'][2] for c in s['chars'] if c['c'].strip()]
                    (small if 'Ital' in s['font'] else lyr).append((t, min(xs), max(xs), s['origin'][1], s['size']))
    hl, vl, stems, ledg, beams, curves = [], [], [], [], [], []
    for d in page.get_drawings():
        r = d['rect']; kinds = {it[0] for it in d['items']}
        if 'c' in kinds:
            curves.append(r)
        elif r.height < 1.5 and r.width > 100:
            hl.append(r)
        elif r.height < 1.5:
            ledg.append(r)
        elif r.width < 1.5:
            stems.append(r)          # barlines are separated from stems once the staves are known
        elif d.get('fill') is not None and r.height < 12:
            beams.append(r)
    return g, lyr, small, hl, vl, stems, ledg, beams, curves


def find_staves(hl):
    ys = sorted({round(r.y0, 1) for r in hl})
    staves = []
    for i in range(0, len(ys) - 4, 5):
        x0 = min(r.x0 for r in hl if abs(r.y0 - ys[i]) < .3); x1 = max(r.x1 for r in hl if abs(r.y0 - ys[i]) < .3)
        staves.append(dict(top=ys[i], bot=ys[i + 4], sp=(ys[i + 4] - ys[i]) / 4, x0=x0, x1=x1))
    return staves


def read(pdf, names, warn=print):
    doc = pymupdf.open(pdf)
    per = len(names)
    measures = []          # list of dict part -> list of voices -> list of events
    carry = {}             # staff name -> pending tie pitches across a system break
    stats = collections.Counter()
    for pn, page in enumerate(doc):
        g, lyr, small, hl, vl, stems_all, ledg, beams, curves = load_page(page)
        staves = find_staves(hl)
        tops = [s['top'] for s in staves]; bots = [s['bot'] for s in staves]
        is_bar = lambda r: min(abs(r.y0 - t) for t in tops) < .7 and min(abs(r.y1 - b) for b in bots) < .7
        vl = [r for r in stems_all if is_bar(r)]
        stems_all = [r for r in stems_all if not is_bar(r)]
        for s0 in range(0, len(staves), per):
            sysm = staves[s0:s0 + per]
            if len(sysm) < per:
                break
            ytop, ybot = sysm[0]['top'], sysm[-1]['bot']
            sp = sysm[0]['sp']
            xs = collections.Counter(round(r.x0, 1) for r in vl if r.y0 < ybot + 1 and r.y1 > ytop - 1)
            bars = sorted(xs)
            merged = []
            for x in bars:
                if merged and x - merged[-1] < 8:
                    merged[-1] = x
                else:
                    merged.append(x)
            bars = merged
            if len(bars) < 2:
                continue
            nmeas = len(bars) - 1
            sys_meas = [dict() for _ in range(nmeas)]
            trips = {}
            for si, (st, name) in enumerate(zip(sysm, names)):
                lo = st['top'] - (st['top'] - sysm[si - 1]['bot']) / 2 if si else st['top'] - 16
                hi = st['bot'] + (sysm[si + 1]['top'] - st['bot']) / 2 if si + 1 < per else st['bot'] + 34
                mine = [(c, x, y) for c, x, y in g if lo <= y < hi and bars[0] - 2 < x < bars[-1] + 2]
                clef = next((c for c, x, y in sorted(mine, key=lambda t: t[1]) if c in TOP_LINE), '&')
                first_note_x = min([x for c, x, y in mine if c in HEADS or c in RESTS] + [bars[-1]])
                heads = [dict(ch=c, x=x, y=y, k=int(round((y - st['top']) / (sp / 2)))) for c, x, y in mine if c in HEADS]
                # notehead width from stems
                stems = [r for r in stems_all if lo <= (r.y0 + r.y1) / 2 < hi + 6 and bars[0] < r.x0 < bars[-1]]
                W = 1.18 * sp
                # ---- chords
                for h in heads:
                    h['stem'] = None
                for r in stems:
                    for h in heads:
                        if r.y0 - 2.5 <= h['y'] <= r.y1 + 2.5 and (abs(h['x'] - r.x0) < 1.3 or abs(h['x'] + W - r.x0) < 1.6):
                            h['stem'] = (round(r.x0, 1), round(r.y0, 1), round(r.y1, 1))
                groups = collections.defaultdict(list)
                loose = []
                for h in heads:
                    (groups[h['stem']] if h['stem'] else loose).append(h)
                events = []
                for stem, hs in groups.items():
                    ys = [h['y'] for h in hs]
                    up = bool((stem[1] + stem[2]) / 2 < np.mean(ys))
                    events.append(dict(x=min(h['x'] for h in hs) if not up else stem[0] - W, heads=hs, stem=stem, up=up))
                loose.sort(key=lambda h: h['x'])
                for h in loose:
                    prev = events[-1] if events and events[-1].get('loose') and abs(events[-1]['x'] - h['x']) < 1.6 * W else None
                    if prev:
                        prev['heads'].append(h)
                    else:
                        events.append(dict(x=h['x'], heads=[h], stem=None, up=None, loose=True))
                # ---- note values
                flags = [(x, y) for c, x, y in mine if c in 'jJ']
                dots = [(x, y) for c, x, y in mine if c == '.']
                for e in events:
                    base = min(HEADS[h['ch']] for h in e['heads'])
                    if e['stem'] and base == 1.:
                        sx, sy0, sy1 = e['stem']
                        nb = sum(1 for r in beams if r.x0 - 1 <= sx <= r.x1 + 1 and r.y0 - 1.2 <= sy1 and r.y1 + 1.2 >= sy0)
                        nf = sum(1 for x, y in flags if abs(x - sx) < 2. and sy0 - 4 <= y <= sy1 + 4)
                        base /= 2 ** max(nb, nf)
                        stats['beamed' if nb else 'flagged' if nf else 'quarter'] += 1
                    e['dur'] = base
                    e['dot'] = False
                owner = {id(h): e for e in events for h in e['heads']}
                rest_dots = []
                for dx, dy in dots:
                    cand = [h for h in heads if 3 < dx - h['x'] < 3.4 * W and abs(dy - h['y']) < sp * .62]
                    if cand:
                        owner[id(min(cand, key=lambda h: dx - h['x']))]['dot'] = True
                    else:
                        rest_dots.append((dx, dy))
                for c, x, y in mine:
                    if c in RESTS and x > first_note_x - 1:
                        e = dict(x=x, rest=True, dur=RESTS[c], up=None, heads=[], ry=y)
                        e['dot'] = any(3 < dx - x < 3 * W and abs(dy - y) < sp * 1.2 for dx, dy in rest_dots)
                        events.append(e)
                # ---- accidentals, and the key signature at the start of the system
                keysig = 0
                for c, x, y in mine:
                    if c in '#bn':
                        cand = [h for h in heads if abs(h['y'] - y) < sp * .3 and 2 < h['x'] - x < 4.2 * W]
                        if cand:
                            min(cand, key=lambda h: h['x'] - x)['acc'] = c
                        elif x < first_note_x and x < bars[0] + 60:
                            keysig += {'#': 1, 'b': -1, 'n': 0}[c]
                        else:
                            stats['stray accidental'] += 1
                # ---- ties: a curve from one notehead to the next at the same height
                ordered = sorted(heads, key=lambda h: h['x'])
                for r in curves:
                    if not (lo <= (r.y0 + r.y1) / 2 < hi):
                        continue
                    a = [h for h in heads if abs(h['x'] + W - r.x0) < 1.3 * W and abs(h['y'] - (r.y0 + r.y1) / 2) < 2.2 * sp]
                    if not a:
                        continue
                    a = min(a, key=lambda h: abs(h['x'] + W - r.x0) + abs(h['y'] - (r.y0 + r.y1) / 2))
                    b = [h for h in heads if abs(h['x'] - r.x1) < 1.4 * W and abs(h['y'] - a['y']) < .5 and h is not a]
                    if b or r.x1 > bars[-1] - 6:
                        a['tie'] = True
                    else:
                        a['slur'] = True
                # ---- lyrics under this staff
                words = [(t, (x0 + x1) / 2, x0) for t, x0, x1, y, sz in lyr if st['bot'] + 4 < y < hi + 6 and 7.5 < sz < 9.5]
                notes_only = [e for e in events if not e.get('rest')]
                for t, xc, x0 in words:
                    if notes_only:
                        e = min(notes_only, key=lambda e: min(abs(e['x'] + W / 2 - xc), abs(e['x'] - x0)))
                        if min(abs(e['x'] + W / 2 - xc), abs(e['x'] - x0)) < 14:
                            e['lyric'] = (e.get('lyric', '') + t) if e.get('lyric') else t
                        else:
                            stats['unplaced syllable'] += 1
                # ---- triplets: an italic 3 over a group
                for ti, (t, x0, x1, y, sz) in enumerate(small):
                    if t == '3' and lo - 12 <= y < hi + 12 and bars[0] < x0 < bars[-1] and len(notes_only) >= 3:
                        near = sorted(notes_only, key=lambda e: abs(e['x'] + W / 2 - (x0 + x1) / 2))[:3]
                        cost = max(abs(e['x'] + W / 2 - (x0 + x1) / 2) for e in near) + (0 if len({e['dur'] for e in near}) == 1 else 50)
                        if cost < trips.get(ti, (1e9,))[0]:
                            trips[ti] = (cost, near)
                # ---- into measures and voices
                for e in events:
                    mi = int(np.searchsorted(bars, e['x'] + W / 2)) - 1
                    if 0 <= mi < nmeas:
                        sys_meas[mi].setdefault(name, []).append(e)
                for mi in range(nmeas):
                    sys_meas[mi].setdefault(name, [])
                    sys_meas[mi][name + '.clef'] = clef
                    sys_meas[mi][name + '.key'] = keysig
            for cost, near in trips.values():
                if cost < 45:
                    for e in near:
                        e['trip'] = True
            measures += sys_meas
    return measures, stats


def pitch(h, clef):
    d = TOP_LINE[clef] - h['k']
    return LETTERS[d % 7] + h.get('acc', '') + str(d // 7)


def value(e, length):
    d = length if e['dur'] is None else e['dur']
    if e.get('dot'):
        d *= 1.5
    if e.get('trip'):
        d *= 2 / 3
    return d


def code(d):
    for k, v in DURCODE.items():
        if abs(k - d) < 1e-6:
            return v
    return None


def split_voices(evs, length):
    """One list of events -> one or two voices that each fill the measure, or None."""
    evs = sorted(evs, key=lambda e: e['x'])
    tot = sum(value(e, length) for e in evs)
    if abs(tot - length) < 1e-6:
        return [evs]
    if not evs:
        return [[]]
    if tot > length:
        fixed_up = [e for e in evs if e['up'] is True]
        fixed_dn = [e for e in evs if e['up'] is False]
        free = [e for e in evs if e['up'] is None]
        if len(free) <= 10:
            for mask in range(2 ** len(free)):
                a = sorted(fixed_up + [e for i, e in enumerate(free) if mask >> i & 1], key=lambda e: e['x'])
                b = sorted(fixed_dn + [e for i, e in enumerate(free) if not mask >> i & 1], key=lambda e: e['x'])
                if a and b and abs(sum(value(e, length) for e in a) - length) < 1e-6 and abs(sum(value(e, length) for e in b) - length) < 1e-6:
                    return [a, b]
    return None


def write(measures, names, out, tempo, title, says=(), warn=print):
    lines = [f'// Read automatically from the PDF by tools/pdf2score.py.  PRIVATE - never commit.',
             f'title: {title}', f'tempo: {tempo:g}', 'time: 4/4']
    clefs = {n: measures[0].get(n + '.clef', '&') for n in names}
    lines += [f'transpose: {n} -12' for n in names if clefs[n] == 'V']
    lines += [f'say: {s_}' for s_ in says]
    known = {L.clean(s_.split('=')[0].strip()): len(s_.split('=')[1].split('.')) for s_ in says}
    key, bad = None, []
    # ---- join lyric syllables into words, part by part
    for n in names:
        seq = []
        for mi, m in enumerate(measures):
            for e in sorted(m[n], key=lambda e: e['x']):
                if e.get('lyric'):
                    seq.append(e)
        i = 0
        while i < len(seq):
            joined = False
            for k in (4, 3, 2):
                if i + k <= len(seq):
                    parts = [L.clean(e['lyric']) for e in seq[i:i + k]]
                    w = ''.join(parts)
                    prons = L._cmu().get(w.strip("'")) or []
                    if len(set(parts)) > 1 and (known.get(w) == k or any(len(L.syllabify(p)) == k for p in prons)):
                        for e in seq[i:i + k - 1]:
                            e['lyric'] += '-'
                        i += k; joined = True
                        break
            if not joined:
                i += 1
    length = 4.
    for mi, m in enumerate(measures):
        k = collections.Counter(m.get(n + '.key', 0) for n in names).most_common(1)[0][0]   # most staves agree
        if k != key:
            lines.append(f'key: {k}'); key = k
        lines.append(f'== {mi + 1}')
        for n in names:
            voices = split_voices(m[n], length)
            if voices is None:
                tot = sum(value(e, length) for e in m[n])
                bad.append((mi + 1, n, tot))
                lines.append(f'// FIXME {n}: adds up to {tot:g}')
                voices = [sorted(m[n], key=lambda e: e['x'])]
            for vi, v in enumerate(voices):
                if not v or all(e.get('rest') for e in v):
                    continue
                toks = []
                for e in v:
                    d = code(value(e, length))
                    if d is None:
                        toks.append(f'?{value(e, length):g}'); continue
                    if e.get('rest'):
                        toks.append(f'r/{d}'); continue
                    hs = sorted(e['heads'], key=lambda h: h['k'], reverse=True)
                    alltie = all(h.get('tie') for h in hs)
                    p = '+'.join(pitch(h, clefs[n]) + ('~' if h.get('tie') and not alltie else '') for h in hs)
                    t = f'{p}/{d}' + ('~' if alltie else '')
                    if n not in ('RH', 'LH'):
                        ly = e.get('lyric')
                        t += '=' + re.sub(r'\s+', '', ly) if ly else ''
                    toks.append(t)
                lines.append(f'{n}{"" if vi == 0 else vi + 1}: ' + ' '.join(toks))
    open(out, 'w').write('\n'.join(lines) + '\n')
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf'); ap.add_argument('out')
    ap.add_argument('--staves', default='T1,T2,BR,BS,RH,LH'); ap.add_argument('--tempo', type=float, default=120.)
    ap.add_argument('--title', default='')
    ap.add_argument('--say', action='append', default=[], help='pronunciation, e.g. "sashay = S AE0 . SH EY1"')
    a = ap.parse_args()
    names = a.staves.split(',')
    measures, stats = read(a.pdf, names)
    bad = write(measures, names, a.out, a.tempo, a.title or os.path.basename(a.pdf), a.say)
    print(f'{len(measures)} measures; {dict(stats)}')
    for mnum, n, tot in bad:
        print(f'  measure {mnum} {n}: adds up to {tot:g} beats - needs a human')
    print(f'{len(bad)} staff-measures to fix by hand' if bad else 'every measure adds up')


if __name__ == '__main__':
    main()
