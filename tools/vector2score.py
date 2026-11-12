"""Read the notes of a PDF exported from notation software exactly, from the symbols it is drawn with.

A score exported from MuseScore, Dorico, Sibelius or a recent Finale is not a picture: every notehead, rest,
accidental, flag and clef is a character of a music font placed at an exact spot, and every staff line, stem,
barline and beam is a line.  Nearly all current music fonts (Bravura, Leland, Petaluma, Finale Maestro in its new
form, ...) follow one standard, SMuFL, which gives each symbol the same code whatever the font.  So nothing has to
be recognized here, only read off:

  staff lines        five evenly spaced long lines -> a staff; a notehead's height on it is its pitch
  clef, key, time    the symbols at the start of a staff (and wherever they change)
  stems              tie noteheads into chords; which way a stem points tells two voices on a staff apart
  beams and flags    crossing the free end of a stem give the note value; dots and tuplet numbers adjust it
  accidentals        the symbol just left of a notehead, lasting to the end of the bar
  curves             a tie if they join two notes of the same pitch, otherwise a slur (one syllable on many notes)

read() returns the systems in the form tools/scan2score.py works with (the same form a recognized page takes),
so everything after the notes - which staff is which part, the words, repeats, the score file itself - is shared.
"""
import collections, re
from fractions import Fraction
import numpy as np

HEADS = {0xE0A4: 1, 0xE0A3: 2, 0xE0A2: 4, 0xE0A0: 8, 0xF4BE: 1, 0xF4BD: 2, 0xF4BC: 4, 0xF4BB: 8,     # black, half, whole (and oversized forms)
         0xE0A9: 1, 0xE0A8: 2, 0xE0A7: 4,                                                          # x-shaped (spoken, clapped)
         0xE0DB: 1, 0xE0D9: 2, 0xE0D8: 4, 0xE0AF: 1, 0xE0BE: 1, 0xE0BD: 2}                         # diamonds, slashes
RESTS = {0xE4E2: 8, 0xE4E3: 4, 0xE4E4: 2, 0xE4E5: 1, 0xE4E6: Fraction(1, 2), 0xE4E7: Fraction(1, 4), 0xE4E8: Fraction(1, 8)}
FLAGS = {0xE240: 1, 0xE241: 1, 0xE242: 2, 0xE243: 2, 0xE244: 3, 0xE245: 3}
ACCS = {0xE260: -1, 0xE261: 0, 0xE262: 1, 0xE263: 2, 0xE264: -2}
CLEFS = {0xE050: 'G', 0xE052: 'G', 0xE053: 'G', 0xE062: 'F', 0xE064: 'F', 0xE07A: 'G', 0xE07C: 'F'}   # (octave marks under a clef are left to the caller)
TOP_LINE = {'G': 38, 'F': 26}                              # the top staff line as letter + 7 * octave (c = 0)
DOT = 0xE1E7
DIGITS = {0xE080 + i: i for i in range(10)}                # time signature
TUPLET = {0xE880 + i: i for i in range(10)}
DYNAMICS = {0xE520: 'p', 0xE522: 'f', 0xE52A: 'pp', 0xE52B: 'pp', 0xE52C: 'mp', 0xE52D: 'mf', 0xE52F: 'ff', 0xE530: 'ff'}
SHARPS, FLATS = 'fcgdaeb', 'beadgcf'
TEXT_DIGIT = 0x10000                                       # + n: a tuplet's number that is not a music symbol but a letter of a text font
FERMATA = (0xE4C0, 0xE4C1)                                 # above, below
LOW_CLEFS = (0xE052, 0xE064)                               # a clef with an 8 under it: sung an octave lower than written
COMMON, CUT = 0xE08A, 0xE08B                               # the C that stands for 4/4, and the barred one for 2/2

# ---- music fonts from before the standard (Finale's Maestro and Petrucci, Adobe's Sonata: one layout, on the letters
# of an ordinary keyboard) - each of their characters, as the standard's code for the same symbol
LEGACY_FONTS = ('maestro', 'petrucci', 'sonata')
LEGACY = {0x26: 0xE050, 0x56: 0xE052, 0x3F: 0xE062, 0x74: 0xE064,                                   # & V ? t: treble, treble an octave down, bass clefs
          0xCF: 0xE0A4, 0xFA: 0xE0A3, 0x77: 0xE0A2, 0x57: 0xE0A0, 0xC0: 0xE0A9,                     # noteheads: black, half, whole, double whole, x
          0xB7: 0xE4E3, 0xEE: 0xE4E4, 0xCE: 0xE4E5, 0xE4: 0xE4E6, 0xC5: 0xE4E7, 0xA8: 0xE4E8,       # rests: whole, half, quarter, eighth, 16th, 32nd
          0x6A: 0xE240, 0x4A: 0xE241, 0x72: 0xE242, 0x52: 0xE243,                                   # j J r R: flags
          0x62: 0xE260, 0x6E: 0xE261, 0x23: 0xE262, 0xDC: 0xE263, 0xBA: 0xE264,                     # b n #, double sharp, double flat
          0x2E: 0xE1E7, 0x6B: 0xE1E7,                                                               # the dot after a note
          0x70: 0xE520, 0x66: 0xE522, 0x50: 0xE52C, 0x46: 0xE52D, 0xB9: 0xE52B, 0xC4: 0xE52F,       # p f P F: piano, forte, mp, mf; pp, ff
          0x55: 0xE4C0, 0x75: 0xE4C1,                                                               # U u: fermatas
          0x63: COMMON, 0x43: CUT, **{0x30 + i: 0xE080 + i for i in range(10)}}                     # time signatures
# Some PDF makers store such a font as a "symbol" font, and its characters then come out as Greek letters and
# mathematical signs: the Symbol encoding's character for each code from 0x20 to 0x7E.
_SYMBOL = dict(zip(' !\u2200#\u2203%&\u220b()\u2217+,\u2212./0123456789:;<=>?\u2245\u0391\u0392\u03a7\u0394\u0395\u03a6\u0393\u0397\u0399\u03d1\u039a\u039b\u039c\u039d\u039f'
                   '\u03a0\u0398\u03a1\u03a3\u03a4\u03a5\u03c2\u03a9\u039e\u03a8\u0396[\u2234]\u22a5_\uf8e5\u03b1\u03b2\u03c7\u03b4\u03b5\u03c6\u03b3\u03b7\u03b9\u03d5\u03ba\u03bb\u00b5\u03bd\u03bf'
                   '\u03c0\u03b8\u03c1\u03c3\u03c4\u03c5\u03d6\u03c9\u03be\u03c8\u03b6{|}\u223c', range(0x20, 0x7F)))
_SYMBOL.update({'\u2206': 0x44, '\u2126': 0x57, '\u03bc': 0x6D})


def _legacy_code(ch, shift):
    """A character of an old music font, as text extraction gives it -> the font's own code for it."""
    if ch in _SYMBOL:
        return _SYMBOL[ch] + shift
    try:
        return ch.encode('mac_roman')[0]
    except (UnicodeEncodeError, IndexError):
        return None


def legacy_shift(doc):
    """Is this PDF drawn with one of the old music fonts - and if so, how far are its low codes displaced?  (One PDF
    maker writes every code below 0x80 one too low.)  The right answer is the one under which the characters on the
    pages are music symbols.  -> the displacement, or None if there is no such font."""
    seen = collections.Counter()
    for page in doc:
        for b in page.get_text('rawdict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    if any(f in s['font'].lower() for f in LEGACY_FONTS):
                        seen.update(c['c'] for c in s['chars'] if c['c'].strip())
    if sum(seen.values()) < 20:
        return None
    score = {sh: sum(n for ch, n in seen.items() if _legacy_code(ch, sh) in LEGACY) for sh in (0, 1, -1)}
    return max(score, key=lambda sh: (score[sh], -abs(sh)))
SEMIS = [0, 2, 4, 5, 7, 9, 11]


def _page(page, shift=None):
    """One PDF page -> (music symbols [(code, x, y, size)], drawings sorted into kinds).  shift: see legacy_shift."""
    glyphs = []
    for b in page.get_text('rawdict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                old = shift is not None and any(f in s['font'].lower() for f in LEGACY_FONTS)
                word = ''.join(c['c'] for c in s['chars']).strip()
                if shift is not None and not old and word in ('3', '5', '6', '7') and (s['flags'] & 2 or 'italic' in s['font'].lower()):
                    c = next(c for c in s['chars'] if c['c'].strip())      # a triplet's number, which this software sets in a text font
                    glyphs.append((TEXT_DIGIT + int(word), c['origin'][0], c['origin'][1], s['size']))
                    continue
                for c in s['chars']:
                    if old:
                        code = LEGACY.get(_legacy_code(c['c'], shift))
                        if code:
                            glyphs.append((code, c['origin'][0], c['origin'][1], s['size']))
                    elif 0xE000 <= ord(c['c']) <= 0xF8FF:
                        glyphs.append((ord(c['c']), c['origin'][0], c['origin'][1], s['size']))
    long_, short, vert, beams, curves = [], [], [], [], []
    for d in page.get_drawings():
        r = d['rect']; kinds = {it[0] for it in d['items']}
        if 'c' in kinds:
            # one drawing may hold several curves (the two ties of an octave, drawn in one stroke): each closed outline by itself
            runs, last = [], None
            for it in d['items']:
                pts = [(p.x, p.y) for p in it[1:] if hasattr(p, 'x')]
                if not pts:
                    continue
                if last is None or abs(pts[0][0] - last[0]) + abs(pts[0][1] - last[1]) > .5:
                    runs.append([])
                runs[-1] += pts; last = pts[-1]
            for run in runs:
                xs = [p[0] for p in run]; ys = [p[1] for p in run]
                if max(xs) - min(xs) > 3:
                    curves.append((min(xs), min(ys), max(xs), max(ys)))
        elif r.height < 1.5 and r.width > 100:
            long_.append((r.y0, r.x0, r.x1))
        elif r.height < 1.5 and r.width > 1.5:
            short.append((r.y0, r.x0, r.x1, d.get('width') or 0.))
        elif r.width < 1.5 and r.height > 1.5:
            vert.append((r.x0, r.y0, r.y1, d.get('width') or 0.))
        elif d.get('fill') is not None and kinds == {'l'} and r.width > 2.5 and r.height < 40:
            pts = [(p.x, p.y) for it in d['items'] for p in it[1:3]]
            beams.append(pts)
    return glyphs, long_, short, vert, beams, curves


def _staves(long_):
    """Long horizontal lines -> staves: five lines evenly spaced."""
    ys = sorted({round(y, 1) for y, x0, x1 in long_})
    merged = []
    for y in ys:
        if not merged or y - merged[-1] > .6:
            merged.append(y)
    staves, i = [], 0
    while i + 4 < len(merged):
        five = merged[i:i + 5]
        gaps = np.diff(five)
        if gaps.max() - gaps.min() < .25 * gaps.mean() and gaps.mean() < 14:
            x0 = min(a for y, a, b in long_ if abs(y - five[0]) < .6); x1 = max(b for y, a, b in long_ if abs(y - five[0]) < .6)
            staves.append(dict(top=five[0], bot=five[4], sp=float(gaps.mean()), x0=x0, x1=x1))
            i += 5
        else:
            i += 1
    return staves


def _systems(staves, vert, glyphs):
    """Staves joined at the left by one vertical line (or a brace) are one system."""
    if not staves:
        return []
    join = [False] * (len(staves) - 1)
    for x, y0, y1, w in vert:
        for i in range(len(staves) - 1):
            a, b = staves[i], staves[i + 1]
            if y0 < a['bot'] - a['sp'] and y1 > b['top'] + b['sp'] and x < a['x0'] + 12 * a['sp'] and abs(x - a['x0']) < 4 * a['sp']:
                join[i] = True
    out, cur = [], [staves[0]]
    for i, j in enumerate(join):
        if j:
            cur.append(staves[i + 1])
        else:
            out.append(cur); cur = [staves[i + 1]]
    out.append(cur)
    for sysm in out:                                   # the piano's two staves share a brace
        for st in sysm:
            st['kind'] = 'v'
        for c, x, y, size in glyphs:
            if c in (0xE000, 0xF401) or 0xF400 <= c <= 0xF40F:
                under = [st for st in sysm if st['top'] - 2 * st['sp'] < y < st['bot'] + 2 * st['sp'] or st['top'] < y - size / 2 < st['bot'] + 4 * st['sp']]
                near = sorted(sysm, key=lambda st: abs((st['top'] + st['bot']) / 2 - (y - size / 4)))[:2]
                if x < sysm[0]['x0'] and len(near) == 2 and abs(sysm.index(near[0]) - sysm.index(near[1])) == 1:
                    for st in near:
                        if y - size - st['sp'] < (st['top'] + st['bot']) / 2 < y + st['sp']:
                            st['kind'] = 'p'
        ps = [st for st in sysm if st['kind'] == 'p']
        if len(ps) != 2:                               # a brace that was not found cleanly: the piano is the two lowest of four or more
            for st in sysm:
                st['kind'] = 'v'
            if len(sysm) >= 3:
                sysm[-1]['kind'] = sysm[-2]['kind'] = 'p'
    return out


def _beam_y(pts, x):
    """The heights between which a beam (a filled four-sided shape) lies at x, or None if it is not there."""
    xs = [p[0] for p in pts]
    if not (min(xs) - .8 <= x <= max(xs) + .8):
        return None
    left = [p for p in pts if p[0] < (min(xs) + max(xs)) / 2]; right = [p for p in pts if p[0] >= (min(xs) + max(xs)) / 2]
    if not left or not right:
        return None
    f = (x - min(xs)) / max(max(xs) - min(xs), 1e-6)
    lo = min(p[1] for p in left) + f * (min(p[1] for p in right) - min(p[1] for p in left))
    hi = max(p[1] for p in left) + f * (max(p[1] for p in right) - max(p[1] for p in left))
    return lo, hi


def _pitch(k, clef, alter):
    d = TOP_LINE[clef] - k
    letter, octave = d % 7, d // 7
    midi = 12 * (octave + 1) + SEMIS[letter] + alter
    name = 'cdefgab'[letter] + {1: '#', -1: 'b', 2: '##', -2: 'bb'}.get(alter, 'n') + str(octave)
    return midi, name


def _timed(events, length, W, sp, both=True):
    """When does each event of one staff in one measure begin?  -> [(voice, onset, event)].
    Notes that sound together stand one above the other, so the measure is read column by column, left to right,
    keeping for each of the two voices (stems up, stems down) the moment it is next due.  A column's moment is when
    its own voice is due; a rest drawn in the middle of the staff, a whole note, or a chord on a single stem at a
    moment when the other voice is due as well, belongs to both voices.  With `both`, such shared events are given
    to both voices, so that each voice is complete from its first note to its last."""
    val = lambda e: length if e['dur'] is None else e['dur']
    events = sorted(events, key=lambda e: e['x'] + (0 if e.get('rest') else W / 2))
    cols = []
    for e in events:
        c = e['x']
        last = cols[-1][1] if cols else []
        # Two voices a second apart stand side by side, a notehead's width from each other - but two notes of one
        # voice never sound together, however close they are printed.
        same_voice = e['up'] is not None and any(o['up'] is e['up'] for o in last)
        near = 1.5 * W if not (e.get('rest') or any(o.get('rest') for o in last)) else .3 * W
        if cols and c - cols[-1][0] < near and not same_voice:
            last.append(e)
        else:
            cols.append([c, [e]])
    # One voice may point its stems now up, now down.  There are two voices only if an up-stem and a down-stem sound
    # together somewhere, or if there is more in the measure than one voice can hold.
    two = any(any(e['up'] is True for e in evs) and any(e['up'] is False for e in evs) for _, evs in cols) or \
        (any(e['up'] is True for e in events) and any(e['up'] is False for e in events) and sum(val(e) for e in events if e['dur'] is not None) > length) or \
        any(any(e['up'] is None and not e.get('rest') for e in evs) and any(e['up'] is not None for e in evs) for _, evs in cols) or \
        (sum(val(e) for e in events) > length and        # more than one voice can hold, and a rest set high or low beside a whole note
         any(any(e.get('rest') and abs(e['y'] - e['mid']) >= 1.2 * sp for e in evs) and any(e['up'] is None and not e.get('rest') for e in evs) for _, evs in cols))
    due = {1: Fraction(0), 2: Fraction(0)}
    out = []
    for _, evs in cols:
        ups = [e for e in evs if e['up'] is True]; downs = [e for e in evs if e['up'] is False]
        free = [e for e in evs if e['up'] is None]
        if not two:                                   # one voice: everything in turn
            t = due[1]
            for e in evs:
                out.append((1, t, e))
            due[1] = due[2] = t + max(val(e) for e in evs)
            continue
        side = {}                                     # which voice a rest or stemless note is drawn for (0 = both)
        for e in free:
            if e.get('rest'):
                side[id(e)] = 0 if abs(e['y'] - e['mid']) < 1.2 * sp else (1 if e['y'] < e['mid'] else 2)
        for e in free:
            if not e.get('rest'):                     # a stemless note beside the other voice's note or rest is not that voice's; alone, it is for both
                one = bool(ups) or any(side.get(id(o)) == 1 for o in free); other = bool(downs) or any(side.get(id(o)) == 2 for o in free)
                side[id(e)] = 2 if one and not other else 1 if other and not one else 0
        v1 = ups + [e for e in free if side[id(e)] == 1]; v2 = downs + [e for e in free if side[id(e)] == 2]
        shared = [e for e in free if side[id(e)] == 0]
        if v1 and v2 or shared:
            t = max(due[1], due[2]) if (v1 and v2) or (shared and not v1 and not v2) else due[1] if v1 else due[2]
        else:
            t = due[1] if v1 else due[2]
        for e in v1 + shared:
            out.append((1, t, e))
        for e in v2 + (shared if both else []):
            out.append((2, t, e))
        d1 = max([val(e) for e in v1 + shared] or [None], key=lambda v: v or 0)
        d2 = max([val(e) for e in v2 + shared] or [None], key=lambda v: v or 0)
        if d1 is not None and d2 is None and due[2] == t:          # the other voice is due now and has nothing of its own: the chord is for both
            if both:
                out.extend((2, t, e) for e in v1)
            d2 = d1
        elif d2 is not None and d1 is None and due[1] == t:
            if both:
                out.extend((1, t, e) for e in v2)
            d1 = d2
        if d1 is not None:
            due[1] = t + d1
        if d2 is not None:
            due[2] = t + d2
    return out


def _staff_events(st, lo, hi, glyphs, vert_stems, beams, x0, x1, bars, size0):
    """Everything drawn on one staff of one system -> what is needed to turn it into notes: the events (chords and
    rests, each with its value before tuplets), the noteheads, accidentals, clef changes, time and key signatures."""
    sp = st['sp']; W = 1.18 * sp
    mine = [(c, x, y, sz) for c, x, y, sz in glyphs if lo <= y < hi and x0 - 2 < x < x1 + 2]
    big = lambda sz: sz > .8 * size0
    clefs = sorted((x, CLEFS[c]) for c, x, y, sz in mine if c in CLEFS and st['top'] - sp < y < st['bot'] + sp)
    low = any(c in LOW_CLEFS for c, x, y, sz in mine if c in CLEFS and st['top'] - sp < y < st['bot'] + sp and x < x0 + 12 * sp)
    heads = [dict(c=c, x=x, y=y, k=int(round((y - st['top']) / (sp / 2))), val=HEADS[c], small=not big(sz)) for c, x, y, sz in mine if c in HEADS]
    rests = [(c, x, y, not big(sz)) for c, x, y, sz in mine if c in RESTS and st['top'] - 3 * sp < y < st['bot'] + 3 * sp]
    first_x = min([h['x'] for h in heads] + [r[1] for r in rests] + [bars[1] if len(bars) > 1 else x1])
    # ---- time signatures: two numbers one above the other
    tdig = sorted((x, y, DIGITS[c]) for c, x, y, sz in mine if c in DIGITS and st['top'] - sp < y < st['bot'] + sp)
    tsigs = []
    for x, y, v in tdig:
        if y < (st['top'] + st['bot']) / 2 + .2 * sp:
            den = sorted((xx, vv) for xx, yy, vv in tdig if abs(xx - x) < 2.5 * sp and yy > y + sp)
            num = [vv for xx, yy, vv in tdig if abs(yy - y) < .5 * sp and abs(xx - x) < 2.5 * sp]
            if den and (not tsigs or x - tsigs[-1][0] > 2.5 * sp):
                tsigs.append((x, f"{int(''.join(map(str, num)))}/{int(''.join(str(vv) for xx, vv in den))}"))
    tsigs = sorted(tsigs + [(x, '4/4' if c == COMMON else '2/2') for c, x, y, sz in mine if c in (COMMON, CUT) and st['top'] - sp < y < st['bot'] + sp])
    # ---- accidentals: each belongs to the notehead at its height just to its right, if there is one
    accs = [dict(x=x, y=y, k=int(round((y - st['top']) / (sp / 2))), a=ACCS[c]) for c, x, y, sz in mine if c in ACCS and big(sz)]
    # (Noteheads sounding together stand in a cluster - a chord, a second pushed to the other side of the stem, another
    # voice set a little apart - and their accidentals stand in columns just left of the whole cluster, never further
    # from it or from each other than a notehead and a half.  A key signature keeps a wider space before the first note.)
    order = sorted(heads, key=lambda h: h['x'])
    clusters = []
    wide = lambda h: (1.75 if h['val'] >= 4 else 1.3) * sp          # a whole note is broader than the others
    for h in order:
        if clusters and h['x'] - max(o['x'] + wide(o) for o in clusters[-1]) < .5 * sp:
            clusters[-1].append(h)
        else:
            clusters.append([h])
    for cl in clusters:
        prev = min(h['x'] for h in cl)
        for a in sorted((a for a in accs if 'head' not in a and a['x'] < prev - .3 * W and prev - a['x'] < 7 * W), key=lambda a: -a['x']):
            if prev - a['x'] > 1.85 * W:
                break
            own = [h for h in cl if h['k'] == a['k'] and 'acc' not in h]
            if not own:
                break
            a['head'] = own[0]; own[0]['acc'] = a['a']
            prev = min(prev, a['x'])
    keys_here = collections.defaultdict(list)          # measure index -> the accidentals of a key signature standing there
    nmeas = len(bars) - 1
    for a in accs:
        if 'head' not in a:
            mi = min(max(int(np.searchsorted(bars, a['x'] + .1)) - 1, 0), nmeas - 1)
            evx = [h['x'] for h in heads if bars[mi] <= h['x'] < bars[mi + 1]] + [r[1] for r in rests if bars[mi] <= r[1] < bars[mi + 1]]
            if not evx or a['x'] < min(evx) - .5 * W:
                keys_here[mi].append(a['a'])
    # ---- chords: noteheads on one stem
    stems = [v for v in vert_stems if lo - 4 * sp <= (v[1] + v[2]) / 2 < hi + 4 * sp]
    for h in heads:
        h['stem'] = None
    for v in stems:
        for h in heads:
            slack = (.7 if h['c'] in (0xE0A7, 0xE0A8, 0xE0A9) else .3) * sp     # a stem ends at a notehead's own height (an x-shaped one: at its corner)
            if v[1] - slack <= h['y'] <= v[2] + slack and (abs(h['x'] + W - v[0]) < .42 * W or abs(h['x'] - v[0]) < .3 * W):
                if h['stem'] is None or abs((v[1] + v[2]) / 2 - h['y']) < abs((h['stem'][1] + h['stem'][2]) / 2 - h['y']) - 3 * sp:
                    h['stem'] = v
    groups = collections.defaultdict(list); loose = []
    for h in heads:
        (groups[h['stem']] if h['stem'] else loose).append(h)
    events = []
    mid = (st['top'] + st['bot']) / 2
    for stem, hs in groups.items():
        ys = [h['y'] for h in hs]
        up = bool((stem[1] + stem[2]) / 2 < np.mean(ys))
        events.append(dict(x=stem[0] - (W if up else 0), heads=hs, stem=stem, up=up, free=stem[1] if up else stem[2], y=float(np.mean(ys)), mid=mid,
                           small=all(h['small'] for h in hs)))
    for h in sorted(loose, key=lambda h: h['x']):
        prev = next((e for e in events if e.get('loose') and abs(e['x'] - h['x']) < wide(h) + .5 * sp and abs(e['y'] - h['y']) < 5 * sp), None)
        if prev:
            prev['heads'].append(h)
        else:
            events.append(dict(x=h['x'], heads=[h], stem=None, up=None, loose=True, y=h['y'], mid=mid, small=h['small']))
    # ---- note values: beams and flags at the free end of the stem; dots
    flags = [(x, y, FLAGS[c]) for c, x, y, sz in glyphs if c in FLAGS and lo - 5 * sp <= y < hi + 5 * sp]
    for e in events:
        base = Fraction(min(h['val'] for h in e['heads']))
        if e['stem'] and base == 1:
            sx, sy0, sy1 = e['stem'][:3]
            nb = 0
            for pts in beams:
                yy = _beam_y(pts, sx)
                if yy and yy[0] - .35 * sp <= e['free'] <= yy[1] + .35 * sp:
                    nb += 1
                elif yy and sy0 - .2 * sp <= (yy[0] + yy[1]) / 2 <= sy1 + .2 * sp and abs((yy[0] + yy[1]) / 2 - e['free']) < 2.2 * sp:
                    nb += 1
            nf = max([n for x, y, n in flags if abs(x - sx) < .5 * W and abs(y - e['free']) < 1.2 * sp] or [0])
            base = base / 2 ** max(nb, nf)
        e['dur'] = base
    dots = [(x, y) for c, x, y, sz in mine if c == DOT]
    used = set()
    for e in events:
        got = set()
        for h in e['heads']:
            got |= {(dx, dy) for dx, dy in dots if .9 * W < dx - h['x'] < 3.6 * W and abs(dy - h['y']) < .62 * sp and
                    not any(o is not h and o['x'] > h['x'] + .5 * W and o['x'] < dx and abs(o['y'] - dy) < .62 * sp for o in heads)}
        used |= got
        cols = []                                      # every note of a chord has its own dot: what counts is how many stand side by side
        for dx in sorted(dx for dx, dy in got):
            if not cols or dx - cols[-1] > .4 * sp:
                cols.append(dx)
        e['dur'] *= {0: 1, 1: Fraction(3, 2)}.get(len(cols), Fraction(7, 4))
    for c, x, y, small in rests:
        nd = sum(1 for dx, dy in dots if (dx, dy) not in used and .8 * W < dx - x < 3.2 * W and abs(dy - y) < 1.6 * sp)
        d = None if c == 0xE4E3 else Fraction(RESTS[c]) * {0: 1, 1: Fraction(3, 2)}.get(nd, Fraction(7, 4))
        events.append(dict(x=x, heads=[], stem=None, up=None, rest=True, dur=d, y=y, mid=mid, small=small))
    dyn = sorted((x, DYNAMICS[c]) for c, x, y, sz in mine if c in DYNAMICS)
    return dict(st=st, lo=lo, hi=hi, W=W, clefs=clefs, heads=heads, accs=accs, events=events, tsigs=tsigs, keys_here=keys_here, first_x=first_x, dyn=dyn,
                low=low)


def read(pdf, zoom=2.6, log=print):
    """-> the systems of the piece, each {'page', 'system', 'staves', 'kinds', 'top', 'bot', 'x0', 'x1', 'bars', 'read'}
    with lengths in page-image pixels (points times zoom) - or None if this PDF is not drawn with a standard music font."""
    import pymupdf
    doc = pymupdf.open(pdf)
    crops, heads_seen = [], 0
    time, length = None, Fraction(4)
    shift = legacy_shift(doc)
    for pn, page in enumerate(doc, 1):
        glyphs, long_, short, vert, beams, curves = _page(page, shift)
        staves = _staves(long_)
        if not staves:
            continue
        sp0 = float(np.median([s['sp'] for s in staves]))
        size0 = collections.Counter(round(sz, 1) for c, x, y, sz in glyphs if c in HEADS).most_common(1)
        size0 = size0[0][0] if size0 else 4 * sp0
        systems = _systems(staves, vert, glyphs)
        for sn, sysm in enumerate(systems, 1):
            ytop, ybot = sysm[0]['top'], sysm[-1]['bot']
            x0, x1 = min(s['x0'] for s in sysm), max(s['x1'] for s in sysm)
            # ---- barlines: vertical lines that run exactly from a staff's top line to a staff's bottom line...
            tops = [s['top'] for s in sysm]; bots = [s['bot'] for s in sysm]
            fits = lambda v: min(abs(v[1] - t) for t in tops) < .9 and min(abs(v[2] - b) for b in bots) < .9
            thin = [v[3] for v in vert if ytop - 4 * sp0 < v[1] and v[2] < ybot + 4 * sp0 and not fits(v) and v[3] > 0]
            stem_w = float(np.median(thin)) if thin else 0.
            # ...and that are drawn heavier than a stem, or stand at the same place on most staves (a stem can fill a staff too)
            cand = [v for v in vert if ytop - 1 < v[1] and v[2] < ybot + 1 and fits(v)]
            covers = lambda x: sum(1 for st in sysm if any(abs(v[0] - x) < .5 and v[1] < st['top'] + .9 and v[2] > st['bot'] - .9 for v in cand))
            heavy = [v[3] for v in cand if covers(v[0]) >= max(1, int(np.ceil(.6 * len(sysm))))]
            by_weight = bool(stem_w) and bool(heavy) and float(np.median(heavy)) > 1.3 * stem_w      # some software draws barlines no heavier than stems
            is_bar = lambda v: fits(v) and (v[3] > 1.3 * stem_w if by_weight else True) and covers(v[0]) >= max(1, int(np.ceil(.6 * len(sysm))))
            bars = []
            for x in sorted(v[0] for v in cand if is_bar(v)):
                if bars and x - bars[-1] < 2.2 * sp0:
                    bars[-1] = x                       # a double bar is one barline
                elif x - x0 > 1.5 * sp0:
                    bars.append(x)
            if not bars or x1 - bars[-1] > 3 * sp0:
                bars.append(x1)
            bars = [x0] + bars                         # the first measure begins after clef, key and time signature
            nmeas = len(bars) - 1
            stems_all = [v for v in vert if not is_bar(v) and ytop - 8 * sp0 < (v[1] + v[2]) / 2 < ybot + 8 * sp0 and x0 < v[0] < x1 + 1]
            info = []
            for si, st in enumerate(sysm):
                lo = (sysm[si - 1]['bot'] + st['top']) / 2 if si else st['top'] - 7 * st['sp']
                hi = (st['bot'] + sysm[si + 1]['top']) / 2 if si + 1 < len(sysm) else st['bot'] + 7 * st['sp']
                info.append(_staff_events(st, lo, hi, glyphs, stems_all, beams, x0, x1, bars, size0))
            # ---- tuplets: a small number over (or under) a group.  It belongs to the staff whose notes are nearest;
            # the bracket or the beam says how far it reaches.
            for c, x, y, sz in glyphs:
                as_text = TEXT_DIGIT < c < TEXT_DIGIT + 10
                if not (c in TUPLET or as_text) or not (ytop - 6 * sp0 <= y <= ybot + 6 * sp0 and x0 < x < x1):
                    continue
                n = c - TEXT_DIGIT if as_text else TUPLET[c]
                if n not in (3, 5, 6, 7) or (as_text and x < min(f['first_x'] for f in info)):       # (a measure number at the head of the system)
                    continue
                def nearest(f):                    # how far the number is from this staff's notes (heads or stem ends)
                    near = [e for e in f['events'] if abs(e['x'] + f['W'] / 2 - x) < 6 * f['W']]
                    return min((min(abs(e['y'] - y), abs(e.get('free', e['y']) - y)) for e in near), default=1e9)
                f = min(info, key=nearest)
                if nearest(f) > 7 * sp0:
                    continue
                W = f['W']
                # the bracket: two thin pieces level with the number, one on each side of it (drawn as lines or as thin filled shapes)
                pieces = [(a_, b_) for yy, a_, b_, w in short if abs(yy - (y - .5 * sp0)) < 1.6 * sp0 and w < .6]
                for pts in beams:
                    xs = [p_[0] for p_ in pts]; ys = [p_[1] for p_ in pts]
                    if abs((min(ys) + max(ys)) / 2 - (y - .5 * sp0)) < 1.6 * sp0 and max(ys) - min(ys) < 1.6 * sp0:
                        pieces.append((min(xs), max(xs)))
                left = [p_ for p_ in pieces if p_[1] <= x + .6 * W and x - p_[1] < 3 * sp0]
                right = [p_ for p_ in pieces if p_[0] >= x - .2 * W and p_[0] - x < 4 * sp0]
                reach = None
                if left and right:
                    reach = (min(p_[0] for p_ in left) - .7 * W, max(p_[1] for p_ in right) + .7 * W)
                else:                              # no bracket: the beam the number is printed on
                    for pts in beams:
                        xs = [p_[0] for p_ in pts]; ys = [p_[1] for p_ in pts]
                        if min(xs) - W <= x <= max(xs) + W and min(abs(y - min(ys)), abs(y - max(ys))) < 4.5 * sp0 and max(xs) - min(xs) > 1.5 * W:
                            if reach is None or max(xs) - min(xs) > reach[1] - reach[0]:
                                reach = (min(xs) - 1.4 * W, max(xs) + .7 * W)
                if as_text and reach is None:          # a lone number with neither bracket nor beam may be anything (a fingering, a verse)
                    continue
                cand_e = [e for e in f['events'] if not e.get('trip') and e['dur'] is not None]
                centre = lambda e: e['x'] + W / 2
                grp = [e for e in cand_e if reach[0] <= centre(e) <= reach[1]] if reach else sorted(cand_e, key=lambda e: abs(centre(e) - x))[:n]
                for e in grp:
                    e['trip'] = Fraction({3: 2, 5: 4, 6: 4, 7: 4}[n], n)
            read_staves = []
            for si, f in enumerate(info):
                st, W, heads, accs = f['st'], f['W'], f['heads'], f['accs']
                sp = st['sp']
                heads_seen += sum(1 for h in heads if not h['small'])
                events = [e for e in f['events'] if not e['small']]         # cue-size and grace notes are not sung
                for e in events:
                    if e.get('trip') and e['dur'] is not None:
                        e['dur'] *= e['trip']
                big_heads = [h for h in heads if not h['small']]
                clef_at = lambda x: next((k for cx, k in reversed(f['clefs']) if cx <= x + 1), f['clefs'][0][1] if f['clefs'] else 'G')
                # ---- ties and slurs: a curve from one notehead to another
                for (cx0, cy0, cx1, cy1) in curves:
                    if not (f['lo'] - 2 * sp <= (cy0 + cy1) / 2 < f['hi'] + 2 * sp) or cx1 - cx0 < 1.2 * W:
                        continue
                    a = [h for h in big_heads if -1.6 * W < cx0 - (h['x'] + W / 2) < 1.6 * W and cy0 - 2.5 * sp < h['y'] < cy1 + 2.5 * sp]
                    if not a:
                        continue
                    a = min(a, key=lambda h: abs(cx0 - (h['x'] + W / 2)) + .5 * abs(h['y'] - (cy0 + cy1) / 2))
                    b = [h for h in big_heads if h is not a and -1.6 * W < cx1 - (h['x'] + W / 2) < 1.6 * W and cy0 - 2.5 * sp < h['y'] < cy1 + 2.5 * sp]
                    b = min(b, key=lambda h: abs(cx1 - (h['x'] + W / 2)) + .5 * abs(h['y'] - (cy0 + cy1) / 2)) if b else None
                    if (b is not None and b['k'] == a['k'] and not any(o['k'] == a['k'] and a['x'] < o['x'] < b['x'] for o in big_heads)) or \
                            (b is None and cx1 > bars[-1] - 2.5 * sp):
                        a['tie'] = True
                    elif b is not None:
                        a.setdefault('slur', []).append('start'); b.setdefault('slur', []).append('stop')
                # ---- into measures: pitches (clef, key, accidentals that last to the barline), voices, onsets
                per_measure = [[] for _ in range(nmeas)]
                for e in events:
                    mi = int(np.searchsorted(bars, e['x'] + W / 2)) - 1
                    if 0 <= mi < nmeas and e['x'] >= f['first_x'] - 1:
                        per_measure[mi].append(e)
                measures = []
                st_key = 0
                for mi in range(nmeas):
                    if mi == 0 or mi in f['keys_here']:      # every system begins with its key signature; a change is drawn where it happens
                        ks = f['keys_here'].get(mi, [])
                        st_key = sum(1 for a in ks if a > 0) - sum(1 for a in ks if a < 0)
                    for x, t in f['tsigs']:
                        if bars[mi] - 1 <= x < bars[mi + 1]:
                            time = t
                            n_, d_ = map(int, t.split('/')); length = Fraction(4 * n_, d_)
                    keyalt = {(SHARPS if st_key > 0 else FLATS)[i_]: (1 if st_key > 0 else -1) for i_ in range(abs(st_key))}
                    memory, notes = {}, []
                    val = lambda e: length if e['dur'] is None else e['dur']
                    timed = _timed(per_measure[mi], length, W, sp, both=st['kind'] == 'v')
                    alt = {}                               # each notehead's accidental state, worked out once, left to right
                    for vi, on, e in sorted(timed, key=lambda t: (t[1], t[2]['x'])):
                        if not e.get('rest'):
                            clef = clef_at(e['x'])
                            for h in e['heads']:
                                if id(h) not in alt:
                                    d = TOP_LINE[clef] - h['k']
                                    if 'acc' in h:
                                        memory[d] = h['acc']
                                    alt[id(h)] = (clef, memory.get(d, keyalt.get('cdefgab'[d % 7], 0)))
                    for vi in (1, 2):
                        for _, on, e in sorted((t for t in timed if t[0] == vi), key=lambda t: (t[1], t[2]['x'])):
                            ql = val(e)
                            e.setdefault('at', (mi, on, ql))
                            if e.get('rest'):
                                notes.append(dict(on=on, ql=Fraction(0) if e['dur'] is None else ql, midi=None, name=None, voice=str(vi), chord=False, x=None, tie=False, slur=[],
                                                  exact=True))
                            else:
                                for j, h in enumerate(sorted([h for h in e['heads'] if not h['small']] or e['heads'], key=lambda h: h['k'])):     # (a cue-size note in a chord is an option, not sung)
                                    midi, name = _pitch(h['k'], *alt[id(h)])
                                    notes.append(dict(on=on, ql=ql, midi=midi, name=name, voice=str(vi), chord=j > 0, x=(h['x'] + W / 2) * zoom,
                                                      tie=bool(h.get('tie')), slur=list(h.get('slur', [])), exact=True))
                    ends = [n['on'] + (n['ql'] if n['ql'] else length) for n in notes]
                    m = dict(len=None, time=None, notes=notes, end=max(ends) if ends else None, nominal=length)
                    if any(bars[mi] - 1 <= x < bars[mi + 1] for x, t in f['tsigs']):
                        m['time'] = time
                    d_here = [v for x, v in f['dyn'] if bars[mi] <= x < bars[mi + 1]]
                    if d_here:
                        m['dyn'] = d_here[0]
                    measures.append(m)
                read_staves.append(dict(clef=f['clefs'][0][1] if f['clefs'] else 'G', octave=-1 if f['low'] else 0, measures=measures))
            # ---- fermatas: each stands over (or under) one note or rest; the music waits there
            for c, x, y, sz in glyphs:
                if c in FERMATA and ytop - 8 * sp0 < y < ybot + 8 * sp0 and x0 < x < x1:
                    cx = x + 1.1 * sp0                 # the sign is about two spaces wide, centred on its note
                    near = [(abs(e['y'] - y), si, e) for si, f in enumerate(info) for e in f['events']
                            if 'at' in e and not e['small'] and abs(e['x'] + (0 if e.get('rest') else f['W'] / 2) - cx) < 1.6 * sp0 and f['lo'] - 3 * sp0 < y < f['hi'] + 3 * sp0]
                    if near:
                        _, si, e = min(near, key=lambda t: t[0])
                        mi, on, ql = e['at']
                        read_staves[si]['measures'][mi].setdefault('fermata', []).append((on, ql))
            for mi in range(nmeas):                    # the measure is as long as most staves fill it - never longer than its time signature
                ends = [stf['measures'][mi]['end'] for stf in read_staves if stf['measures'][mi]['end']]
                nominal = read_staves[0]['measures'][mi]['nominal']
                agreed = nominal if not ends or nominal in ends else collections.Counter(ends).most_common(1)[0][0]
                for stf in read_staves:
                    stf['measures'][mi]['len'] = agreed if agreed <= nominal else nominal
            for c, x, y, sz in glyphs:                 # repeat signs: dots just inside a barline
                if c in (0xE043, 0xE044) and ytop - sp0 < y < ybot + sp0:
                    b = int(np.argmin([abs(x - bx) for bx in bars]))
                    if abs(x - bars[b]) < 3 * sp0:
                        mi = b - 1 if x < bars[b] else b
                        if 0 <= mi < nmeas:
                            for stf in read_staves:
                                stf['measures'][mi]['rep_end' if x < bars[b] else 'rep_start'] = True
            above = (systems[sn - 2][-1]['bot'] + sysm[0]['top']) / 2 if sn > 1 else max(0., sysm[0]['top'] - 14 * sp0)
            below = (sysm[-1]['bot'] + systems[sn][0]['top']) / 2 if sn < len(systems) else min(page.rect.height, sysm[-1]['bot'] + 14 * sp0)
            crops.append(dict(name=None, page=pn, system=sn, staves=[(s['top'] * zoom, s['bot'] * zoom) for s in sysm], kinds=[s['kind'] for s in sysm],
                              top=int(above * zoom), bot=int(below * zoom), x0=x0 * zoom, x1=x1 * zoom, bars=[b * zoom for b in bars], read=read_staves))
    if heads_seen < 20:
        return None
    full = part = 0                                    # does what was read fill its measures?  If not, this is not a PDF to read this way
    for c in crops:
        for stf in c['read']:
            for m in stf['measures']:
                if any(n['midi'] is not None for n in m['notes']):
                    part += 1; full += m['end'] == m['len']
    if part and full / part < .8:
        log(f'  the symbols of this PDF do not add up as music ({full} of {part} staff-measures fill their measure): not read this way')
        return None
    log(f'the notes are read exactly, from the symbols the PDF is drawn with: {len(crops)} systems, {heads_seen} noteheads, '
        f'{full} of {part} staff-measures add up')
    return crops
