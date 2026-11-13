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


def measure(path, n, unsure=()):
    """One measure as the page shows it.  unsure: the doubts there are about the piece (doubts()): the notes they
    point at in this measure are marked, and the doubts themselves are handed back with it."""
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
                        word='' if m['l'] in (None, '_', '*') else m['l'], held=m['l'] == '_', tie='~' in (m['f'] or ''), spoken='x' in (m['f'] or ''), pitches=[])
            if not note['rest']:
                for k, p in enumerate(m['p'].split('+')):
                    q = PITCH.match(p)
                    letter, sign, octave = q[1], q[2] or '', q[3]
                    before = dict(acc)                     # the signs in force where this note stands, its own aside
                    if sign:
                        acc[(letter, octave)] = {'##': 2, 'bb': -2, '#': 1, 'b': -1, 'n': 0}[sign]
                    alter = acc.get((letter, octave), _keysig(b['key'], letter))
                    midi = 12 * (int(octave) + 1) + scoremod.STEP[letter] + alter + shift
                    # What it would sound as if it were moved (move(), below) - a step up or down the staff, or given
                    # a sign, or none: the page plays that at the click.  Waiting until the change was written, the
                    # sound came seconds late on a computer busy making tracks, and a browser allows a page to make
                    # sound only just after a click.  None: a move that would be refused.
                    place = int(octave) * 7 + LETTERS.index(letter)
                    as_ = lambda l, o, a=None: 12 * (int(o) + 1) + scoremod.STEP[l] + shift + \
                        (before.get((l, str(o)), _keysig(b['key'], l)) if a is None else a)
                    stepped = lambda d: as_(LETTERS[(place + d) % 7], (place + d) // 7) if 7 <= place + d <= 42 else None
                    would = {'up': stepped(1), 'down': stepped(-1), '#': as_(letter, octave, 1), 'b': as_(letter, octave, -1),
                             'n': as_(letter, octave, 0), '': as_(letter, octave)}
                    note['pitches'].append(dict(k=k, letter=letter.upper(), sign=sign, octave=int(octave), step=place,
                                                midi=midi, sounds=letter.upper() + SIGNS[alter], tie=bool(q[4]), would=would))
            notes.append(note)
        label, hint = STAVES.get(name, (name, ''))
        staves.append(dict(line=i, name=name, label=label, hint=hint, clef=clefs.get(name, 'bass'), notes=notes))
    here = [d for d in unsure if n in d.get('measures', ())]
    for d in here:
        for st in staves:
            start, run = 0., []
            for note in st['notes']:
                if any(part in scoremod.VOCAL[st['name']] and abs(start - (beat - 1)) < 1e-6 for part, beat in d.get('notes', {}).get(str(n), ())):
                    note.setdefault('doubt', []).append(d['key'])         # which doubts point at this note
                if d.get('syllable'):                            # the very syllable that was doubted
                    if note['word'] == d['syllable']:
                        note.setdefault('doubt', []).append(d['key'])
                elif d.get('word') and not note['rest']:         # the notes a doubted word is sung on
                    if note['word']:
                        run.append(note)
                        if not note['word'].endswith('-'):
                            if _plain(''.join(x['word'] for x in run)) == _plain(d['word']):
                                for x in run:
                                    x.setdefault('doubt', []).append(d['key'])
                            run = []
                start += note['beats']
    return dict(n=n, prev=order[at - 1] if at else None, next=order[at + 1] if at + 1 < len(order) else None,
                first=order[0], last=order[-1], time=b['time'], tempo=b['tempo'], key=b['key'], staves=staves,
                doubts=[d['key'] for d in here])


def _plain(word):
    return re.sub(r"[^a-z']", '', word.lower())


PARTS = {'T1': 'Tenor 1', 'T2': 'Tenor 2', 'BR': 'Baritone', 'BS': 'Bass', 'SOLO': 'the soloist', 'TR1': 'the trio (first voice)',
         'TR2': 'the trio (second voice)', 'TR3': 'the trio (third voice)'}
NTH = {1: '1st', 2: '2nd', 3: '3rd'}


def _who(parts):
    names = [PARTS.get(p, p) for p in sorted(parts, key=list(PARTS).index)]
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def _span(ms):
    ms = sorted(ms)
    return f'measure {ms[0]}' if len(ms) == 1 else f'measures {ms[0]} to {ms[-1]}' if ms[-1] - ms[0] == len(ms) - 1 else 'measures ' + ', '.join(map(str, ms[:6])) + (' ...' if len(ms) > 6 else '')


def doubts(path, read_log=''):
    """Everything the program was unsure of in this piece, in words a singer can act on, each tied to the measures to look
    at.  Two kinds of source: what the score says when it is loaded as it now stands (a note with no word, a syllable
    with no vowel, a word not in the dictionary - these go away when they are put right), and what the reader of a
    scan said while it read (a line of music whose measures it miscounted - these stay until someone says they have
    looked).  The loader counts measures as they are performed; with repeats that is not how they are printed, and
    one printed measure sung three times is one place to look, not three."""
    said = []
    try:
        sc = scoremod.load(path, warn=said.append)
    except Exception as e:
        return [dict(key='broken', kind='broken', measures=[], title='The music no longer adds up',
                     text=f'Something in it cannot be read ({e}). "Undo all my changes" puts it back as it was first read.')]
    printed = sc.printed or {}
    lines, blocks = _blocks(path)
    systems, cur = {}, None                               # (page, line of music) -> the measures printed there
    for raw in lines:
        m = re.match(r'\s*// page (\d+), system (\d+)', raw)
        if m:
            cur = (int(m[1]), int(m[2]))
        elif raw.strip().startswith('==') and cur:
            systems.setdefault(cur, []).append(int(raw.split('//')[0].strip('= \t').split()[0]))
    found = {}

    def add(key, **kw):
        d = found.setdefault(key, dict(key=key, measures=[], notes={}, parts=[]))
        for k, v in kw.items():
            if k == 'measure':
                if v not in d['measures']:
                    d['measures'].append(v)
            elif k == 'note':
                n, part, beat = v
                d['notes'].setdefault(str(n), [])
                if [part, beat] not in d['notes'][str(n)]:
                    d['notes'][str(n)].append([part, beat])
                if part not in d['parts']:
                    d['parts'].append(part)
            else:
                d[k] = v
        return d
    for line in said:
        line = line.strip().lstrip('!? ').strip()
        m = re.match(r'measure (\d+) (\w+): no syllable for the note on beat ([\d.]+)', line)
        if m:
            n = printed.get(int(m[1]), int(m[1]))
            add(f'noword|{n}', kind='noword', measure=n, note=(n, m[2], float(m[3])))
            continue
        m = re.match(r'measure (\d+) (\w+): "(.+)" has no vowel to sing', line)
        if m:
            n = printed.get(int(m[1]), int(m[1]))
            add(f'novowel|{n}|{m[3]}', kind='novowel', measure=n, word=m[3], syllable=m[3]).setdefault('parts', [])
            if m[2] not in found[f'novowel|{n}|{m[3]}']['parts']:
                found[f'novowel|{n}|{m[3]}']['parts'].append(m[2])
            continue
        m = re.match(r'measure (\d+) (\w+): a syllable on a tied note was ignored', line)
        if m:
            n = printed.get(int(m[1]), int(m[1]))
            d = add(f'tied|{n}', kind='tied', measure=n)
            if m[2] not in d['parts']:
                d['parts'].append(m[2])
            continue
        m = re.match(r'"(.+)" is not in the dictionary', line)
        if m:
            add(f'unknown|{_plain(m[1])}', kind='unknown', word=m[1])
            continue
        m = re.match(r'"(.+)" is set to (\d+) note-syllable\(s\) but pronounced with (\d+)', line)
        if m:
            add(f'fitting|{_plain(m[1])}', kind='fitting', word=m[1], given=int(m[2]), needs=int(m[3]))
            continue
        m = re.match(r'no pronunciation for "(.+)"', line)
        if m:
            add(f'nopron|{_plain(m[1])}', kind='nopron', word=m[1])
    for line in read_log.splitlines():
        line = line.strip().lstrip('!? ').strip()
        m = re.match(r'page (\d+) system (\d+): found (\d+) measures on the page but (\d+) were read', line)
        if m:
            add(f'miscount|{m[1]}|{m[2]}', kind='miscount', page=int(m[1]), system=int(m[2]), saw=int(m[3]), read=int(m[4]))
            continue
        m = re.match(r'page (\d+) system (\d+): (\d+) staves on the page but (\d+) were read', line)
        if m:
            add(f'staves|{m[1]}|{m[2]}', kind='staves', page=int(m[1]), system=int(m[2]), saw=int(m[3]), read=int(m[4]))
            continue
        m = re.match(r'page (\d+) system (\d+): the staves were read with different numbers of measures', line)
        if m:
            add(f'uneven|{m[1]}|{m[2]}', kind='uneven', page=int(m[1]), system=int(m[2]))
            continue
        if line.startswith('no text recognition here'):
            add('nowords', kind='nowords')
        elif line.startswith('a D.S. is printed but its sign was not found'):
            add('order', kind='order')
    # A line of music whose barlines were not all found is common in scans, and seldom does harm: the words are put
    # under the notes by where both stand.  One line of it is worth pointing at; many are one remark, not many alarms.
    lost = [d for d in found.values() if d['kind'] == 'miscount']
    if len(lost) > 2:
        for d in lost:
            del found[d['key']]
        first = sorted(systems[(d['page'], d['system'])][0] for d in lost if systems.get((d['page'], d['system'])))
        found['barlines'] = dict(key='barlines', kind='barlines', measures=first, notes={}, parts=[], lines=len(lost))
    words = None
    out = []
    for d in found.values():
        k = d['kind']
        if k in ('unknown', 'fitting', 'nopron'):
            if words is None:
                words = outline(path)['words']
            want = _plain(d['word'])
            d['measures'] = [n for n, text in words.items() if want and want in [_plain(w) for w in re.split(r'[ /]+', text)]]
        if k in ('miscount', 'staves', 'uneven'):
            d['measures'] = list(systems.get((d['page'], d['system']), []))
            place = f"Page {d['page']}, {NTH.get(d['system'], str(d['system']) + 'th')} line of music" + (f" ({_span(d['measures'])})" if d['measures'] else '')
        d['measures'].sort()
        where = _span(d['measures']).capitalize() if d['measures'] else ''
        if k == 'noword':
            d.update(title=f'{where}: a note with no word', text=f'The reader found no word under a note for {_who(d["parts"])}, so the vowel before it is held. '
                     'That is right when one syllable is sung over several notes.', do='If your music has a word under the marked note, type it in the box below it. Otherwise it is right as it is.')
        elif k == 'novowel':
            d.update(title=f'{where}: a syllable that cannot be sung', text=f'The reader read “{d["syllable"]}” as a syllable under a note for {_who(d["parts"])}, and there is no vowel in it to sing. It is probably a misreading.',
                     do='Type what your music has under the marked note.')
        elif k == 'tied':
            d.update(title=f'{where}: a word under a tied note', text=f'A tied note only holds the note before it, so the word the reader found under it ({_who(d["parts"])}) was left out.',
                     do='If the word belongs here, type it under the note where it really starts.')
        elif k == 'unknown':
            d.update(title=f'“{d["word"]}” is not a word it knows' + (f' ({_span(d["measures"])})' if d['measures'] else ''),
                     text='It will be sung the way it is spelled. A name, another language, or a sound like “doo” is fine.',
                     do='If it is a misreading, correct the spelling under the marked notes. Otherwise it is right as it is.')
        elif k == 'fitting':
            d.update(title=f'“{d["word"]}” does not fit its notes' + (f' ({_span(d["measures"])})' if d['measures'] else ''),
                     text=f'The reader put this word under {d["given"]} note{"s" if d["given"] != 1 else ""}, but it is said in {d["needs"]} syllables, so it is squeezed to fit.',
                     do='Check that each syllable sits under its own note, with a hyphen where the word goes on: “glo-” “ri-” “a”.')
        elif k == 'nopron':
            d.update(title=f'“{d["word"]}” could not be pronounced' + (f' ({_span(d["measures"])})' if d['measures'] else ''), text='It will be sung as “ah”.',
                     do='Correct its spelling under the marked notes.')
        elif k == 'miscount':
            d.update(title=f'{place}: the words may sit under the wrong notes', text=f'The reader counted {d["saw"]} measure{"s" if d["saw"] != 1 else ""} in this line of music but read {d["read"]}, '
                     'so it spaced the words out evenly.', do='Compare these measures with your music: are the notes there, and is each word under the right note?')
        elif k == 'barlines':
            d.update(title=f'On {d["lines"]} lines of music the reader could not find every barline',
                     text='That is common with scans. The words there were put under the notes by where each stands on the page, which is usually right.',
                     do='If words sound a note early or late somewhere, look at that measure. Otherwise this is fine as it is.')
        elif k == 'staves':
            d.update(title=f'{place}: a part may be missing', text=f'The reader saw {d["saw"]} staves in this line of music and could read {d["read"]} of them.',
                     do='Compare these measures with your music: is every part there?')
        elif k == 'uneven':
            d.update(title=f'{place}: the parts may not line up', text='The staves in this line of music were read with different numbers of measures.',
                     do='Compare these measures with your music: is any part ahead of the others, or behind?')
        elif k == 'nowords':
            d.update(title='The words could not be read', text='This computer has nothing to read printed words with, so the notes have no words.', do='')
        elif k == 'order':
            d.update(title='The order of the music may be wrong', text='A repeat sign (D.S.) is printed, but the reader could not find the place it sends the music back to.', do='')
        out.append(d)
    return sorted(out, key=lambda d: (d['measures'][0] if d['measures'] else 10 ** 6, d['key']))


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


def spoken(path, n, line, t, on):
    """Mark one note as spoken, not sung (the x-shaped notehead of the printed music), or as sung again."""
    def new(m):
        if m['p'] == 'r':
            raise Refused('That is a rest.')
        flags = (m['f'] or '').replace('x', '')
        return m['p'] + '/' + m['d'] + ('x' if on else '') + flags + ('=' + m['l'] if m['l'] else '')
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
