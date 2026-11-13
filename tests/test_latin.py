"""choral/latin.py: church Latin, syllable by printed syllable."""
import pytest

from choral import latin


@pytest.mark.parametrize('syllables,want', [
    (['ex', 'cel', 'sis'], ['LE k', 'sh LE l', 's LI s']),          # the docstring's example: x+c before e
    (['Sanc', 'tus'], ['s LA ng k', 't LU s']),                      # n before c is ng
    (['pa', 'cem'], ['p LA', 'ch LE m']),                            # c softens before e
    (['coe', 'li'], ['ch LE', 'l LI']),                              # ... and before oe, which is "eh"
    (['cae', 'li'], ['ch LE', 'l LI']),                              # ae is "eh"
    (['sae', 'cu', 'lum'], ['s LE', 'k LU', 'l LU m']),              # c hard before u
    (['re', 'gi', 'na'], ['r LE', 'jh LI', 'n LA']),                 # g softens before i
    (['glo', 'ri', 'a'], ['g l LO', 'r LI', 'LA']),                  # g hard before l
    (['gra', 'ti', 'a'], ['g r LA', 't s LI', 'LA']),                # ti before a vowel is "tsee"
    (['ho', 'sti', 'a'], ['LO', 's t LI', 'LA']),                    # ... but not after s
    (['ma', 'gna'], ['m LA', 'n y LA']),                             # gn is ny
    (['A', 'gnus'], ['LA', 'n y LU s']),
    (['Ag', 'nus'], ['LA', 'n y LU s']),                             # ... however the printer divided the word
    (['mag', 'na'], ['m LA', 'n y LA']),
    (['dig', 'num'], ['d LI', 'n y LU m']),
    (['reg', 'num'], ['r LE', 'n y LU m']),
    (['an', 'ge', 'lus'], ['LA n', 'jh LE', 'l LU s']),              # n is ng only before a hard c or g: not here,
    (['vin', 'cit'], ['v LI n', 'ch LI t']),                         # nor here,
    (['san', 'guis'], ['s LA ng', 'g w LI s']),                      # but here
    (['Ho', 'san', 'na'], ['LO', 'z LA n', 'n LA']),                 # h silent, s softened between vowels
    (['mi', 'hi'], ['m LI', 'k LI']),                                # mihi: the h is a k
    (['ni', 'hil'], ['n LI', 'k LI l']),
    (['ec', 'ce'], ['LE t', 'ch LE']),                               # ec-ce: "et-cheh"
    (['Chri', 'ste'], ['k r LI', 's t LE']),                         # ch is k
    (['phi', 'lo'], ['f LI', 'l LO']),                               # ph is f
    (['qui'], ['k w LI']),
    (['lau', 'da'], ['l AW', 'd LA']),
    (['Je', 'su'], ['y LE', 'z LU']),                                # j is y
    (['ju', 'bi', 'la', 'te'], ['y LU', 'b LI', 'l LA', 't LE']),
    (['Ky', 'ri', 'e'], ['k LI', 'r LI', 'LE']),                     # y is i
    (['Ze', 'lo'], ['d z LE', 'l LO']),
    (['su', 'sci', 'pe'], ['s LU', 'sh LI', 'p LE']),                # sc before i is sh
    (['De', 'us'], ['d LE', 'LU s']),
])
def test_pronounce(syllables, want):
    assert latin.pronounce(syllables) == want


def test_punctuation_and_case_ignored():
    assert latin.pronounce(['SANC-', 'tus.']) == latin.pronounce(['sanc', 'tus'])


def test_vowels_are_the_engines_latin_vowels():
    assert [latin.syllable(v) for v in 'aeiou'] == ['LA', 'LE', 'LI', 'LO', 'LU']


def test_initial_i_before_vowel_is_a_glide():
    assert latin.syllable('pie') == 'p y LE'


def test_syllable_uses_neighbours():
    assert latin.syllable('ti', 'gra', 'a') == 't s LI'
    assert latin.syllable('ti', 'gra', 'bus') == 't LI'
    assert latin.syllable('') == ''


def test_every_syllable_has_a_vowel():
    import re
    for word in (['Glo', 'ri', 'a', 'in', 'ex', 'cel', 'sis', 'De', 'o'], ['Be', 'ne', 'dic', 'tus', 'qui', 've', 'nit']):
        for ph in latin.pronounce(word):
            assert re.search(r'\bL[AEIOU]\b|\bAW\b', ph), (word, ph)
