"""Church (Italianate) Latin, as choirs sing it -> phonemes for the voice engine.

Latin is far more regular than English, and the score already divides every word into its sung
syllables, so no dictionary is needed: each printed syllable is read letter by letter with the
handful of rules every chorister learns (c and g soften before e and i, "ti" before a vowel is
"tsee", "gn" is "ny", h is silent, vowels are pure).  Two choices were settled by measuring real
singers rather than by the rule book: the h of "Hosanna" is silent (no breath before the vowel),
and an s between vowels stays a hissed s (a softened z was heard as "l").
"""
V = {'a': 'LA', 'e': 'LE', 'i': 'LI', 'o': 'LO', 'u': 'LU', 'y': 'LI'}     # the engine's Latin vowels (voice.VOW)
FRONT = ('e', 'i', 'y', 'ae', 'oe')


def _front(rest):
    return rest.startswith(FRONT)


def syllable(s, prev='', nxt=''):
    """One printed syllable -> engine phonemes.  prev / nxt are the neighbouring syllables of the same word."""
    s = s.lower()
    out, i, seen_vowel = [], 0, False
    while i < len(s):
        two, c, rest = s[i:i + 2], s[i], s[i + 1:]
        after = rest or nxt                       # what follows this letter, looking into the next syllable
        if two in ('ae', 'oe'):
            ph, i = 'LE', i + 1
        elif two == 'au':
            ph, i = 'AW', i + 1
        elif two == 'qu':
            ph, i = 'k w', i + 1
        elif two in ('ch',):
            ph, i = 'k', i + 1
        elif two == 'ph':
            ph, i = 'f', i + 1
        elif two == 'th':
            ph, i = 't', i + 1
        elif two == 'gn':
            ph, i = 'n y', i + 1
        elif two == 'sc' and _front(s[i + 2:] or nxt):
            ph, i = 'sh', i + 1
        elif c == 'c':
            if not rest and nxt.startswith('c') and _front(nxt[1:]):
                ph = 't'                          # ec-ce
            elif _front(after):
                ph = 'sh' if (i == 0 and prev.endswith('x')) else 'ch'   # ex-cel-sis
            else:
                ph = 'k'
        elif c == 'g':
            ph = 'jh' if _front(after) else 'g'
        elif c == 'h':
            ph = 'k' if (prev + s) in ('mihi', 'nihil') and i == 0 and prev else ''
        elif c == 'j' or (c == 'i' and not seen_vowel and rest[:1] in V and rest[:1] != ''):
            ph = 'y'
        elif c == 't' and rest == 'i' and nxt[:1] in V and not prev.endswith(('s', 't', 'x')) and i > 0 - 1 \
                and not (i > 0 and s[i - 1] in 'stx'):
            ph = 't s'                            # gra-ti-a
        elif c == 'x':
            ph = 'k' if nxt.startswith('c') and _front(nxt[1:]) and not rest else 'k s'
        elif c == 'z':
            ph = 'd z'
        elif c == 'n' and (rest[:1] in ('c', 'g', 'q', 'x') or (not rest and nxt[:1] in ('c', 'g', 'q'))):
            ph = 'ng'
        elif c in V:
            if seen_vowel and out and out[-1] in V.values():   # two vowels left in one syllable: glide into the second
                out[-1] = {'LI': 'y', 'LU': 'w'}.get(out[-1], out[-1])
                if out[-1] in V.values():
                    i += 1
                    continue
            ph, seen_vowel = V[c], True
        elif c.isalpha():
            ph = c
        else:
            ph = ''
        out += ph.split()
        i += 1
    return ' '.join(out)


def pronounce(syllables):
    """['ex', 'cel', 'sis'] -> ['LE k', 'sh LE l', 's LI s']"""
    syl = [''.join(ch for ch in s.lower() if ch.isalpha()) for s in syllables]
    return [syllable(s, syl[k - 1] if k else '', syl[k + 1] if k + 1 < len(syl) else '') for k, s in enumerate(syl)]
