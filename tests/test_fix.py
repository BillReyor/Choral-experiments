"""choral/fix.py: the page's "Fix a note or a word" - showing one measure and changing one note or word in a score."""
import os

import pytest

from choral import fix
from choral import score as scoremod

TEN, LOW = 14, 15          # the demo score's line numbers (0-based) for measure 2's tenor and low staves


def ten_notes(path, n=2):
    st = next(s for s in fix.measure(path, n)['staves'] if s['name'] == 'TEN')
    return st['notes']


# ---- reading a measure

def test_outline_lists_measures_and_joins_hyphenated_words(demo_score):
    o = fix.outline(demo_score)
    assert o['measures'] == [1, 2, 3, 4, 5]
    assert o['words'][2] == 'Shenandoah I long to'
    assert o['words'][4] == 'way you rolling river'
    assert o['changed'] == 0
    assert o['locked'] is False


def test_measure_navigation(demo_score):
    m = fix.measure(demo_score, 2)
    assert (m['prev'], m['next'], m['first'], m['last']) == (1, 3, 1, 5)
    assert m['time'] == '4/4' and m['tempo'] == 66.0 and m['key'] == -1
    assert fix.measure(demo_score, 1)['prev'] is None
    assert fix.measure(demo_score, 5)['next'] is None


def test_unknown_measure_is_refused(demo_score):
    with pytest.raises(fix.Refused):
        fix.measure(demo_score, 99)


def test_measure_applies_key_signature_and_tenor_transposition(demo_score):
    notes = ten_notes(demo_score)
    # F major (one flat): the written b4 sounds B flat, and tenor staves sound an octave lower (transpose: TEN -12)
    last = notes[-1]['pitches'][0]
    assert (last['letter'], last['sign'], last['sounds']) == ('B', '', 'B flat')
    assert last['midi'] == 12 * 5 + 11 - 1 - 12
    assert notes[0]['pitches'][0]['midi'] == 53          # f4 written, sounds F3
    assert [n['word'] for n in notes] == ['Shen-', 'an-', 'doah', 'I', 'long', 'to']


def test_measure_shows_chords_and_clefs(demo_score):
    staves = {s['name']: s for s in fix.measure(demo_score, 2)['staves']}
    assert staves['TEN']['clef'] == 'treble' and staves['LOW']['clef'] == 'bass'
    first = staves['LOW']['notes'][0]
    assert [p['letter'] for p in first['pitches']] == ['F', 'A']


def test_accidental_lasts_to_the_barline(demo_score):
    fix.move(demo_score, 2, TEN, 4, 0, sign='#')         # a4 -> a#4 ...
    fix.move(demo_score, 2, TEN, 5, 0, step=-1)           # ... and the next note b4 -> a4 inherits the sharp
    notes = ten_notes(demo_score)
    assert notes[4]['pitches'][0]['sounds'] == 'A sharp'
    assert notes[5]['pitches'][0]['sounds'] == 'A sharp'
    assert notes[5]['pitches'][0]['sign'] == ''


# ---- changing notes

def test_move_changes_only_that_token_and_keeps_a_backup(demo_score):
    before = open(demo_score).read()
    fix.move(demo_score, 2, TEN, 3, 0, step=1)            # g4 -> a4
    after = open(demo_score).read()
    assert 'g4/e=I' in before and 'a4/e=I' in after
    diff = [(a, b) for a, b in zip(before.split('\n'), after.split('\n')) if a != b]
    assert len(diff) == 1 and diff[0][0].replace('g4/e=I', 'a4/e=I') == diff[0][1]
    assert open(fix.backup(demo_score)).read() == before
    assert fix.outline(demo_score)['changed'] == 1
    scoremod.load(demo_score)                              # still a valid score


def test_move_drops_the_printed_sign_when_the_note_moves(demo_score):
    fix.move(demo_score, 2, TEN, 3, 0, sign='#')           # g#4
    fix.move(demo_score, 2, TEN, 3, 0, step=1)             # moves to a line of its own: a4, no sign
    assert 'a4/e=I' in open(demo_score).read()


def test_move_within_a_chord(demo_score):
    fix.move(demo_score, 2, LOW, 0, 1, step=-1)            # f3+a3 -> f3+g3
    assert open(demo_score).read().split('\n')[LOW].split()[1] == 'f3+g3/e'


@pytest.mark.parametrize('kwargs, message', [
    (dict(t=3, k=0, sign='x'), 'sharp, flat, natural'),
    (dict(t=3, k=5, step=1), 'no longer there'),
    (dict(t=99, k=0, step=1), 'no longer there'),
    (dict(t=3, k=0, step=40), 'as far as a voice goes'),
])
def test_move_refusals(demo_score, kwargs, message):
    before = open(demo_score).read()
    with pytest.raises(fix.Refused, match=message):
        fix.move(demo_score, 2, TEN, **kwargs)
    assert open(demo_score).read() == before


def test_a_rest_cannot_be_moved(demo_score):
    with pytest.raises(fix.Refused, match='rest'):
        fix.move(demo_score, 1, 11, 1, 0, step=1)          # measure 1 TEN: "!mp r/h. c4/q=Oh" -> token 1 is the rest


def test_a_change_that_breaks_the_score_is_rolled_back(demo_score, monkeypatch):
    before = open(demo_score).read()

    def broken(path, *a, **k):
        raise scoremod.ScoreError('does not add up')
    monkeypatch.setattr(scoremod, 'load', broken)
    with pytest.raises(fix.Refused, match='Nothing was changed'):
        fix.move(demo_score, 2, TEN, 3, 0, step=1)
    assert open(demo_score).read() == before


# ---- changing words

def test_word_replaces_and_removes_a_syllable(demo_score):
    fix.word(demo_score, 2, TEN, 3, 'We')
    assert 'g4/e=We' in open(demo_score).read()
    fix.word(demo_score, 2, TEN, 3, '')
    assert ten_notes(demo_score)[3]['word'] == ''


@pytest.mark.parametrize('text', ['two words', 'a/b', 'x=y', '*', 'a' * 41])
def test_word_refuses_what_cannot_be_one_syllable(demo_score, text):
    with pytest.raises(fix.Refused):
        fix.word(demo_score, 2, TEN, 3, text)


def test_a_rest_has_no_word(demo_score):
    with pytest.raises(fix.Refused, match='rest'):
        fix.word(demo_score, 1, 11, 1, 'la')


def test_spoken_toggles_the_x_flag(demo_score):
    fix.spoken(demo_score, 2, TEN, 3, True)
    assert 'g4/ex=I' in open(demo_score).read()
    assert ten_notes(demo_score)[3]['spoken'] is True
    fix.spoken(demo_score, 2, TEN, 3, False)
    assert 'g4/e=I' in open(demo_score).read()


# ---- undo and search

def test_undo_all_restores_the_score_as_read(demo_score):
    before = open(demo_score).read()
    fix.move(demo_score, 2, TEN, 3, 0, step=1)
    fix.word(demo_score, 3, 19, 0, "here")
    fix.undo_all(demo_score)
    assert open(demo_score).read() == before
    assert not os.path.exists(fix.backup(demo_score))
    fix.undo_all(demo_score)                                # nothing to undo: no error


def test_find_matches_whole_and_partial_words(demo_score):
    assert fix.find(demo_score, 'River') == [4]
    assert fix.find(demo_score, 'shen') == [2]
    assert fix.find(demo_score, 'Shenandoah!') == [2]
    assert fix.find(demo_score, 'zebra') == []
    assert fix.find(demo_score, '!!') == []
