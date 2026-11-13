"""Pure helpers of tools/scan2score.py: no homr, no text recognition."""
from fractions import Fraction as F

import pytest

import scan2score as S


def N(on, ql, midi, name, voice='1', chord=False, tie=False, exact=True, slur=()):
    return dict(on=F(on), ql=F(ql), midi=midi, name=name, voice=voice, chord=chord, tie=tie, slur=list(slur), exact=exact, x=None)


def names(line):
    return [(n and n['name'], a, b) for n, a, b in line]


@pytest.fixture(autouse=True)
def no_pdf_text(monkeypatch):
    """The words are recognized ones (not a PDF's own text) unless a test says otherwise."""
    monkeypatch.setitem(S.TEXT, 'pages', {})


# ------------------------------------------------------------------- note values ----
@pytest.mark.parametrize('ql, out', [(F(4), ['w']), (F(3), ['h.']), (F(7, 2), ['h.', 'e']), (F(5), ['w', 'q']),
                                     (F(5, 4), ['q', 's']), (F(2, 3), ['q3']), (F(1, 3), ['e3']), (F(1, 8), ['t']), (F(0), [])])
def test_spell(ql, out):
    assert S.spell(ql) == out


def test_name_of():
    assert S.name_of('C', 0, 4) == 'cn4'
    assert S.name_of('B', -1, 3) == 'bb3'
    assert S.name_of('F', 2, 5) == 'f##5'


# ------------------------------------------------------------- the score's tokens ----
def test_tokens_rests_ties_syllables_and_octave():
    n1, n2 = N(0, 3, 67, 'gn4', tie=True), N(3, 1, 67, 'gn4')
    up, _ = S.lines_of([n1, n2], F(4))
    assert S.tokens(up, {id(n1): 'Shen-'}) == ['gn4/h.~=Shen-', 'gn4/q']
    long_ = N(0, F(5, 2), 60, 'cn4')                        # a length that takes two values is tied across them
    up, _ = S.lines_of([long_, N(F(5, 2), F(3, 2), None, None)], F(4))
    assert S.tokens(up) == ['cn4/h~', 'cn4/e', 'r/q.']
    assert S.tokens(up, up=-1) == ['cn3/h~', 'cn3/e', 'r/q.']
    spoken = dict(N(0, 4, 60, 'cn4'), spoken=True)
    assert S.tokens([[spoken, F(0), F(4)]]) == ['cn4/wx']


# --------------------------------------------------------- two voices on one staff ----
def test_lines_of_exact_voices_kept_apart():
    ns = [N(0, 2, 67, 'gn4'), N(2, 2, 69, 'an4'), N(0, 4, 60, 'cn4', '2')]
    up, lo = S.lines_of(ns, F(4))
    assert names(up) == [('gn4', 0, 2), ('an4', 2, 4)]
    assert names(lo) == [('cn4', 0, 4)]


def test_lines_of_exact_voice_rests_where_it_rests():
    ns = [N(0, 4, 67, 'gn4'), N(0, 2, 60, 'cn4', '2'), N(2, 2, None, None, '2')]
    up, lo = S.lines_of(ns, F(4))
    assert S.tokens(up) == ['gn4/w'] and S.tokens(lo) == ['cn4/h', 'r/h']


def test_lines_of_recognized_chord_split_by_height():
    ns = [N(0, 4, 60, 'cn4', exact=False), N(0, 4, 67, 'gn4', chord=True, exact=False)]
    up, lo = S.lines_of(ns, F(4))
    assert S.tokens(up) == ['gn4/w'] and S.tokens(lo) == ['cn4/w']


def test_lines_of_unison_with_different_rhythm_believes_the_engine_voices():
    """Basses hold a C while baritones on the same C move on: by height alone the moving voice would vanish."""
    ns = [N(0, 4, 48, 'cn3', '1', exact=False, tie=True),
          N(0, 2, 48, 'cn3', '2', exact=False), N(2, 2, 50, 'dn3', '2', exact=False)]
    a, b = S.lines_of(ns, F(4))
    assert {tuple(S.tokens(a)), tuple(S.tokens(b))} == {('cn3/w~',), ('cn3/h', 'dn3/h')}


def test_layout_moves_overlong_voice_back_and_restores_lost_dot():
    ns = [N(1, 2, 67, 'gn4'), N(3, 2, 69, 'an4')]
    S.layout(ns, F(4))
    assert [(n['on'], n['ql']) for n in ns] == [(0, 2), (2, 2)]
    ns = [N(0, 2, 67, 'gn4'), N(2, 1, 69, 'an4')]                # stops half a beat short of a 7/8-ish bar
    S.layout(ns, F(7, 2))
    assert [(n['on'], n['ql']) for n in ns] == [(0, 2), (2, F(3, 2))]


def test_mark_melisma_ties_and_slurs():
    ms = [dict(notes=[N(0, 2, 67, 'gn4', tie=True), N(2, 2, 67, 'gn4')]),
          dict(notes=[N(0, 1, 60, 'cn4', slur=['start']), N(1, 1, 62, 'dn4'), N(2, 2, 64, 'en4', slur=['stop']), ])]
    ms[1]['notes'].append(N(4, 0, 65, 'fn4'))                    # after the slur: a new syllable
    S.mark_melisma(ms)
    a, b = ms[0]['notes']
    assert not a.get('tied_from') and b.get('tied_from')
    c, d, e, f = ms[1]['notes']
    assert not c.get('melisma') and d.get('melisma') and e.get('melisma') and not f.get('melisma')


def test_piano_lines_join_chords_and_fill_with_rests():
    ns = [N(0, 2, 64, 'en4', chord=True), N(0, 2, 60, 'cn4'), N(2, 1, 67, 'gn4')]
    assert S.piano_lines(ns, F(4), 'RH') == [('RH', ['cn4+en4/h', 'gn4/q', 'r/q'])]
    overlapping = [N(0, 2, 60, 'cn4'), N(1, 2, 62, 'dn4')]       # does not add up: dropped
    assert S.piano_lines(overlapping, F(4), 'LH') == []


def test_instrument_tremolo_and_unbracketed_triplets():
    trem = S.instrument_lines([N(0, 4, 60, 'cn4'), N(0, 4, 64, 'en4')], F(4))
    assert trem == [('IN', ['cn4/s', 'en4/s'] * 8)]
    six = [N(i, 1, 60 + i, f'{"cdefga"[i]}n4') for i in range(6)]
    assert S.instrument_lines(six, F(4)) == [('IN', ['cn4/q3', 'dn4/q3', 'en4/q3', 'fn4/q3', 'gn4/q3', 'an4/q3'])]


# -------------------------------------------------------------- MusicXML from homr ----
XML = """<?xml version="1.0"?>
<score-partwise><part id="P1">
<measure number="1"><attributes><divisions>2</divisions><key><fifths>-1</fifths></key><time><beats>3</beats><beat-type>4</beat-type></time><staves>2</staves>
<clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>
<barline><repeat direction="forward"/></barline>
<note><pitch><step>B</step><alter>-1</alter><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>half</type><staff>1</staff><tie type="start"/><!-- imgpos 120.5 40 --></note>
<note><chord/><pitch><step>D</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><type>half</type><staff>1</staff></note>
<note><rest/><duration>2</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>
<backup><duration>6</duration></backup>
<note><pitch><step>C</step><alter>1</alter><octave>3</octave></pitch><duration>6</duration><voice>5</voice><type>half</type><dot/><staff>2</staff><notations><slur type="start"/></notations></note>
</measure>
<measure number="2">
<note><grace/><pitch><step>A</step><octave>4</octave></pitch><voice>1</voice><staff>1</staff></note>
<note><rest/><duration>6</duration><voice>1</voice><staff>1</staff></note>
<note><pitch><step>E</step><octave>3</octave></pitch><duration>6</duration><voice>5</voice><staff>2</staff></note>
<barline><repeat direction="backward"/></barline>
</measure>
</part></score-partwise>
"""


def test_read_xml(tmp_path):
    p = tmp_path / 'sys.musicxml'
    p.write_text(XML)
    st = S.read_xml(str(p))
    assert [s['clef'] for s in st] == ['G', 'F'] and all(s['key'] == -1 for s in st)
    m1, m2 = st[0]['measures']
    assert m1['time'] == '3/4' and m1.get('rep_start') and m2.get('rep_end')
    bb, d, r = m1['notes']
    assert (bb['name'], bb['midi'], bb['ql'], bb['tie'], bb['x']) == ('bb4', 70, 2, True, 120.5)
    assert d['chord'] and d['on'] == 0 and d['midi'] == 74
    assert r['midi'] is None and r['on'] == 2 and r['ql'] == 1
    assert m2['notes'] == []                                     # a grace note is not sung; a whole-bar rest has no notes
    low = st[1]['measures'][0]['notes']
    assert [(n['name'], n['on'], n['ql'], n['slur']) for n in low] == [('c#3', 0, 3, ['start'])]
    assert st[1]['measures'][1]['notes'][0]['name'] == 'en3'


# -------------------------------------------------------------- staff names and roles ----
@pytest.mark.parametrize('text, role', [
    ('T 1', 'T1'), ('T 2', 'T2'), ('Tenor I', 'T1'), ('Tenor II', 'T2'), ('Tenor 1 2', 'TEN'), ('Tenors', 'TEN'),
    ('Bar.', 'BR'), ('Baritone', 'BR'), ('Bari', 'BR'), ('Baritone Bass', 'LOW'), ('B 1', 'BR'), ('B 2', 'BS'),
    ('Bass', 'BASS'), ('Bass 2', 'BS'), ('Cl.', 'I'), ('Clarinet in Bb', 'I'), ('Fl. 1', 'I'),
    ('Keybd.', 'P'), ('Piano', 'P'), ('Organ', 'P'), ('Drums', 'D'), ('Perc.', 'D'), ('Solo', 'SOLO'),
    ('xyz', None), ('', None)])
def test_label_role(text, role):
    assert S.label_role(text) == role


def _crop(clefs, kinds=None, labels=None):
    c = dict(read=[{'clef': k, 'measures': []} for k in clefs])
    if kinds:
        c['kinds'] = list(kinds)
    if labels:
        c['labels'] = labels
    return c


@pytest.mark.parametrize('clefs, kinds, piano, roles', [
    ('GGFFGF', 'vvvvpp', None, ['T1', 'T2', 'BR', 'BS', 'RH', 'LH']),
    ('GF', None, None, ['TEN', 'LOW']),
    ('GFGF', None, None, ['TEN', 'LOW', 'RH', 'LH']),          # with a piano, its two staves are the lowest
    ('GGF', 'vvv', False, ['SOLO', 'TEN', 'LOW']),
    ('GFGF', 'vvvv', False, ['TRIO', 'TR3', 'TEN', 'LOW']),    # treble, bass, treble, bass: a small group over the choir
])
def test_roles_by_counting_staves(clefs, kinds, piano, roles):
    cs = [_crop(clefs, kinds)]
    S.roles_for(cs, piano=piano)
    assert cs[0]['roles'] == roles


def test_roles_from_printed_names():
    cs = [_crop('GGFGF', 'vvvpp', ['I', 'TEN', 'LOW', 'P', 'P'])]       # a clarinet over the choir
    S.roles_for(cs)
    assert cs[0]['roles'] == ['I', 'TEN', 'LOW', 'RH', 'LH']
    cs = [_crop('GFGF', 'vvpp', ['BR', 'BASS', 'P', 'P'])]              # "Bass" under "Baritone" is the second basses
    S.roles_for(cs)
    assert cs[0]['roles'] == ['BR', 'BS', 'RH', 'LH']


# ----------------------------------------------------------------- clef correction ----
def test_reclef_moves_notes_and_keeps_key_and_accidentals():
    st = dict(clef='G', line='2', key=-1, measures=[dict(notes=[
        dict(midi=70, step='B', alter=-1, oct=4, name='bb4'),       # follows the key
        dict(midi=61, step='C', alter=1, oct=4, name='c#4'),        # its own sharp
        dict(midi=None, step=None, alter=None, oct=None, name=None)])])
    S.reclef(st, 'F')
    b, c, r = st['measures'][0]['notes']
    assert (b['name'], b['midi']) == ('dn3', 50)                  # middle line: B4 in treble, D3 in bass
    assert (c['name'], c['midi']) == ('e#2', 41)
    assert r['midi'] is None
    assert st['clef'] == 'F' and st['line'] is None


def test_fix_clefs_corrects_the_odd_one_out():
    def crop(i, clef):
        return dict(page=1, system=i, roles=['BS'], read=[dict(clef=clef, line=None, key=0, measures=[dict(notes=[
            dict(midi=55, step='G', alter=0, oct=3, name='gn3')])])])
    cs = [crop(i, 'F') for i in range(4)] + [crop(5, 'G')]
    logged = []
    S.fix_clefs(cs, logged.append)
    odd = cs[-1]['read'][0]
    assert odd['clef'] == 'F' and odd['measures'][0]['notes'][0]['name'] == 'bn1'
    assert len(logged) == 1 and 'BS' in logged[0]
    assert all(c['read'][0]['clef'] == 'F' and c['read'][0]['measures'][0]['notes'][0]['name'] == 'gn3' for c in cs[:4])


def test_fix_clefs_needs_enough_evidence():
    cs = [dict(page=1, system=i, roles=['BS'], read=[dict(clef=c, measures=[dict(notes=[dict(midi=55, step='G', alter=0, oct=3, name='gn3')])])])
          for i, c in enumerate('FFG')]
    S.fix_clefs(cs, lambda *a: None)
    assert [c['read'][0]['clef'] for c in cs] == ['F', 'F', 'G']


# ---------------------------------------------------------- repeats, D.S., coda ----
@pytest.mark.parametrize('n, nav, starts, ends, endings, order', [
    (6, [], set(), set(), (), None),                                               # nothing to unroll
    (6, [], set(), {3}, (), [1, 2, 3, 1, 2, 3, 4, 5, 6]),                          # repeat from the top
    (8, [], {3}, {5}, (), [1, 2, 3, 4, 5, 3, 4, 5, 6, 7, 8]),
    (6, [], {1}, {4}, [(4, [1]), (5, [2])], [1, 2, 3, 4, 1, 2, 3, 5, 6]),         # first and second endings
    (6, [('segno', 2), ('ds', 5)], set(), set(), (), [1, 2, 3, 4, 5, 2, 3, 4, 5, 6]),
    (8, [('segno', 2), ('ds coda', 6), ('to coda', 3), ('coda', 7)], set(), set(), (), [1, 2, 3, 4, 5, 6, 2, 3, 7, 8]),
    (6, [('dc fine', 6), ('fine', 2)], set(), set(), (), [1, 2, 3, 4, 5, 6, 1, 2]),
    (6, [('dc', 4)], {2}, {3}, (), [1, 2, 3, 2, 3, 4, 1, 2, 3, 4, 5, 6]),        # no repeats the second time
])
def test_performed(n, nav, starts, ends, endings, order):
    assert S.performed(n, nav, starts, ends, endings) == order


def test_ranges():
    assert S.ranges([1, 2, 3, 5, 6, 2, 3, 9]) == '1-3 5-6 2-3 9'
    assert S.ranges([4]) == '4'


def W_(x0, x1, text, y=10):
    return ((x0 + x1) / 2, y, x0, x1, text)


def test_navigation_reads_jumps_and_labels():
    bars, u = [0, 50, 100, 150, 200], 8
    assert S.navigation([W_(100, 120, 'D.S.'), W_(125, 130, 'al'), W_(135, 160, 'Coda')], [30], bars, 1, u) == [('segno', 1), ('ds coda', 3)]
    assert S.navigation([W_(140, 170, 'To'), W_(175, 195, 'Coda')], [], bars, 1, u) == [('to coda', 4)]
    assert S.navigation([W_(10, 30, 'Coda')], [], bars, 5, u) == [('coda', 5)]
    assert S.navigation([W_(10, 30, 'Fine')], [], bars, 1, u) == [('fine', 1)]
    assert S.navigation([W_(60, 80, 'D.C.'), W_(85, 90, 'al'), W_(95, 110, 'Fine')], [], bars, 1, u) == [('dc fine', 2)]


# ------------------------------------------------------------------ the words ----
def test_clean_word():
    assert S.clean_word('nIght') == 'night'
    assert S.clean_word('THE') == 'the'
    assert S.clean_word('I') == 'I'
    assert S.clean_word('café') == 'cafe'
    assert S.clean_word('don’t') == "don't"


def test_syllables_split_hyphens_and_drop_markings():
    u = 8
    ws = [W_(10, 40, 'Oh', 200), W_(50, 80, 'Shen-', 200), W_(90, 120, 'an-', 200), W_(130, 160, 'doah,', 200),
          W_(170, 190, 'Ebm7', 200), W_(200, 240, 'cresc.', 200), W_(250, 270, '12', 200),
          W_(10, 40, 'Far', 215), W_(50, 80, 'a-way', 215)]
    lines = S.syllables(ws, u)
    assert lines == [[(25, 'Oh'), (65, 'Shen-'), (105, 'an-'), (145, 'doah,')],
                     [(25, 'Far'), (57.5, 'a-'), (72.5, 'way')]]
    assert S.syllables([W_(10, 20, '5'), W_(30, 40, 'pp')], u) == []


def test_place_x_assigns_in_order_and_skips_far_notes():
    notes = [{'x': x} for x in (20, 60, 100, 140, 180)]
    got = S.place_x(notes, [(25, 'a'), (65, 'b'), (145, 'c')], 8)
    assert [got.get(id(n)) for n in notes] == ['a', 'b', None, 'c', None]
    assert S.place_x([], [(1, 'a')], 8) == {} and S.place_x(notes, [], 8) == {}


def test_place_closest_in_order():
    slots = [(x, {'x': x}) for x in (20, 60, 100)]
    got = S.place(slots, [(58, 'a'), (102, 'b')])
    assert [got[id(n)] for _, n in slots] == ['_', 'a', 'b']
    got = S.place(slots, [(0, 'x'), (1, 'y'), (2, 'z'), (3, 'w')])     # more syllables than notes: in turn
    assert [got[id(n)] for _, n in slots] == ['x', 'y', 'z']


def test_tempo_and_swing_words():
    assert S.tempo_words([W_(10, 50, 'Moderately'), W_(55, 80, 'slow')]) == [(10, 72.0)]
    assert S.tempo_words([W_(10, 50, 'Andante')]) == [(10, 76.0)]
    assert S.tempo_words([W_(10, 50, 'andante')]) == []                 # a heading begins with a capital
    assert S.swing_words([W_(10, 50, 'Swing!')], 8) == [(10, 'on')]
    assert S.swing_words([W_(10, 50, 'Straight'), W_(55, 80, '8ths')], 8) == [(10, 'off')]
    lyric = [W_(10 + 30 * i, 35 + 30 * i, t) for i, t in enumerate('Swing low, sweet char- i- ot'.split())]
    assert S.swing_words(lyric, 8) == []


# ---------------------------------------------------------- split systems joined ----
def _split_pair(gap):
    st = lambda n: {'clef': 'G', 'measures': [{}] * n}
    a = dict(page=1, system=1, staves=[(100, 140), (181, 221)], kinds=['v', 'v'], read=[st(3), st(3)], x0=50, x1=500, top=80, bot=240)
    t = 221 + gap
    b = dict(page=1, system=2, staves=[(t, t + 40), (t + 82, t + 122), (t + 162, t + 202)], kinds=['v', 'p', 'p'], read=[st(3)] * 3,
             x0=52, x1=505, top=t - 20, bot=t + 222)
    return a, b


def test_join_split_systems():
    a, b = _split_pair(50)
    c = dict(page=1, system=3, staves=[(700, 740)], kinds=['v'], read=[{'clef': 'G', 'measures': [{}] * 2}], x0=50, x1=500, top=680, bot=760)
    logged = []
    out = S.join_split_systems([a, b, c], logged.append)
    assert len(out) == 2 and len(logged) == 1
    assert out[0]['kinds'] == ['v', 'v', 'v', 'p', 'p'] and len(out[0]['read']) == 5 and out[0]['bot'] == b['bot'] and out[0]['x1'] == 505
    assert [o['system'] for o in out] == [1, 2]


def test_join_split_systems_not_when_far_apart():
    a, b = _split_pair(200)
    assert len(S.join_split_systems([a, b], lambda *x: None)) == 2


@pytest.mark.xfail(strict=True, reason="scan2score.join_split_systems: `rest = [g for g in inner if g != gap]` drops every inner "
                   "gap equal in value to the gap between the groups, so evenly spaced staves (the clearest case of one system) "
                   "leave `rest` empty and are never joined")
def test_join_split_systems_evenly_spaced():
    a, b = _split_pair(41)          # 41: the same as the gap between a's two staves
    b['staves'] = [(262, 302), (343, 383), (424, 464)]
    a['staves'] = [(100, 140), (181, 221)]
    assert len(S.join_split_systems([a, b], lambda *x: None)) == 1
