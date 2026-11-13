"""choral/lyrics.py: sung words -> engine phonemes."""
import pytest

from choral import lyrics as L


def say(word, nsyl=1, overrides=None, nxt=None, prv=None):
    warnings = []
    out = L.pronounce(word, nsyl, overrides or {}, nxt, warnings.append, prv)
    return out, warnings


# ------------------------------------------------------------------ clean ----
@pytest.mark.parametrize('raw,want', [
    ('Lord,', 'lord'), ('Shen-', 'shen-'), ('“Ev’ry!”', "ev'ry"), ('O!-', 'o-'),
    ("heav'n;", "heav'n"), ('(Amen.)', 'amen'),
])
def test_clean(raw, want):
    assert L.clean(raw) == want


# ------------------------------------------------------------- overrides ----
def test_parse_override():
    assert L.parse_override(' HH EH1 V . N L IY0 ') == [['HH', 'EH1', 'V'], ['N', 'L', 'IY0']]
    assert L.parse_override('Z AH1 + M') == [['Z', 'AH1', '+', 'M']]


def test_override_wins_over_dictionary():
    out, _ = say('love', 1, {'love': [['L', 'UW1', 'V']]})
    assert out == ['l UW v']


# ------------------------------------------------------- dictionary words ----
@pytest.mark.parametrize('word,nsyl,want', [
    ('love', 1, ['l AH v']),
    ('merry', 2, ['m EH', 'r IY']),
    ('hallelujah', 4, ['h AE', 'l AX', 'l UW', 'y AX']),
    ('beautiful', 3, ['b y UW', 't AX', 'f AX l']),
])
def test_dictionary_lookup_split_into_syllables(word, nsyl, want):
    out, warnings = say(word, nsyl)
    assert out == want
    assert warnings == []


def test_fixed_singer_readings():
    assert say('a')[0] == ['AX']
    assert say('of')[0] == ['AH v']
    assert say('oh')[0] == ['OW']


def test_drum_syllables_hum_on_the_consonant():
    assert say('pum')[0] == ['p AH + m']
    assert say('ding')[0] == ['d IH + ng']


def test_the_before_vowel_and_consonant():
    assert say('the', nxt='earth')[0] == ['dh IY']
    assert say('the', nxt='sun')[0] == ['dh AX']


def test_drawn_out_vowel_spellings():
    assert say('ooo')[0] == ['UW']
    assert say('oooh')[0] == ['UW']


def test_a_prefix():
    assert say('afeeding', 3)[0] == ['AX', 'f IY', 'd IH ng']


def test_compound_of_dictionary_words():
    assert say('merrygoround', 4)[0] == ['m EH', 'r IY', 'g OW', 'r AW n d']


# --------------------------------------------------------- fuller spellings ----
def test_ev_ry_found_under_every():
    out, warnings = say("ev'ry", 2)
    assert out == ['EH v', 'r IY']
    assert not any('not in the dictionary' in w for w in warnings)


def test_heav_n_found_under_heaven():
    out, warnings = say("heav'n", 1)
    assert out == ['h EH v n']
    assert not any('not in the dictionary' in w for w in warnings)


def test_singin_found_under_singing():
    out, _ = say("singin'", 2)
    assert out == ['s IH ng', 'IH n']


def test_near_o_er_restores_the_v():
    assert L._near("o'er") == L._cmu()['over']


def test_o_er_on_one_note_keeps_its_r():
    out, _ = say("o'er", 1)
    assert out[0].split()[-1] == 'r' and 'v' not in out[0].split()


# ------------------------------------------------------------- homographs ----
@pytest.mark.parametrize('word,nxt,prv,want', [
    ('tear', None, None, 't IH r'),
    ('tear', 'apart', None, 't EH r'),
    ('tear', None, 'to', 't EH r'),
    ('read', None, None, 'r IY d'),
    ('read', None, 'have', 'r EH d'),
    ('close', None, None, 'k l OW s'),
    ('close', 'your', None, 'k l OW z'),
    ('lives', None, None, 'l AY v z'),
    ('lives', None, 'he', 'l IH v z'),
    ('live', None, 'he', 'l IH v'),
    ('wind', None, None, 'w IH n d'),
])
def test_homographs(word, nxt, prv, want):
    assert say(word, 1, nxt=nxt, prv=prv)[0] == [want]


# -------------------------------------------------------- unknown words ----
def test_unknown_word_spelled_by_rule_and_reported():
    out, warnings = say('zorblax', 2)
    assert out == ['z AO r', 'b l AE k s']
    assert any('not in the dictionary' in w and 'Z AO R B L AE K S' in w for w in warnings)


def test_word_with_no_vowel_sings_ah():
    out, warnings = say('xqzv', 2)
    assert out == ['AA', '-']
    assert any('no pronunciation' in w for w in warnings)


@pytest.mark.parametrize('word,want', [
    ('kate', ['K', 'EY1', 'T']),
    ('candle', ['K', 'AE1', 'N', 'D', 'AH1', 'L']),
    ('kyrie', ['K', 'IH1', 'R', 'IY1']),
    ('nation', ['N', 'AA1', 'SH', 'AH1', 'N']),
    ('knight', ['N', 'AY1', 'T']),
])
def test_guess(word, want):
    assert L.guess(word) == want


def test_guess_no_vowel():
    assert L.guess('brrr') is None


# --------------------------------------------------- fitting to the notes ----
def test_fewer_notes_than_syllables_crowds_the_tail():
    out, warnings = say('beautiful', 2)
    assert out == ['b y UW', 't AX f l']
    assert any('fitting it' in w for w in warnings)


def test_more_notes_than_syllables_pads_with_holds():
    out, _ = say('love', 3)
    assert out == ['l AH v', '-', '-']


# ------------------------------------------------------------- syllabify ----
@pytest.mark.parametrize('phones,want', [
    ('HH AE1 P IY0', [['HH', 'AE1'], ['P', 'IY0']]),
    ('AH0 S T R EY1', [['AH0'], ['S', 'T', 'R', 'EY1']]),        # "str" is a legal onset
    ('M AH1 NG K IY0', [['M', 'AH1', 'NG'], ['K', 'IY0']]),
    ('S IH1 NG IH0 NG', [['S', 'IH1', 'NG'], ['IH0', 'NG']]),    # no syllable begins with ng
    ('K AE1 N D AH0 L', [['K', 'AE1', 'N'], ['D', 'AH0', 'L']]),
    ('HH M', [['HH', 'M']]),                                     # no vowel: one piece
])
def test_syllabify(phones, want):
    assert L.syllabify(phones.split()) == want


def test_to_engine():
    assert L.to_engine(['AH0', 'B', 'AH1', '+', 'M']) == 'AX b AH + m'
    assert L.to_engine(['SH', 'IY1', 'NG', 'ZH', 'ER0']) == 'sh IY ng zh ER'


# ------------------------------------------------- letters and run-together words ----
@pytest.mark.parametrize('letter, want', [('t', 't IY'), ('s', 'EH s'), ('u', 'y UW'), ('b', 'b IY'), ("v's", 'v IY z')])
def test_a_letter_set_to_a_note_is_said_by_its_name(letter, want):
    out, warnings = say(letter)                 # a name spelled out, one capital to a note: the reader hands each on in lower case
    assert out == [want] and not warnings


def test_compound_may_use_the_small_common_words():
    out, warnings = say('upanddown', 3)         # "up-and-down" as the reader joins it: "up" is too short for the rule, and allowed by name
    assert out == ['AH', 'p AX n d', 'd AW n'] and not warnings


# ------------------------------------------- a word the dictionary has, with an s it has not ----
# A listener heard a possessive sung by its spelling, and the page called it "not a word it knows": the dictionary
# had the word and not its 's.  So it was with most possessives - "beauty's" came out "bow-tis".
@pytest.mark.parametrize('word, stem, nsyl, ending', [
    ("tempest's", 'tempest', 2, 's'),            # after a sound without voice: s
    ("velvet's", 'velvet', 2, 's'),
    ("beauty's", 'beauty', 2, 'z'),              # after a voiced one: z
    ("melody's", 'melody', 3, 'z'),
    ("lavender's", 'lavender', 3, 'z'),
    ('carousels', 'carousel', 3, 'z'),           # ... and the same for a plain plural the dictionary lacks,
    ("jubilees'", 'jubilee', 3, 'z'),            # and for the possessive of one
])
def test_a_known_word_with_an_s_is_that_word_and_the_s(word, stem, nsyl, ending):
    whole, _ = say(stem, nsyl)
    out, warnings = say(word, nsyl)
    assert not warnings                                       # it is a word it knows
    assert out == whole[:-1] + [whole[-1] + ' ' + ending]     # sung as the word is, with the s on the end of it


def test_after_a_hiss_the_s_is_a_syllable_of_its_own():
    out, warnings = say("thrush's", 2)
    assert not warnings and out == ['th r AH', 'sh IH z']
    out, warnings = say("compass's", 3)
    assert not warnings and out[2] == 's IH z'


def test_a_short_word_ending_in_s_is_not_taken_for_a_plural():
    out, warnings = say('nos')                                # another language's word, not two of "no": too short to tell
    assert warnings and 'not in the dictionary' in warnings[0]
    assert out != ['n OW z']


def test_a_possessive_the_dictionary_has_is_left_to_it():
    assert say("angel's", 2)[0] == say('angels', 2)[0]
