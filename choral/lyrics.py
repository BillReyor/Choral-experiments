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
    'ye': [['Y', 'IY1']], 'oh': [['OW1']], 'o': [['OW1']], 'ah': [['AA1']], 'oo': [['UW1']],
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


def pronounce(word, nsyl, overrides, next_word=None, warn=print):
    """Return nsyl engine syllables for a word."""
    w = word.strip("'") if word not in overrides else word
    if word in overrides:
        cands = [overrides[word]]
    elif w == 'the':
        nxt = (next_word or 'x').lstrip("'")
        cands = [[['DH', 'IY0']]] if nxt[:1] in 'aeio' else [[['DH', 'AH0']]]
    else:
        prons = FIXED.get(w) or _cmu().get(w) or _cmu().get(w.replace("'", ''))
        if not prons:                          # a prefix "a-" glued on: "a-feeding", "a-stray"
            if w.startswith('a') and _cmu().get(w[1:]):
                prons = [['AH0'] + p for p in _cmu()[w[1:]]]
        if not prons:
            warn(f'  ! no pronunciation for "{word}" - singing "ah"; add a  say:  line to the score')
            return ['AA'] + ['-'] * (nsyl - 1)
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
