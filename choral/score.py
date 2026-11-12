"""Reader for the plain-text score format (see docs/score-format.md).

The format mirrors the printed page: notes are written as they appear on the staff (the key
signature and accidentals-within-the-bar rules are applied here), one line per staff or voice per
measure, with the sung syllable attached to each note.
"""
import json, os, re
from collections import defaultdict
from . import lyrics, latin

STEP = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
DUR = {'w': 4., 'h': 2., 'q': 1., 'e': .5, 's': .25, 't': .125}
SHARPS, FLATS = 'fcgdaeb', 'beadgcf'
DYN = {'pp': .42, 'p': .52, 'mp': .62, 'mf': .74, 'f': .88, 'ff': 1.0}
VOCAL = {'TEN': ('T1', 'T2'), 'LOW': ('BR', 'BS'), 'T1': ('T1',), 'T2': ('T2',), 'BR': ('BR',), 'BS': ('BS',), 'SOLO': ('SOLO',),
         'TRIO': ('TR1', 'TR2'), 'TR1': ('TR1',), 'TR2': ('TR2',), 'TR3': ('TR3',)}
PIANO = ('RH', 'RH2', 'RH3', 'LH', 'LH2', 'LH3')
TOKEN = re.compile(r"^(?P<p>r|[a-g](?:##|bb|[#bn])?-?\d~?(?:\+[a-g](?:##|bb|[#bn])?-?\d~?)*)/(?P<d>[whqest]3?\.*)"
                   r"(?P<f>(?:~|\^|>|'|%gl)*)(?:=(?P<l>\S+))?$")


class ScoreError(Exception):
    pass


class Score:
    def __init__(self):
        self.parts = {k: [] for k in ('T1', 'T2', 'BR', 'BS', 'SOLO', 'TR1', 'TR2', 'TR3')}   # dicts: beat, dur, midi, tie, lyric, flags
        self.piano = []                                           # dicts: beat, dur, midi, hand, flags
        self.tempo = []                                           # (beat, bpm)
        self.stretch = []                                         # (beat, length, factor): a fermata, a step of a rallentando
        self.timing = None                                        # measured beat -> second map, if any
        self.language = 'english'
        self.printed = None                                       # performed measure -> printed measure, when a play: order is given
        self.marks = {'voice': [], 'piano': []}                   # (beat, mark)
        self.measures = {}                                        # number -> (start beat, length)
        self.beats = 0.
        self.say = {}
        self.title = ''
        self.transpose = defaultdict(int)
        self.streams = {}          # (system, staff) -> syllables waiting for notes marked =*
        self.system = None

    def dyn(self, group, beat):
        """Dynamic level at a beat: step marks, with cresc/dim ramping to the next mark."""
        level, ramp = DYN['mf'], None
        marks = self.marks[group] or self.marks['voice'] or self.marks['piano']
        for i, (b, m) in enumerate(marks):
            if b > beat + 1e-9:
                break
            if m in DYN:
                level, ramp = DYN[m], None
            else:
                nxt = next(((b2, m2) for b2, m2 in marks[i + 1:] if m2 in DYN), None)
                target = DYN[nxt[1]] if nxt and nxt[0] - b <= 8.01 else level + (.14 if m == 'cresc' else -.16)
                ramp = (b, level, (nxt[0] if nxt and nxt[0] - b <= 8.01 else b + 4.), target)
        if ramp:
            b0, l0, b1, l1 = ramp
            return l0 + (l1 - l0) * min(1., max(0., (beat - b0) / max(b1 - b0, 1e-9)))
        return level


def _dur(code):
    d = DUR[code[0]]
    rest = code[1:]
    if rest.startswith('3'):
        d *= 2 / 3; rest = rest[1:]
    return d * (2 - .5 ** len(rest))


def play_order(spec, have):
    """'1-15 14-15 16-62' -> [1, 2, ..., 15, 14, 15, 16, ...]"""
    order = []
    for tok in spec.split():
        a, _, b = tok.partition('-')
        a, b = int(a), int(b or a)
        if a > b or a not in have or b not in have:
            raise ScoreError(f'play: "{tok}" names measures that are not in the score')
        order += [n for n in range(a, b + 1) if n in have]
    return order


def unroll(text, warn=print):
    """A score written as printed, with a `play:` line giving the order its measures are performed in
    (repeats, D.S., coda), becomes the score as performed: measures renumbered 1, 2, 3 ... and the
    time signature, key, tempo and dynamic level put right wherever the music jumps.
    Returns (text, {performed number: printed number})."""
    lines = text.splitlines()
    spec = next((l.split('//')[0].partition(':')[2].strip() for l in lines if l.split('//')[0].strip().startswith('play:')), None)
    if spec is None:
        return text, None
    STATE = ('time', 'key', 'tempo', 'dynamic')
    head, blocks, pre, cur = [], {}, [], None                 # blocks[n] = (lines before it, its own lines)
    for raw in lines:
        line = raw.split('//')[0].strip()
        if line.startswith('play:'):
            continue
        if line.startswith('=='):
            cur = int(line.strip('= ').split()[0])
            blocks[cur] = (pre, []); pre = []
        elif cur is None:
            head.append(raw)
        elif line.partition(':')[0].strip() in VOCAL or line.partition(':')[0].strip() in PIANO:
            blocks[cur][1].append(raw)
        else:
            pre.append(raw)                                   # a directive or comment: it belongs to what follows
    state = {k: None for k in STATE}
    for raw in head:
        k, _, v = raw.split('//')[0].partition(':')
        if k.strip() in STATE:
            state[k.strip()] = v.strip()
    at, after = {}, {}
    for n in blocks:                                          # what holds at the start of each printed measure, and after it
        for raw in blocks[n][0]:
            k, _, v = raw.split('//')[0].partition(':')
            if k.strip() in STATE:
                state[k.strip()] = v.strip()
        at[n] = dict(state)
        for raw in blocks[n][1]:
            if raw.split('//')[0].partition(':')[0].strip() in VOCAL:
                for tok in raw.split():
                    if tok[1:] in DYN and tok.startswith('!'):
                        state['dynamic'] = tok[1:]
        after[n] = dict(state)
    order = play_order(spec, blocks)
    if '=*' in text:
        warn('  ! play: with lyrics taken from a lyricsfile is not supported: a repeated measure would use up new words')
    out, now, printed = list(head), {k: None for k in STATE}, {}
    for k_, raw in ((r.split('//')[0].partition(':')[0].strip(), r) for r in head):
        if k_ in STATE:
            now[k_] = raw.split('//')[0].partition(':')[2].strip()
    for i, n in enumerate(order):
        out += [r for r in blocks[n][0] if r.split('//')[0].partition(':')[0].strip() not in STATE]
        for k in STATE:
            if at[n][k] is not None and at[n][k] != now[k]:
                out.append(f'{k}: {at[n][k]}')
        printed[i + 1] = n
        out.append(f'== {i + 1}   // printed {n}')
        jump = i + 1 < len(order) and order[i + 1] != n + 1
        for raw in blocks[n][1]:
            if jump:                                          # a tie cannot reach across a jump
                toks = raw.split()
                note, eq, lyr = toks[-1].partition('=')
                if '/' in note and '~' in note.split('/')[-1]:
                    d = note.rsplit('/', 1)
                    toks[-1] = d[0] + '/' + d[1].replace('~', '') + eq + lyr
                    raw = ' '.join(toks)
            out.append(raw)
        now = dict(after[n])
    return '\n'.join(out) + '\n', printed


def parse(text, warn=print, base='.'):
    text, printed = unroll(text, warn)
    sc = Score()
    sc.printed = printed
    key, meas_len, beat0, cur = 0, 4., 0., None
    lines_in_measure = {}

    def keysig(letter):
        if key > 0 and letter in SHARPS[:key]:
            return 1
        if key < 0 and letter in FLATS[:-key]:
            return -1
        return 0

    def close():
        nonlocal beat0, cur
        if cur is None:
            return
        sc.measures[cur] = (beat0, meas_len)
        for name, toks in lines_in_measure.items():
            _line(sc, cur, name, toks, beat0, meas_len, keysig, warn)
        beat0 += meas_len
        lines_in_measure.clear()
        cur = None

    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.split('//')[0].strip()          # // starts a comment
        if not line:
            continue
        if line.startswith('=='):
            close()
            cur = int(line.strip('= ').split()[0])
            continue
        head, _, rest = line.partition(':')
        head, rest = head.strip(), rest.strip()
        if head == 'title':
            sc.title = rest
        elif head == 'key':
            close()
            key = int(rest)
        elif head == 'time':
            close()
            a, b = rest.split('/')
            meas_len = int(a) * 4. / int(b)
        elif head == 'tempo':
            close()
            sc.tempo.append((beat0, float(rest)))
        elif head == 'stretch':                       # "stretch: 3 2 1.8" - from beat 3 of the next measure, 2 beats take 1.8 times as long
            close()
            at, span, factor = (float(v) for v in rest.split())
            sc.stretch.append((beat0 + at - 1, span, factor))
        elif head == 'dynamic':                       # one level for a piece that prints none
            close()
            sc.marks['voice'].append((beat0, rest)); sc.marks['piano'].append((beat0, rest))
        elif head == 'lyricsfile':                    # syllables read from the page by text recognition
            for system, staves in json.load(open(os.path.join(base, rest))).items():
                for staff, toks in staves.items():
                    sc.streams[(system, staff)] = list(toks)
        elif head == 'language':                      # 'latin': read syllables by rule instead of the English dictionary
            sc.language = rest.lower()
        elif head == 'timing':                        # beat -> second map measured from a recording (choral.timing)
            sc.timing = json.load(open(os.path.join(base, rest)))
        elif head == 'system':                        # which system of the page the next measures are on
            close()
            sc.system = rest
        elif head == 'transpose':
            name, semis = rest.split()
            sc.transpose[name] = int(semis)
        elif head == 'say':
            w, _, pron = rest.partition('=')
            sc.say[lyrics.clean(w.strip())] = lyrics.parse_override(pron)
        elif head in VOCAL or head in PIANO:
            if cur is None:
                raise ScoreError(f'line {ln}: notes before the first "== measure" line')
            if head in lines_in_measure:
                raise ScoreError(f'measure {cur}: two {head} lines')
            lines_in_measure[head] = rest.split()
        else:
            raise ScoreError(f'line {ln}: do not understand "{head}:"')
    close()
    sc.beats = beat0
    for (system, staff), left in sc.streams.items():
        if left:
            warn(f'  ! system {system} {staff}: {len(left)} recognized syllable(s) were not used')
    if not sc.tempo:
        sc.tempo = [(0., 100.)]
    _finish(sc, warn)
    return sc


def load(path, warn=None):
    """Read a score file (quietly unless given a warn function)."""
    return parse(open(path).read(), warn=warn or (lambda *a: None), base=os.path.dirname(os.path.abspath(path)))


def _line(sc, mnum, name, toks, beat0, meas_len, keysig, warn):
    vocal = name in VOCAL
    shift = sc.transpose[name] + (sc.transpose['TEN'] if name in ('T1', 'T2') else 0) + (sc.transpose['TRIO'] if name in ('TR1', 'TR2') else 0) + \
        (sc.transpose['LOW'] if name in ('BR', 'BS') else 0)
    acc, t = {}, 0.
    for tok in toks:
        if tok.startswith('!'):
            m = {'<': 'cresc', '>': 'dim'}.get(tok[1:], tok[1:])
            if m not in DYN and m not in ('cresc', 'dim'):
                raise ScoreError(f'measure {mnum} {name}: unknown dynamic "{tok}"')
            sc.marks['voice' if vocal else 'piano'].append((beat0 + t, m))
            continue
        mt = TOKEN.match(tok)
        if not mt:
            raise ScoreError(f'measure {mnum} {name}: cannot read "{tok}"')
        d = _dur(mt['d'])
        flags = set(re.findall(r"~|\^|>|'|%gl", mt['f']))
        lyric = mt['l']
        if lyric == '*':                               # take the next recognized syllable for this staff
            key = next((k for k in ((sc.system, name), (sc.system, 'TEN' if name in ('T1', 'T2') else 'LOW'))
                        if sc.streams.get(k)), None)
            if key is None:
                raise ScoreError(f'measure {mnum} {name}: no syllable left in system {sc.system}')
            lyric = sc.streams[key].pop(0)
        if mt['p'] != 'r':
            midis, tied = [], set()
            for p in mt['p'].split('+'):
                one_tie = p.endswith('~')            # a tie on just this note of the chord
                p = p.rstrip('~')
                letter, rest = p[0], p[1:]
                if rest[:2] in ('##', 'bb'):         # a double sharp or double flat
                    acc[(letter, rest[2:])] = 2 if rest[0] == '#' else -2
                    rest = rest[2:]
                elif rest[0] in '#bn':
                    acc[(letter, rest[1:])] = {'#': 1, 'b': -1, 'n': 0}[rest[0]]
                    rest = rest[1:]
                alter = acc.get((letter, rest), keysig(letter))
                midis.append(12 * (int(rest) + 1) + STEP[letter] + alter + shift)
                if one_tie or '~' in flags:
                    tied.add(midis[-1])
            midis = sorted(set(midis), reverse=True)
            if vocal:
                parts = VOCAL[name]
                if len(parts) == 2:        # a shared staff: top notes to the upper part
                    split = [tuple(midis[:-1]) if len(midis) > 1 else (midis[0],), (midis[-1],)]
                else:
                    split = [tuple(midis)]
                for part, ms in zip(parts, split):
                    sc.parts[part].append(dict(beat=beat0 + t, dur=d, midi=ms[0] if len(ms) == 1 else ms,
                                               tie=all(m_ in tied for m_ in ms), lyric=lyric, flags=flags, m=mnum))
            else:
                for mi in midis:
                    sc.piano.append(dict(beat=beat0 + t, dur=d, midi=mi, hand=name[:2], tie=mi in tied,
                                         flags=flags, m=mnum))
        t += d
    if abs(t - meas_len) > 1e-6:
        raise ScoreError(f'measure {mnum} {name}: adds up to {t:g} beats, not {meas_len:g}')


def _finish(sc, warn):
    # --- ties
    for part, notes in sc.parts.items():
        notes.sort(key=lambda n: n['beat'])
        out = []
        for n in notes:
            p = out[-1] if out else None
            if p and p['tie'] and abs(p['beat'] + p['dur'] - n['beat']) < 1e-6 and p['midi'] == n['midi']:
                p['dur'] += n['dur']; p['tie'] = n['tie']; p['flags'] |= n['flags'] - {'~'}
                if n['lyric'] not in (None, '_'):
                    warn(f'  ! measure {n["m"]} {part}: a syllable on a tied note was ignored')
            else:
                if p and p['tie'] and abs(p['beat'] + p['dur'] - n['beat']) < 1e-6 and n['lyric'] is None:
                    n['lyric'] = '_'       # written as a tie but the pitch changes: treat as a slur
                out.append(n)
        sc.parts[part] = out
    sc.piano.sort(key=lambda n: (n['beat'], n['midi']))
    alive, out = {}, []
    for n in sc.piano:
        k = (n['hand'], n['midi'])
        p = alive.get(k)
        if p and p['tie'] and abs(p['beat'] + p['dur'] - n['beat']) < 1e-6:
            p['dur'] += n['dur']; p['tie'] = n['tie']
        else:
            out.append(n); alive[k] = n
    sc.piano = out

    # --- lyrics: a voice without its own text sings what the others sing at the same moment
    at = defaultdict(list)
    for part, notes in sc.parts.items():
        for n in notes:
            if n['lyric'] is not None:
                at[round(n['beat'] * 96)].append((part, n['lyric']))
    buddy = {'T1': 'T2', 'T2': 'T1', 'BR': 'BS', 'BS': 'BR'}
    for part, notes in sc.parts.items():
        for n in notes:
            if n['lyric'] is None:
                c = at.get(round(n['beat'] * 96), [])
                pick = next((l for p, l in c if p == buddy.get(part)), None) or (c[0][1] if c else None)
                if pick is None:
                    warn(f'  ! measure {n["m"]} {part}: no syllable for the note on beat '
                         f'{n["beat"] - sc.measures[n["m"]][0] + 1:g}; holding the previous vowel')
                    pick = '_'
                else:
                    n['lent'] = True
                n['lyric'] = pick
    # A borrowed beginning of a word ("sip-") followed by a note with a word of its own: this voice is not singing
    # that word.  If it comes straight out of the note before, it is that note's vowel, still held; otherwise the
    # syllable stands by itself.  (Without this the two halves were glued into a word nobody sings.)
    for part, notes in sc.parts.items():
        heads = [(i, n) for i, n in enumerate(notes) if n['lyric'] != '_']
        for (i, a), (_, b) in zip(heads, heads[1:]):
            if a.get('lent') and a['lyric'].rstrip('.,;:!?').endswith('-') and not b.get('lent'):
                held = i and abs(notes[i - 1]['beat'] + notes[i - 1]['dur'] - a['beat']) < 1e-6
                a['lyric'] = '_' if held else a['lyric'].rstrip('-')

    # --- words -> phonemes
    for part, notes in sc.parts.items():
        heads = [n for n in notes if n['lyric'] != '_']
        words, cur = [], []
        for n in heads:
            s = lyrics.clean(n['lyric'])
            cur.append((n, s.rstrip('-')))
            if not s.endswith('-'):
                words.append(cur); cur = []
        if cur:
            words.append(cur)
        for i, w in enumerate(words):
            word = ''.join(s for _, s in w)
            nxt = ''.join(s for _, s in words[i + 1]) if i + 1 < len(words) else None
            if sc.language == 'latin' and word not in sc.say:
                prons = latin.pronounce([s for _, s in w])
            else:
                prons = lyrics.pronounce(word, len(w), sc.say, nxt, warn)
            for (n, _), syl in zip(w, prons):
                n['phon'] = syl
        for n in notes:
            if n['lyric'] == '_':
                n['phon'] = '-'
