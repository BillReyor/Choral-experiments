"""Small corrections to a score, for the page's "Fix a note or a word" (choral/app.py).

A score file mirrors the printed page (docs/score-format.md): every measure has a line for each staff, the notes
written as they are printed and the syllables attached to them.  This module shows one measure the way the page
shows it - each staff's notes in order, where each sits on its staff, what it sounds as, the word under it - and
changes one note or one word in the file, leaving every other character of it as it was.

A note is moved the way one would point at the page: up or down a step on the staff, with or without a sharp, flat
or natural in front of it.  What it then sounds as follows from the key signature and from the accidentals earlier
in its measure, by the same rules the reader of the score applies (score._line), and is worked out here again so
that it can be shown and played before anything is sung.

Before the first change the score is copied beside itself (NAME.score.as-read), so that all of them can be undone."""
import os, re, shutil
from . import score as scoremod

LETTERS = 'cdefgab'
PITCH = re.compile(r'^([a-g])(##|bb|[#bn])?(-?\d)(~?)$')
STAVES = {'TEN': ('Tenors', 'Where there are two notes, Tenor 1 sings the upper one.'),
          'LOW': ('Baritones and basses', 'Where there are two notes, the baritones sing the upper one.'),
          'T1': ('Tenor 1', ''), 'T2': ('Tenor 2', ''), 'BR': ('Baritone', ''), 'BS': ('Bass', ''), 'SOLO': ('Solo', ''),
          'TRIO': ('Trio, upper two voices', ''), 'TR1': ('Trio, first voice', ''), 'TR2': ('Trio, second voice', ''), 'TR3': ('Trio, third voice', '')}
LENGTH = {'w': 'whole', 'h': 'half', 'q': 'quarter', 'e': '8th', 's': '16th', 't': '32nd'}
SIGNS = {2: ' double sharp', 1: ' sharp', 0: '', -1: ' flat', -2: ' double flat'}


class Refused(ValueError):
    """A change that cannot be made, said in words for the person who asked for it."""


def backup(path):
    return path + '.as-read'


def _blocks(path):
    """The file as lines, and for every measure in it: where its lines are and what holds at its start."""
    lines = open(path).read().split('\n')
    state = dict(key=0, time='4/4', tempo=100., transpose={})
    blocks, cur = {}, None
    for i, raw in enumerate(lines):
        line = raw.split('//')[0].strip()
        if not line:
            continue
        if line.startswith('=='):
            cur = int(line.strip('= ').split()[0])
            blocks[cur] = dict(n=cur, at=i, key=state['key'], time=state['time'], tempo=state['tempo'], transpose=dict(state['transpose']), staves=[])
            continue
        head, _, rest = line.partition(':')
        head, rest = head.strip(), rest.strip()
        if head == 'key':
            state['key'] = int(rest)
        elif head == 'time':
            state['time'] = rest
        elif head == 'tempo':
            state['tempo'] = float(rest)
        elif head == 'transpose':
            name, semis = rest.split()
            state['transpose'][name] = int(semis)
        elif head in scoremod.VOCAL and cur is not None:
            blocks[cur]['staves'].append((i, head))
    return lines, blocks


def _tokens(raw):
    """A staff's line -> (what stands before the notes, its tokens, the comment after them)."""
    body, sep, comment = raw.partition('//')
    head, _, rest = body.partition(':')
    return head + ':', rest.split(), (sep + comment if sep else '')


def _shift(name, tr):
    return tr.get(name, 0) + (tr.get('TEN', 0) if name in ('T1', 'T2') else 0) + (tr.get('TRIO', 0) if name in ('TR1', 'TR2') else 0) + \
        (tr.get('LOW', 0) if name in ('BR', 'BS') else 0)


def _keysig(key, letter):
    if key > 0 and letter in scoremod.SHARPS[:key]:
        return 1
    if key < 0 and letter in scoremod.FLATS[:-key]:
        return -1
    return 0


def _clefs(lines, blocks):
    """Which clef each staff is printed in: told from where its notes lie (tenors are printed in the treble clef)."""
    where = {}
    for b in blocks.values():
        for i, name in b['staves']:
            for tok in _tokens(lines[i])[1]:
                m = scoremod.TOKEN.match(tok)
                if m and m['p'] != 'r':
                    for p in m['p'].split('+'):
                        q = PITCH.match(p)
                        where.setdefault(name, []).append(int(q[3]) * 7 + LETTERS.index(q[1]))
    return {name: ('treble' if sorted(v)[len(v) // 2] >= 27 else 'bass') for name, v in where.items()}      # (27: the B below middle C)


def _length(code):
    name = LENGTH[code[0]]
    rest = code[1:]
    if rest.startswith('3'):
        name = 'triplet ' + name; rest = rest[1:]
    return ('dotted ' * len(rest)) + name


def outline(path):
    """What the page needs to find its way: the measures there are, in order, and the words sung in each."""
    lines, blocks = _blocks(path)
    words = {}
    for n, b in blocks.items():
        said = []
        for i, name in b['staves']:
            text = ''
            for tok in _tokens(lines[i])[1]:
                m = scoremod.TOKEN.match(tok)
                if m and m['l'] and m['l'] not in ('_', '*'):
                    text += m['l'][:-1] if m['l'].endswith('-') else m['l'] + ' '
            said.append(text.strip())
        words[n] = ' / '.join(s for s in dict.fromkeys(said) if s)
    changed = 0
    if os.path.exists(backup(path)):
        was = [l for l in open(backup(path)).read().split('\n') if not l.startswith('// read from')]
        now = [l for l in lines if not l.startswith('// read from')]
        changed = sum(a != b for a, b in zip(was, now)) + abs(len(was) - len(now))
    return dict(measures=list(blocks), words=words, changed=changed, locked='=*' in '\n'.join(lines))


def measure(path, n):
    """One measure as the page shows it."""
    lines, blocks = _blocks(path)
    if n not in blocks:
        raise Refused(f'There is no measure {n} in this piece.')
    b, order, clefs = blocks[n], list(blocks), _clefs(lines, blocks)
    at = order.index(n)
    staves = []
    for i, name in b['staves']:
        shift, acc, notes = _shift(name, b['transpose']), {}, []
        for t, tok in enumerate(_tokens(lines[i])[1]):
            m = scoremod.TOKEN.match(tok)
            if not m:
                continue                                   # a dynamic mark: left where it is, not shown
            note = dict(t=t, beats=scoremod._dur(m['d']), length=_length(m['d']), code=m['d'], rest=m['p'] == 'r',
                        word='' if m['l'] in (None, '_', '*') else m['l'], held=m['l'] == '_', tie='~' in (m['f'] or ''), pitches=[])
            if not note['rest']:
                for k, p in enumerate(m['p'].split('+')):
                    q = PITCH.match(p)
                    letter, sign, octave = q[1], q[2] or '', q[3]
                    if sign:
                        acc[(letter, octave)] = {'##': 2, 'bb': -2, '#': 1, 'b': -1, 'n': 0}[sign]
                    alter = acc.get((letter, octave), _keysig(b['key'], letter))
                    midi = 12 * (int(octave) + 1) + scoremod.STEP[letter] + alter + shift
                    note['pitches'].append(dict(k=k, letter=letter.upper(), sign=sign, octave=int(octave), step=int(octave) * 7 + LETTERS.index(letter),
                                                midi=midi, sounds=letter.upper() + SIGNS[alter], tie=bool(q[4])))
            notes.append(note)
        label, hint = STAVES.get(name, (name, ''))
        staves.append(dict(line=i, name=name, label=label, hint=hint, clef=clefs.get(name, 'bass'), notes=notes))
    return dict(n=n, prev=order[at - 1] if at else None, next=order[at + 1] if at + 1 < len(order) else None,
                first=order[0], last=order[-1], time=b['time'], tempo=b['tempo'], key=b['key'], staves=staves)


def _change(path, n, line, t, new):
    """Replace token t of the staff line at `line` (in measure n) by new(the token's parts) and make sure the score
    still reads; if it does not, put the file back and say why."""
    lines, blocks = _blocks(path)
    if n not in blocks or line not in [i for i, _ in blocks[n]['staves']]:
        raise Refused('That measure has changed. Open it again.')
    head, toks, comment = _tokens(lines[line])
    if not 0 <= t < len(toks) or not scoremod.TOKEN.match(toks[t]):
        raise Refused('That note is no longer there. Open the measure again.')
    toks[t] = new(scoremod.TOKEN.match(toks[t]))
    if not scoremod.TOKEN.match(toks[t]):
        raise Refused('That cannot be written as a note.')
    before = '\n'.join(lines)
    if not os.path.exists(backup(path)):
        shutil.copy(path, backup(path))
    lines[line] = head + ' ' + ' '.join(toks) + ((' ' + comment) if comment else '')
    open(path, 'w').write('\n'.join(lines))
    try:
        scoremod.load(path)
    except Exception as e:
        open(path, 'w').write(before)
        raise Refused(f'That change does not fit the music ({e}). Nothing was changed.')
    return measure(path, n)


def move(path, n, line, t, k, step=0, sign=None):
    """Move one note up or down the staff by `step` lines-and-spaces, or give it a sign: '#', 'b', 'n', or '' for none."""
    def new(m):
        if m['p'] == 'r':
            raise Refused('That is a rest.')
        ps = m['p'].split('+')
        if not 0 <= k < len(ps):
            raise Refused('That note is no longer there. Open the measure again.')
        q = PITCH.match(ps[k])
        letter, s, octave = q[1], q[2] or '', int(q[3])
        if step:
            at = octave * 7 + LETTERS.index(letter) + step
            if not 1 * 7 <= at <= 6 * 7:
                raise Refused('That is as far as a voice goes.')
            letter, octave, s = LETTERS[at % 7], at // 7, ''     # a sign belongs to the line it was printed on: it does not move with the note
        if sign is not None:
            if sign not in ('', '#', 'b', 'n'):
                raise Refused('Choose sharp, flat, natural or no sign.')
            s = sign
        ps[k] = f'{letter}{s}{octave}{q[4]}'
        return '+'.join(ps) + '/' + m['d'] + (m['f'] or '') + ('=' + m['l'] if m['l'] else '')
    return _change(path, n, line, t, new)


def word(path, n, line, t, text):
    """The word (or syllable) under one note.  '' takes it away; a hyphen at its end means the word goes on."""
    text = (text or '').strip()
    if re.search(r'[\s/=]', text):
        raise Refused('One word or syllable to a note, with no spaces. Put the next word under the next note.')
    if text == '*' or len(text) > 40:
        raise Refused('That cannot be sung as a word.')

    def new(m):
        if m['p'] == 'r':
            raise Refused('A rest has no word.')
        if m['l'] == '*':
            raise Refused('The words of this piece are kept in a separate file and cannot be changed here.')
        return m['p'] + '/' + m['d'] + (m['f'] or '') + ('=' + text if text else '')
    return _change(path, n, line, t, new)


def undo_all(path):
    """Put the score back as it was read."""
    if os.path.exists(backup(path)):
        os.replace(backup(path), path)


def find(path, text):
    """The measures in which a word is sung."""
    want = re.sub(r'[^a-z\']', '', text.lower())
    if not want:
        return []
    return [n for n, said in outline(path)['words'].items() if want in re.sub(r'[^a-z\' /]', '', said.lower()).replace(' ', '') or
            any(w.startswith(want) for w in re.sub(r'[^a-z\' ]', ' ', said.lower()).split())]
