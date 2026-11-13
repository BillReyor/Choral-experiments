"""choral/score.py: the plain-text score format (docs/score-format.md)."""
import pytest

from choral import score
from choral.score import ScoreError


def parse(text):
    warnings = []
    sc = score.parse(text, warn=warnings.append)
    sc.warnings = warnings
    return sc


def midis(sc, part='T1'):
    return [n['midi'] for n in sc.parts[part]]


def timing_of(notes):
    return [(round(n['beat'], 4), round(n['dur'], 4)) for n in notes]


# ---------------------------------------------------------------- pitches ----
def test_middle_c_and_octaves():
    sc = parse('== 1\nT1: c4/q c5/q a4/q b3/q\n')
    assert midis(sc) == [60, 72, 69, 59]


def test_written_accidentals():
    sc = parse('== 1\nT1: f#4/q bb3/q f##4/q bbb3/q\n')
    assert midis(sc) == [66, 58, 67, 57]


def test_accidental_lasts_to_the_barline_then_resets():
    sc = parse('== 1\nT1: f#4/q f4/q fn4/q f4/q\n== 2\nT1: f4/w\n')
    assert midis(sc) == [66, 66, 65, 65, 65]


def test_accidental_applies_only_to_its_own_octave():
    sc = parse('== 1\nT1: f#4/h f5/h\n')
    assert midis(sc) == [66, 77]


def test_key_signature_sharps():
    # two sharps: F# and C#; other letters untouched
    sc = parse('key: 2\n== 1\nT1: f4/q c4/q g4/q fn4/q\n')
    assert midis(sc) == [66, 61, 67, 65]


def test_key_signature_flats_and_change_between_measures():
    sc = parse('key: -1\n== 1\nT1: b3/q e4/h b3/q\nkey: -2\n== 2\nT1: b3/h e4/h\nkey: 0\n== 3\nT1: b3/w\n')
    assert midis(sc) == [58, 64, 58, 58, 63, 59]


def test_natural_overrides_key_signature_until_barline():
    sc = parse('key: -1\n== 1\nT1: bn3/q b3/q b3/h\n== 2\nT1: b3/w\n')
    assert midis(sc) == [59, 59, 59, 58]


# --------------------------------------------------------------- durations ----
@pytest.mark.parametrize('code,beats', [
    ('w', 4.), ('h', 2.), ('q', 1.), ('e', .5), ('s', .25), ('t', .125),
    ('q.', 1.5), ('h.', 3.), ('q..', 1.75), ('e3', 1 / 3), ('q3', 2 / 3),
])
def test_duration_codes(code, beats):
    assert score._dur(code) == pytest.approx(beats)


def test_beats_and_measures_accumulate():
    sc = parse('time: 3/4\n== 1\nT1: c4/q. c4/e c4/q\n== 2\nT1: c4/e3 c4/e3 c4/e3 c4/q.. c4/s\n')
    assert timing_of(sc.parts['T1']) == [(0, 1.5), (1.5, .5), (2, 1), (3, .3333), (3.3333, .3333),
                                         (3.6667, .3333), (4, 1.75), (5.75, .25)]
    assert sc.measures == {1: (0., 3.), 2: (3., 3.)}
    assert sc.beats == 6.


def test_rests_take_time_but_make_no_note():
    sc = parse('== 1\nT1: r/q c4/q r/h\n')
    assert timing_of(sc.parts['T1']) == [(1, 1)]


def test_absent_line_is_a_bar_of_rest():
    sc = parse('== 1\nT1: c4/w\n== 2\nT2: d4/w\n')
    assert timing_of(sc.parts['T1']) == [(0, 4)]
    assert timing_of(sc.parts['T2']) == [(4, 4)]


@pytest.mark.parametrize('text', [
    '== 1\nT1: c4/h\n',                       # short
    '== 1\nT1: c4/w c4/q\n',                  # long
    'time: 3/4\n== 1\nT1: c4/w\n',
    '== 1\nT1: c4/e3 c4/e3 c4/h.\n',          # an incomplete triplet
])
def test_measure_that_does_not_add_up_is_refused(text):
    with pytest.raises(ScoreError, match='adds up to'):
        parse(text)


def test_compound_time_counted_in_eighths():
    sc = parse('time: 6/8\n== 1\nT1: c4/q. c4/q.\n')
    assert sc.measures[1] == (0., 3.)
    sc = parse('time: 10/8\n== 1\nT1: c4/h c4/h c4/q\n')
    assert sc.measures[1] == (0., 5.)


def test_time_and_tempo_changes_between_measures():
    sc = parse('tempo: 60\n== 1\nT1: c4/w\ntime: 3/4\ntempo: 90\n== 2\nT1: c4/h.\n== 3\nT1: c4/h.\n')
    assert sc.measures == {1: (0., 4.), 2: (4., 3.), 3: (7., 3.)}
    assert sc.tempo == [(0., 60.), (4., 90.)]
    assert sc.beats == 10.


def test_default_tempo_when_none_given():
    assert parse('== 1\nT1: c4/w\n').tempo == [(0., 100.)]


# -------------------------------------------------------------------- ties ----
def test_tie_joins_same_pitch_across_barline():
    sc = parse('== 1\nT1: c4/h c4/h~\n== 2\nT1: c4/h d4/h\n')
    assert timing_of(sc.parts['T1']) == [(0, 2), (2, 4), (6, 2)]
    assert midis(sc) == [60, 60, 62]


def test_tie_to_a_different_pitch_is_a_slur():
    sc = parse('== 1\nT1: c4/h~=la d4/h\n')
    assert [n['lyric'] for n in sc.parts['T1']] == ['la', '_']
    assert sc.parts['T1'][1]['phon'] == '-'


def test_syllable_on_tied_note_is_ignored_with_warning():
    sc = parse('== 1\nT1: c4/h~=la c4/h=lo\n')
    assert len(sc.parts['T1']) == 1 and sc.parts['T1'][0]['lyric'] == 'la'
    assert any('tied note was ignored' in w for w in sc.warnings)


def test_tie_on_one_note_of_a_piano_chord():
    sc = parse('== 1\nRH: c4~+e4/h c4+e4/h\n')
    got = sorted((n['midi'], n['beat'], n['dur']) for n in sc.piano)
    assert got == [(60, 0., 4.), (64, 0., 2.), (64, 2., 2.)]


# ------------------------------------------------------------------ chords ----
def test_shared_staff_two_notes_split_top_to_first_part():
    sc = parse('== 1\nTEN: c4+e4/w=Ah\nLOW: c3+g3/w\n')
    assert midis(sc, 'T1') == [64] and midis(sc, 'T2') == [60]
    assert midis(sc, 'BR') == [55] and midis(sc, 'BS') == [48]


def test_shared_staff_one_note_both_parts():
    sc = parse('== 1\nTEN: d4/w=Ah\n')
    assert midis(sc, 'T1') == [62] and midis(sc, 'T2') == [62]


def test_shared_staff_three_notes_first_tenors_split():
    sc = parse('== 1\nTEN: c4+e4+g4/w=Ah\n')
    assert midis(sc, 'T1') == [(67, 64)]
    assert midis(sc, 'T2') == [60]


def test_piano_chord_gives_one_note_per_pitch():
    sc = parse('== 1\nRH: c4+e4+g4/w\nLH: c3/w\n')
    assert sorted((n['hand'], n['midi']) for n in sc.piano) == [('LH', 48), ('RH', 60), ('RH', 64), ('RH', 67)]


# ---------------------------------------------------------------- lyrics ----
def test_voice_without_words_borrows_its_partners():
    sc = parse('== 1\nT1: c4/w=Ah\nT2: a3/w\n')
    assert sc.parts['T2'][0]['lyric'] == 'Ah'
    assert sc.parts['T2'][0]['phon'] == sc.parts['T1'][0]['phon'] == 'AA'


def test_slur_continues_syllable():
    sc = parse('== 1\nT1: c4/q=la c4/q=_ d4/h=lo\n')
    assert [(n['lyric'], n['phon']) for n in sc.parts['T1']] == [('la', 'l AA'), ('_', '-'), ('lo', 'l OW')]


def test_syllables_joined_into_words():
    sc = parse('== 1\nT1: c4/h=mer- c4/h=ry\n')
    assert [n['phon'] for n in sc.parts['T1']] == ['m EH', 'r IY']


def test_say_override():
    sc = parse("say: zorp = Z AO1 R . P IY1\nsay: heav'nly = HH EH1 V . N L IY0\n"
               "== 1\nT1: c4/h=Zorp- c4/h=py\n== 2\nT1: c4/h=heav'n- c4/h=ly\n")
    assert sc.say == {'zorp': [['Z', 'AO1', 'R'], ['P', 'IY1']], "heav'nly": [['HH', 'EH1', 'V'], ['N', 'L', 'IY0']]}
    assert [n['phon'] for n in sc.parts['T1']] == ['z AO r', 'p IY', 'h EH v', 'n l IY']


def test_language_latin():
    sc = parse('language: latin\n== 1\nT1: c4/q=Sanc- c4/q=tus c4/h=Do-\n== 2\nT1: c4/h=mi- c4/h=nus\n')
    assert sc.language == 'latin'
    assert [n['phon'] for n in sc.parts['T1']] == ['s LA ng k', 't LU s', 'd LO', 'm LI', 'n LU s']


# --------------------------------------------------------------- transpose ----
def test_transpose_staff_and_parts():
    sc = parse('transpose: TEN -12\ntranspose: RH 2\n== 1\nTEN: c5/w\nLOW: c3/w\nRH: c4/w\n')
    assert midis(sc, 'T1') == [60] and midis(sc, 'T2') == [60]
    assert midis(sc, 'BR') == [48]
    assert sc.piano[0]['midi'] == 62


def test_transpose_ten_also_applies_to_t1_t2_lines():
    sc = parse('transpose: TEN -12\n== 1\nT1: c5/w\nT2: a4/w\n')
    assert midis(sc, 'T1') == [60] and midis(sc, 'T2') == [57]


# ---------------------------------------------------------------- dynamics ----
def test_dynamics_and_crescendo_ramp():
    sc = parse('== 1\nT1: !p c4/h !cresc c4/h\n== 2\nT1: !f c4/w\n')
    assert sc.marks['voice'] == [(0., 'p'), (2., 'cresc'), (4., 'f')]
    assert sc.dyn('voice', 0) == pytest.approx(.52)
    assert sc.dyn('voice', 3) == pytest.approx((.52 + .88) / 2)
    assert sc.dyn('voice', 5) == pytest.approx(.88)


def test_default_dynamic_is_mf():
    assert parse('== 1\nT1: c4/w\n').dyn('voice', 0) == pytest.approx(.74)


def test_unknown_dynamic_refused():
    with pytest.raises(ScoreError, match='unknown dynamic'):
        parse('== 1\nT1: !zz c4/w\n')


# --------------------------------------------------------------- repeats ----
def test_play_order():
    assert score.play_order('1-3 2-3 4', {1: 0, 2: 0, 3: 0, 4: 0}) == [1, 2, 3, 2, 3, 4]


def test_play_order_unknown_measure_refused():
    with pytest.raises(ScoreError):
        score.play_order('1-5', {1: 0, 2: 0})


def test_play_unrolls_repeats_and_renumbers():
    sc = parse('play: 1-2 1-3\n== 1\nT1: c4/w\n== 2\nT1: d4/w\n== 3\nT1: e4/w\n')
    assert sc.printed == {1: 1, 2: 2, 3: 1, 4: 2, 5: 3}
    assert midis(sc) == [60, 62, 60, 62, 64]
    assert sorted(sc.measures) == [1, 2, 3, 4, 5]
    assert sc.beats == 20.


def test_no_play_line_means_no_printed_map():
    assert parse('== 1\nT1: c4/w\n').printed is None


def test_tie_does_not_reach_across_a_jump():
    sc = parse('play: 1-2 1-3\n== 1\nT1: c4/w~\n== 2\nT1: c4/w~\n== 3\nT1: c4/w\n')
    # 1~2 tied, jump back (tie dropped), 1~2~3 tied
    assert timing_of(sc.parts['T1']) == [(0, 8), (8, 12)]


def test_play_puts_key_tempo_and_time_right_at_a_jump():
    text = ('key: 0\ntempo: 60\ntime: 4/4\nplay: 2 1 3\n'
            '== 1\nT1: f4/w\nkey: 1\ntempo: 120\ntime: 3/4\n== 2\nT1: f4/h.\n== 3\nT1: f4/h.\n')
    sc = parse(text)
    assert sc.printed == {1: 2, 2: 1, 3: 3}
    assert sc.measures == {1: (0., 3.), 2: (3., 4.), 3: (7., 3.)}
    assert midis(sc) == [66, 65, 66]
    assert sorted(sc.tempo) == [(0., 60.), (0., 120.), (3., 60.), (7., 120.)]


def test_play_restores_default_time_signature_at_a_jump():
    text = 'play: 2 1\n== 1\nT1: c4/w\ntime: 3/4\n== 2\nT1: c4/h.\n'
    sc = parse(text)
    assert sc.measures == {1: (0., 3.), 2: (3., 4.)}


def test_chord_note_tie_does_not_reach_across_a_jump():
    sc = parse('play: 1 1\n== 1\nRH: c4~+e4/w\n')
    c = sorted((n['beat'], n['dur']) for n in sc.piano if n['midi'] == 60)
    assert c == [(0., 4.), (4., 4.)]


# ------------------------------------------------------------------ swing ----
def test_swing_on_moves_offbeat_eighths_but_not_triplets():
    sc = parse('swing: on\n== 1\nRH: c4/e d4/e c4/e3 c4/e3 c4/e3 c4/h\n')
    assert sc.swing == [(0., pytest.approx(2 / 3))]
    assert timing_of(sc.piano) == [(0, .6667), (.6667, .3333), (1, .3333), (1.3333, .3333), (1.6667, .3333), (2, 2)]


def test_swing_share_and_off():
    assert parse('swing: 60\n== 1\nT1: c4/w\n').swing == [(0., pytest.approx(.6))]
    assert parse('swing: off\n== 1\nT1: c4/w\n').swing == [(0., None)]
    assert parse('swing: 50\n== 1\nT1: c4/w\n').swing == [(0., None)]


@pytest.mark.parametrize('value', ['maybe', '80', '45', '-60'])
def test_swing_invalid_refused(value):
    with pytest.raises(ScoreError):
        parse(f'swing: {value}\n== 1\nT1: c4/w\n')


def test_straight_passage_inside_swing():
    sc = parse('swing: on\nstraight: 1 1\n== 1\nRH: c4/e d4/e c4/e d4/e c4/h\n')
    assert timing_of(sc.piano) == [(0, .5), (.5, .5), (1, .6667), (1.6667, .3333), (2, 2)]
    assert sc.straight == [(0., 1.)]


def test_stretch_line():
    sc = parse('== 1\nT1: c4/w\nstretch: 3 2 1.8\n== 2\nT1: c4/w\n')
    assert sc.stretch == [(6., 2., 1.8)]


# ---------------------------------------------------------------- errors ----
def test_unknown_header_refused():
    with pytest.raises(ScoreError, match='do not understand "foo:"'):
        parse('foo: 1\n== 1\nT1: c4/w\n')


def test_notes_before_first_measure_refused():
    with pytest.raises(ScoreError, match='before the first'):
        parse('T1: c4/w\n')


def test_two_lines_for_one_staff_refused():
    with pytest.raises(ScoreError, match='two T1 lines'):
        parse('== 1\nT1: c4/w\nT1: c4/w\n')


@pytest.mark.parametrize('tok', ['c9x/w', 'h4/w', 'c4/z', 'c4'])
def test_unreadable_token_refused(tok):
    with pytest.raises(ScoreError, match='cannot read'):
        parse(f'== 1\nT1: {tok}\n')


def test_comments_ignored():
    sc = parse('title: X // a comment\n// a whole-line comment\n== 1   // measure\nT1: c4/w // note\n')
    assert sc.title == 'X' and midis(sc) == [60]


# -------------------------------------------------------------------- demo ----
def test_demo_score_loads(demo_score):
    sc = score.load(demo_score)
    assert sc.title.startswith('Shenandoah')
    assert sc.beats == 20. and sorted(sc.measures) == [1, 2, 3, 4, 5]
    assert sc.tempo == [(0., 66.)]
    assert all(len(sc.parts[p]) == 17 for p in ('T1', 'T2', 'BR', 'BS'))
    t1 = sc.parts['T1']
    # "Oh" on c4 written, sounding an octave lower (transpose: TEN -12); b4 flattened by the key
    assert t1[0]['midi'] == 48 and t1[0]['lyric'] == 'Oh'
    assert [n['midi'] for n in t1[1:7]] == [53, 53, 53, 55, 57, 58]
    # the say: line for "shenandoah"
    assert [n['phon'] for n in t1[1:4]] == ['sh EH n', 'AX n', 'd OW']
    assert len(sc.piano) == 38
