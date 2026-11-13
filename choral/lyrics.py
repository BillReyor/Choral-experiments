"""Sung text -> phonemes for the voice engine.

Words come from the score already split into sung syllables ("mer-", "ry").  Each word is looked
up in the CMU pronouncing dictionary, its phonemes are divided into the same number of syllables,
and each syllable is rewritten in the engine's alphabet ("m EH", "r IY").
"""
import re

_CMU = None

# CMU phoneme -> engine phoneme
CONS = {'B': 'b', 'CH': 'ch', 'D': 'd', 'DH': 'dh', 'F': 'f', 'G': 'g', 'HH': 'h', 'JH': 'jh', 'K': 'k', 'L': 'l',
        'M': 'm', 'N': 'n', 'NG': 'ng', 'P': 'p', 'R': 'r', 'S': 's', 'SH': 'sh', 'T': 't', 'TH': 'th', 'V': 'v',
        'W': 'w', 'Y': 'y', 'Z': 'z', 'ZH': 'zh'}
VOWELS = {'AA', 'AE', 'AH', 'AO', 'AW', 'AY', 'EH', 'ER', 'EY', 'IH', 'IY', 'OW', 'OY', 'UH', 'UW'}
ONSETS = {tuple(x.split()) for x in """
    P L|P R|B L|B R|T R|D R|K L|K R|G L|G R|F L|F R|TH R|SH R|S P|S T|S K|S M|S N|S L|S W|S F|T W|D W|K W|G W
    |S P R|S P L|S T R|S K R|S K W|HH Y|K Y|F Y|M Y|B Y|P Y|V Y|N Y""".replace('\n', ' ').split('|')}

# Words a singer does not pronounce the way the dictionary's first entry says.
FIXED = {
    'a': [['AH0']], 'to': [['T', 'UW1']], 'of': [['AH1', 'V']], 'and': [['AE1', 'N', 'D']],
    'ye': [['Y', 'IY1']], 'oh': [['OW1']], 'o': [['OW1']], 'ah': [['AA1']], 'oo': [['UW1']], 'ooh': [['UW1']], 'aah': [['AA1']], 'ahh': [['AA1']],
}
# Drum and bell syllables.  Singers do not hold the vowel on these: they close early and hum the
# rest of the note on the m or ng ("pummm", "dinnng").  '+' marks that: everything after it is held.
for _w, _p in {'pum': 'P AH1 + M', 'rum': 'R AH1 + M', 'tum': 'T AH1 + M', 'bum': 'B AH1 + M', 'dum': 'D AH1 + M',
               'pom': 'P AA1 + M', 'bom': 'B AA1 + M', 'dom': 'D AA1 + M', 'bim': 'B IH1 + M', 'bam': 'B AE1 + M',
               'ding': 'D IH1 + NG', 'dong': 'D AO1 + NG', 'bong': 'B AO1 + NG'}.items():
    FIXED[_w] = [_p.split()]


def _cmu():
    global _CMU
    if _CMU is None:
        import cmudict
        _CMU = cmudict.dict()
    return _CMU


def clean(s):
    """Strip punctuation from a sung syllable, keeping apostrophes and a trailing hyphen."""
    s = s.replace('’', "'").replace('‘', "'")
    hy = s.endswith('-')
    s = re.sub(r"[^A-Za-z']", '', s)
    return s.lower() + ('-' if hy else '')


def syllabify(phones):
    """Split a CMU pronunciation into syllables: each consonant cluster gives the following vowel
    the longest onset English allows."""
    vi = [i for i, p in enumerate(phones) if p.rstrip('012') in VOWELS]
    if not vi:
        return [phones]
    cuts = [0]
    for a, b in zip(vi[:-1], vi[1:]):
        cluster = [p for p in phones[a + 1:b]]
        k = len(cluster)                       # how many consonants stay with the earlier syllable
        for take in range(len(cluster), 0, -1):
            on = tuple(cluster[-take:])
            if take == 1 and on[0] not in ('NG',) or on in ONSETS:
                k = len(cluster) - take
                break
        cuts.append(a + 1 + k)
    cuts.append(len(phones))
    return [phones[c0:c1] for c0, c1 in zip(cuts[:-1], cuts[1:])]


def to_engine(syl):
    out = []
    for p in syl:
        base, stress = p.rstrip('012'), p[-1] if p[-1] in '012' else ''
        if p == '+':
            out.append('+')
        elif base in VOWELS:
            out.append('AX' if base == 'AH' and stress == '0' else base)
        else:
            out.append(CONS[base])
    return ' '.join(out)


# ---- words spelled alike and said differently.  The dictionary lists both readings and does not say which is which.
# A song nearly always means one of them; for a few, the word before or after says otherwise.
#   word: (the usual reading in a song, the other one, words before it that call for the other, words after it that do)
ALIKE = {
    'lives': ('L AY1 V Z', 'L IH1 V Z', 'he she it who that which god christ jesus lord love hope spirit redeemer savior saviour still ever never always there', ''),
    'live': ('L IH1 V', None, '', ''),
    'wind': ('W IH1 N D', None, '', ''), 'winds': ('W IH1 N D Z', None, '', ''),
    'tear': ('T IH1 R', 'T EH1 R', "to will shall would could can cannot can't don't they we you", 'apart down away'),
    'tears': ('T IH1 R Z', None, '', ''),
    'read': ('R IY1 D', 'R EH1 D', "have has had was were been be i've we've you've they've having", ''),
    'lead': ('L IY1 D', None, '', ''), 'leads': ('L IY1 D Z', None, '', ''),
    'wound': ('W UW1 N D', None, '', ''),
    'bass': ('B EY1 S', None, '', ''),
    'sow': ('S OW1', None, '', ''),
    'minute': ('M IH1 N AH0 T', None, '', ''),
    'present': ('P R EH1 Z AH0 N T', 'P R IY0 Z EH1 N T', 'to we i they you shall will let now', ''),
    'presents': ('P R EH1 Z AH0 N T S', None, '', ''),
    'close': ('K L OW1 S', 'K L OW1 Z', 'to', 'your the my his her their our it them a every all'),
    'use': ('Y UW1 Z', 'Y UW1 S', 'the no of little good some any much its their his her', ''),
}


# ---- a word the dictionary does not have: a name, a word from another language, a misprint
_SPELL = [  # letters -> sounds, the longest match first; '$' is the end of the word, '^' its beginning
    ('eigh', 'EY'), ('augh', 'AO'), ('ough', 'OW'), ('tion$', 'SH AH N'), ('sion$', 'ZH AH N'), ('eus$', 'IY AH S'), ('ous$', 'AH S'),
    ('igh', 'AY'), ('sch', 'SH'), ('tch', 'CH'), ('dge', 'JH'), ('eau', 'OW'), ('que$', 'K'), ('ing$', 'IH NG'),
    ('ah$', 'AA'), ('uh$', 'AH'), ('oh$', 'OW'), ('eh$', 'EH'), ('^kn', 'N'), ('^wr', 'R'), ('^ps', 'S'), ('^gh', 'G'), ('rh', 'R'),
    ('ai', 'EY'), ('ay', 'EY'), ('au', 'AO'), ('aw', 'AO'), ('ea', 'IY'), ('ee', 'IY'), ('ei', 'EY'), ('ey', 'EY'), ('eu', 'UW'), ('ew', 'UW'),
    ('ie$', 'IY'), ('ie', 'IY'), ('oa', 'OW'), ('oe', 'OW'), ('oi', 'OY'), ('oy', 'OY'), ('oo', 'UW'), ('ou', 'AW'), ('ow', 'OW'),
    ('ue', 'UW'), ('ui', 'UW'), ('ch', 'CH'), ('ck', 'K'), ('gh', ''), ('ng', 'NG'), ('ph', 'F'), ('qu', 'K W'), ('sh', 'SH'),
    ('th', 'TH'), ('wh', 'W'), ('zh', 'ZH'),
    ('b', 'B'), ('d', 'D'), ('f', 'F'), ('j', 'JH'), ('k', 'K'), ('l', 'L'), ('m', 'M'), ('n', 'N'), ('p', 'P'), ('q', 'K'), ('r', 'R'),
    ('s', 'S'), ('t', 'T'), ('v', 'V'), ('x', 'K S'), ('z', 'Z')]


def guess(word):
    """Sounds for a word by its spelling alone (rough English rules, with the plain vowels most other languages
    use where a syllable is open).  -> CMU phonemes, every vowel full; None if the word has no vowel to sing."""
    w = re.sub(r"[^a-z]", '', word.lower())
    V = 'aeiouy'
    out, i, n = [], 0, len(w)
    while i < n:
        rest, c = w[i:], w[i]
        prev, nxt, nxt2 = (w[i - 1] if i else ''), (w[i + 1] if i + 1 < n else ''), (w[i + 2] if i + 2 < n else '')
        if nxt == c and c not in V:                              # a doubled consonant is one sound ("cc" before e or i is two)
            if c == 'c' and nxt2 in ('e', 'i', 'y') and nxt2:
                out += ['K', 'S']
            else:
                out += dict(_SPELL).get(c, '').split() or ({'c': ['K'], 'g': ['G']}.get(c, []))
            i += 2; continue
        hit = None
        for letters, sounds in _SPELL:
            key = letters.strip('^$')
            if rest.startswith(key) and (not letters.startswith('^') or i == 0) and (not letters.endswith('$') or i + len(key) == n):
                hit = (key, sounds); break
        if c in V or hit is None or c in 'cghw':
            if c in V and hit and len(hit[0]) > 1 and hit[0][0] in V:
                pass                                             # a vowel pair or ending from the table
            elif c == 'c':
                hit = ('ch', 'CH') if nxt == 'h' else ('ck', 'K') if nxt == 'k' else ('c', 'S' if nxt and nxt in 'eiy' else 'K')
            elif c == 'g':
                hit = hit if hit and len(hit[0]) > 1 else ('g', 'JH' if nxt and nxt in 'eiy' else 'G')
            elif c == 'h':
                hit = ('h', 'HH' if nxt and nxt in V else '')
            elif c == 'w':
                hit = hit if hit and len(hit[0]) > 1 else ('w', 'W' if nxt and nxt in V else '')
            elif c == 'y' and (i == 0 or prev in V) and nxt and nxt in 'aeiou':
                hit = ('y', 'Y')
            elif c in V:
                last = i == n - 1
                r_coloured = nxt == 'r' and (not nxt2 or nxt2 not in V)
                magic = nxt and nxt not in V and nxt2 == 'e' and i + 3 == n and nxt not in 'x'        # "ate", "ime": the e is silent
                open_ = nxt and nxt not in V and nxt2 and nxt2 in V and not magic or (w[i + 1:i + 3] in ('sh', 'ch', 'th', 'ph') and i + 3 < n and w[i + 3] in V)
                if c == 'e' and last and any(x in V for x in w[:i]):
                    if prev == 'l' and i >= 2 and w[i - 2] not in V and out and out[-1] == 'L':
                        out[-1:] = ['AH', 'L']                   # "kindle", "candle"
                    hit = ('e', '')
                elif r_coloured:
                    hit = (c + 'r', {'a': 'AA R', 'o': 'AO R'}.get(c, 'ER'))
                elif magic:
                    hit = (c, {'a': 'EY', 'e': 'IY', 'i': 'AY', 'o': 'OW', 'u': 'UW', 'y': 'AY'}[c])
                elif last:
                    hit = (c, {'a': 'AA', 'e': 'IY', 'i': 'IY', 'o': 'OW', 'u': 'UW', 'y': 'IY' if sum(x in V for x in w) > 1 else 'AY'}[c])
                elif nxt in V and nxt:                           # two vowels the table does not know: each its own ("ia", "io", "ua")
                    hit = (c, {'a': 'AA', 'e': 'IY', 'i': 'IY', 'o': 'OW', 'u': 'UW', 'y': 'IY'}[c])
                elif open_:
                    hit = (c, {'a': 'AA', 'e': 'EH', 'i': 'IH', 'o': 'OW', 'u': 'UW', 'y': 'IH'}[c])
                else:
                    hit = (c, {'a': 'AE', 'e': 'EH', 'i': 'IH', 'o': 'AA', 'u': 'AH', 'y': 'IH'}[c])
            elif hit is None:
                hit = (c, '')
        out += hit[1].split()
        i += len(hit[0])
    if not any(p in VOWELS for p in out):
        return None
    return [p + '1' if p in VOWELS else p for p in out]


def _near(w):
    """A word the dictionary has under another spelling: a letter left out for the metre ("ev'ry", "heav'n",
    "o'er", "singin'"), a letter doubled or not ("Halelujah")."""
    d = _cmu()
    if "'" in w:
        k = w.index("'")
        between = 0 < k < len(w) - 1 and w[k - 1] in 'aeiou' and w[k + 1] in 'aeiou'        # "o'er", "e'er", "ne'er": a v is left out
        for ch in ('v' if between else 'eoaiu'):
            if d.get(w.replace("'", ch, 1)):
                return d[w.replace("'", ch, 1)]
    if w.endswith('in') and d.get(w + 'g'):
        return [p[:-1] + ['N'] for p in d[w + 'g'] if p[-1] == 'NG']
    single = re.sub(r'(.)\1', r'\1', w)
    if single != w and d.get(single):
        return d[single]
    for i in range(1, len(w)):                                   # ...or one letter doubled that we have single
        if w[i] != w[i - 1] and d.get(w[:i] + w[i - 1] + w[i:]) and w[i - 1] not in 'aeiou':
            return d[w[:i] + w[i - 1] + w[i:]]
    return None


SMALL = set('a i o of in on to the and or by at up go no so we me my be he do it is as an out off for'.split())


def _compound(w, nsyl):
    """Words printed with hyphens between them and sung to as many notes as they have syllables - "mer-ry-go-round" -
    arrive here as one word no dictionary has.  If it divides into two to four dictionary words (each of three
    letters or more, or one of the small common ones) whose syllables are exactly the notes it is set to, it is said
    as those words.  -> [phonemes] or None."""
    w = w.replace("'", '')
    if not 5 <= len(w) <= 24 or not w.isalpha():
        return None
    d = _cmu()
    count = lambda p: sum(x[-1:].isdigit() for x in p)
    best = None

    def walk(i, parts, phones):
        nonlocal best
        if i == len(w):
            if len(parts) >= 2 and count(phones) == nsyl and (best is None or len(parts) < len(best[0])):
                best = (list(parts), list(phones))
            return
        if len(parts) == 4:
            return
        for j in range(len(w), i, -1):
            piece = w[i:j]
            if (len(piece) >= 3 or piece in SMALL) and piece in d:
                walk(j, parts + [piece], phones + d[piece][0])

    walk(0, [], [])
    return [best[1]] if best else None


def pronounce(word, nsyl, overrides, next_word=None, warn=print, prev_word=None):
    """Return nsyl engine syllables for a word."""
    w = word.strip("'") if word not in overrides else word
    if word in overrides:
        cands = [overrides[word]]
    elif w in ALIKE:
        usual, other, before, after = ALIKE[w]
        swap = other and ((prev_word or '').strip("'").lower() in before.split() or (next_word or '').strip("'").lower() in after.split())
        cands = [syllabify((other if swap else usual).split())]
    elif w == 'the':
        nxt = (next_word or 'x').lstrip("'")
        cands = [[['DH', 'IY0']]] if nxt[:1] in 'aeio' else [[['DH', 'AH0']]]
    else:
        prons = FIXED.get(w) or _cmu().get(w) or _cmu().get(w.replace("'", ''))
        if not prons:                          # a vowel drawn out in print: "Ooo", "oooh", "aaah"
            short = re.sub(r'(.)\1{2,}', r'\1\1', w)
            prons = FIXED.get(short) or _cmu().get(short) if short != w else None
        if not prons:                          # a prefix "a-" glued on: "a-feeding", "a-stray"
            if w.startswith('a') and _cmu().get(w[1:]):
                prons = [['AH0'] + p for p in _cmu()[w[1:]]]
        if not prons:
            prons = _near(w.strip("'")) or _near(w)
        if not prons:
            prons = _compound(w, nsyl)
        if not prons:
            g = guess(w)
            if not g:
                warn(f'  ! no pronunciation for "{word}" - singing "ah"; add a  say:  line to the score')
                return ['AA'] + ['-'] * (nsyl - 1)
            warn(f'  ! "{word}" is not in the dictionary - sung as it is spelled ({" ".join(x.rstrip("1") for x in g)}); a  say:  line in the score corrects it')
            prons = [g]
        cands = [syllabify(p) for p in prons]
    exact = [c for c in cands if len(c) == nsyl]
    if exact:   # prefer the fullest vowels: sung text is not reduced the way speech is
        best = min(exact, key=lambda c: sum(p == 'AH0' for s in c for p in s) if w not in ('a', 'the') else 0)
        return [to_engine(s) for s in best]
    c = cands[0]
    warn(f'  ! "{word}" is set to {nsyl} note-syllable(s) but pronounced with {len(c)}; fitting it')
    if len(c) > nsyl:                          # more spoken syllables than notes: crowd the tail into the last
        head, tail = c[:nsyl - 1], [p for s in c[nsyl - 1:] for p in s]
        first_v = next(i for i, p in enumerate(tail) if p.rstrip('012') in VOWELS)
        tail = [p for i, p in enumerate(tail) if i <= first_v or p.rstrip('012') not in VOWELS]
        return [to_engine(s) for s in head + [tail]]
    return [to_engine(s) for s in c] + ['-'] * (nsyl - len(c))


def parse_override(text):
    """'HH EH V . N L IY' -> [['HH','EH','V'], ['N','L','IY']] (CMU phonemes, '.' between syllables)."""
    return [s.split() for s in text.strip().split('.')]
