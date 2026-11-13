"""tools/vector2score.py: reading notation-software PDFs from their music-font symbols.

The synthetic PDFs here are drawn with pymupdf: staff lines, barlines and stems as lines, and the symbols as
characters of a font named "Maestro" (the old, pre-SMuFL keyboard layout the module also reads), so no music font
has to be installed."""
from fractions import Fraction as F

import pytest

import vector2score as V

pymupdf = pytest.importorskip('pymupdf')

SP = 8.                       # staff space, points
W = 1.18 * SP                 # a notehead's width as the module reckons it
# characters of the old music-font layout (as text; their Mac Roman codes are what LEGACY maps)
HEAD, HALF, WHOLE, QREST = 'œ', '˙', 'w', 'Œ'
SHARP, FLAT, NATURAL, DOT, FLAG = '#', 'b', 'n', '.', 'j'
TREBLE, BASS = '&', '?'
BARS = (150, 250, 350, 450, 550)


def build_pdf(path, staves, width=600, height=400, joined=False, words=()):
    """staves: [(top, bars, glyphs [(char, x, k)], stems [(x, y0, y1)] relative to top)]; k = half-spaces below the top line.
    joined: the staves are one system - a line down their left side, as a choir's staves have.
    words: [(x, y, text)] in an ordinary font, each centred on x - the lyrics, as the PDF's own text."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.insert_font(fontname='F1', fontbuffer=pymupdf.Font('helv').buffer)
    if joined:
        page.draw_line((50, staves[0][0]), (50, staves[-1][0] + 4 * SP), width=1.4)
    for top, bars, glyphs, stems in staves:
        for i in range(5):
            page.draw_line((50, top + i * SP), (550, top + i * SP), width=.5)
        for x in bars:
            page.draw_line((x, top), (x, top + 4 * SP), width=1.4)
        for ch, x, k in glyphs:
            page.insert_text((x, top + k * SP / 2), ch, fontname='F1', fontsize=20)
        for x, y0, y1 in stems:
            page.draw_line((x, top + y0), (x, top + y1), width=.7)
    for xref in range(1, doc.xref_length()):         # call the font what an old music font is called
        if doc.xref_get_key(xref, 'BaseFont')[0] == 'name':
            doc.xref_set_key(xref, 'BaseFont', '/Maestro')
    for x, y, text in words:                         # (after that, so that this font keeps its own name)
        page.insert_text((x - pymupdf.get_text_length(text, 'tiro', 9) / 2, y), text, fontname='tiro', fontsize=9)
    doc.save(str(path))
    return str(path)


def quarters(k, per_measure=4):
    return [(HEAD, 50 + 100 * m + 20 + 20 * j, k) for m in range(5) for j in range(per_measure)]


@pytest.fixture
def piece_pdf(tmp_path):
    """Two one-staff systems.  Upper (treble, key of one flat):
       m1  bb4 (key)  #g4  g4 (sharp lasts to the bar)  bb4
       m2  g4 (natural again)  nat-b4  b4 (natural lasts)  quarter rest   + a forte
       m3  dotted half g4, quarter g4
       m4  two flagged eighths, quarter, half
       m5  whole note
    Lower (bass clef): twenty quarter-note G2s."""
    upper = [(TREBLE, 52, 6), (FLAT, 60, 4),
             (HEAD, 70, 4), (SHARP, 81, 6), (HEAD, 90, 6), (HEAD, 110, 6), (HEAD, 130, 4),
             (HEAD, 170, 6), (NATURAL, 181, 4), (HEAD, 190, 4), (HEAD, 210, 4), (QREST, 230, 4), ('f', 175, 14),
             (HALF, 270, 6), (DOT, 283, 5), (HEAD, 330, 6),
             (HEAD, 365, 6), (FLAG, 365 + W, -1), (HEAD, 382, 6), (FLAG, 382 + W, -1), (HEAD, 400, 6), (HALF, 420, 6),
             (WHOLE, 470, 6)]
    stems = [(365 + W, -4, 24), (382 + W, -4, 24)]        # stems up from the two eighths to their flags
    lower = [(BASS, 52, 6)] + quarters(8)
    return build_pdf(tmp_path / 'piece.pdf', [(100, BARS, upper, stems), (250, BARS, lower, [])])


def notes_of(m):
    return [(n['name'], n['on'], n['ql']) for n in m['notes']]


# ------------------------------------------------------------------ the symbol tables ----
def test_glyph_tables_follow_smufl():
    assert V.HEADS[0xE0A4] == 1 and V.HEADS[0xE0A3] == 2 and V.HEADS[0xE0A2] == 4 and V.HEADS[0xE0A0] == 8
    assert V.RESTS[0xE4E5] == 1 and V.RESTS[0xE4E3] == 4 and V.RESTS[0xE4E6] == F(1, 2)
    assert V.FLAGS[0xE240] == V.FLAGS[0xE241] == 1 and V.FLAGS[0xE244] == 3       # an eighth's flag up and down; a 32nd's
    assert V.ACCS == {0xE260: -1, 0xE261: 0, 0xE262: 1, 0xE263: 2, 0xE264: -2}
    assert V.CLEFS[0xE050] == 'G' and V.CLEFS[0xE062] == 'F'
    assert set(V.LOW_CLEFS) <= set(V.CLEFS)
    assert all(c in V.HEADS for c in V.SPOKEN)
    assert V.DIGITS[0xE084] == 4 and V.TUPLET[0xE883] == 3


def test_every_legacy_character_maps_to_a_known_symbol():
    known = set(V.HEADS) | set(V.RESTS) | set(V.FLAGS) | set(V.ACCS) | set(V.CLEFS) | set(V.DIGITS) | set(V.DYNAMICS) | \
        {V.DOT, V.COMMON, V.CUT, *V.FERMATA}
    assert set(V.LEGACY.values()) <= known


@pytest.mark.parametrize('ch, code', [('&', 0xE050), ('?', 0xE062), ('w', 0xE0A2), (HEAD, 0xE0A4), (HALF, 0xE0A3),
                                      (QREST, 0xE4E5), ('#', 0xE262), ('b', 0xE260), ('n', 0xE261), ('.', 0xE1E7),
                                      ('j', 0xE240), ('f', 0xE522), ('c', V.COMMON), ('4', 0xE084)])
def test_legacy_characters_as_smufl(ch, code):
    assert V.LEGACY[V._legacy_code(ch, 0)] == code


def test_legacy_code_symbol_encoding_and_shift():
    # a "symbol" font comes out as Greek letters: the Symbol encoding's character for the code
    assert V._legacy_code('ω', 0) == 0x77              # omega is where 'w' (a whole note) is
    assert V.LEGACY[V._legacy_code('ω', 0)] == 0xE0A2
    assert V._legacy_code('%', 1) == 0x26                   # one PDF maker writes low codes one too low
    assert V._legacy_code('一', 0) is None              # not a character the font can hold


class _FakePage:
    def __init__(self, font, text):
        self.font, self.text = font, text

    def get_text(self, kind):
        return {'blocks': [{'lines': [{'spans': [{'font': self.font, 'chars': [{'c': c} for c in self.text]}]}]}]}


def test_legacy_shift_detects_old_fonts_and_their_displacement():
    assert V.legacy_shift([_FakePage('Helvetica', '&' * 40)]) is None       # not a music font
    assert V.legacy_shift([_FakePage('Maestro', '&' * 10)]) is None         # too few symbols to tell
    assert V.legacy_shift([_FakePage('Maestro', '&w#' * 10)]) == 0
    assert V.legacy_shift([_FakePage('ABCDEF+Petrucci', '%v"' * 10)]) == 1  # each one code too low: & w #


# ---------------------------------------------------------------------- pitch ----
@pytest.mark.parametrize('k, clef, alter, midi, name', [
    (0, 'G', 0, 77, 'fn5'),        # top line of the treble staff
    (8, 'G', 0, 64, 'en4'),        # bottom line
    (10, 'G', 0, 60, 'cn4'),       # middle C on a ledger line below
    (4, 'G', -1, 70, 'bb4'),
    (6, 'G', 1, 68, 'g#4'),
    (6, 'G', 2, 69, 'g##4'),
    (0, 'F', 0, 57, 'an3'),        # top line of the bass staff
    (8, 'F', 0, 43, 'gn2'),        # bottom line
    (-2, 'F', 0, 60, 'cn4'),       # middle C on a ledger line above
])
def test_pitch_from_staff_position(k, clef, alter, midi, name):
    assert V._pitch(k, clef, alter) == (midi, name)


# -------------------------------------------------------------- staves and beams ----
def test_staves_found_from_five_even_lines():
    long_ = [(100 + 8 * i, 50, 550) for i in range(5)] + [(200 + 7 * i, 40, 560) for i in range(5)]
    st = V._staves(long_)
    assert len(st) == 2
    assert st[0] == dict(top=100, bot=132, sp=8.0, x0=50, x1=550)
    assert st[1]['top'] == 200 and st[1]['sp'] == pytest.approx(7.0) and st[1]['x0'] == 40


def test_staves_reject_uneven_or_too_few_lines():
    assert V._staves([(100 + 8 * i, 50, 550) for i in range(4)]) == []
    assert V._staves([(y, 50, 550) for y in (100, 108, 116, 140, 148)]) == []
    # a line drawn twice (a hair apart) is one line
    doubled = [(100 + 8 * i, 50, 550) for i in range(5)] + [(100.3, 50, 550)]
    assert len(V._staves(doubled)) == 1


def test_beam_height_along_a_sloped_beam():
    flat = [(0, 10), (10, 10), (10, 12), (0, 12)]
    assert V._beam_y(flat, 5) == pytest.approx((10, 12))
    assert V._beam_y(flat, 20) is None
    slope = [(0, 10), (10, 20), (10, 22), (0, 12)]
    assert V._beam_y(slope, 5) == pytest.approx((15, 17))


def test_systems_joined_by_a_line_at_the_left():
    staves = [dict(top=100 + 60 * i, bot=132 + 60 * i, sp=8., x0=50, x1=550) for i in range(4)]
    joined = V._systems([dict(s) for s in staves], [(50, 100, 312, 1.)], [])
    assert [len(s) for s in joined] == [4]
    assert [st['kind'] for st in joined[0]] == ['v', 'v', 'p', 'p']   # no brace found: the piano is the lowest two
    apart = V._systems([dict(s) for s in staves], [], [])
    assert [len(s) for s in apart] == [1, 1, 1, 1]
    assert all(s[0]['kind'] == 'v' for s in apart)


# -------------------------------------------------------- voices and onsets in a measure ----
def _ev(x, up, dur, y=100., rest=False):
    return dict(x=x, up=up, dur=None if dur is None else F(dur), y=y, mid=100., rest=rest)


def test_timed_one_voice_in_turn():
    evs = [_ev(10, True, 1), _ev(30, False, 1), _ev(50, True, 2)]     # stems flip, but nothing sounds together
    out = V._timed(evs, F(4), W, SP)
    assert [(v, t) for v, t, e in out] == [(1, 0), (1, 1), (1, 2)]


def test_timed_two_voices_by_stem_direction():
    evs = [_ev(10, True, 2, 90), _ev(10, False, 1, 110), _ev(40, False, 1, 110), _ev(70, True, 2, 90), _ev(70, False, 2, 110)]
    out = V._timed(evs, F(4), W, SP)
    assert sorted((v, t, e['up']) for v, t, e in out) == [(1, 0, True), (1, 2, True), (2, 0, False), (2, 1, False), (2, 2, False)]


def test_timed_whole_measure_rest_belongs_to_the_measure():
    out = V._timed([_ev(10, None, None, rest=True)], F(3), W, SP)
    assert [(v, t) for v, t, e in out] == [(1, 0)]


# ------------------------------------------------------------------ a whole page ----
def test_read_synthetic_score(piece_pdf):
    logged = []
    crops = V.read(piece_pdf, log=logged.append)
    assert crops is not None
    assert len(crops) == 2 and all(c['kinds'] == ['v'] for c in crops)
    assert 'read exactly' in logged[-1] and '10 of 10 staff-measures add up' in logged[-1]
    c = crops[0]
    assert c['page'] == 1 and c['system'] == 1
    assert len(c['bars']) == 6                                   # five measures
    assert c['bars'][0] == pytest.approx(50 * 2.6) and c['bars'][-1] == pytest.approx(550 * 2.6)   # page-image pixels
    staff = c['read'][0]
    assert staff['clef'] == 'G' and staff['octave'] == 0
    m = staff['measures']
    assert len(m) == 5
    # key signature, accidental lasting to the barline
    assert notes_of(m[0]) == [('bb4', 0, 1), ('g#4', 1, 1), ('g#4', 2, 1), ('bb4', 3, 1)]
    assert [n['midi'] for n in m[0]['notes']] == [70, 68, 68, 70]
    # the barline cancels the sharp; a natural cancels the key's flat until the next barline; a rest
    assert notes_of(m[1]) == [('gn4', 0, 1), ('bn4', 1, 1), ('bn4', 2, 1), (None, 3, 1)]
    assert m[1].get('dyn') == 'f' and 'dyn' not in m[0]
    # a dot adds half
    assert notes_of(m[2]) == [('gn4', 0, 3), ('gn4', 3, 1)]
    # flags halve a black note
    assert notes_of(m[3]) == [('gn4', 0, F(1, 2)), ('gn4', F(1, 2), F(1, 2)), ('gn4', 1, 1), ('gn4', 2, 2)]
    assert notes_of(m[4]) == [('gn4', 0, 4)]
    for mm in m:                                                 # the self-check: each measure is filled
        assert mm['len'] == mm['end'] == mm['nominal'] == 4
    assert all(n['exact'] and n['voice'] == '1' for mm in m for n in mm['notes'])
    # the bass-clef system, with no key signature of its own
    low = crops[1]['read'][0]
    assert low['clef'] == 'F'
    assert all(notes_of(mm) == [('gn2', i, 1) for i in range(4)] for mm in low['measures'])


def test_read_steps_aside_when_measures_do_not_add_up(tmp_path):
    """Five quarter notes in every 4/4 measure: the symbols are not music as read, and the PDF is left to the scan reader."""
    pdf = build_pdf(tmp_path / 'overfull.pdf', [(100, BARS, [(TREBLE, 52, 6)] + [(HEAD, 50 + 100 * m + 12 + 17 * j, 6) for m in range(5) for j in range(5)], [])])
    logged = []
    assert V.read(pdf, log=logged.append) is None
    assert any('do not add up' in s and '0 of 5' in s for s in logged)


def test_read_steps_aside_with_too_few_noteheads(tmp_path):
    pdf = build_pdf(tmp_path / 'few.pdf', [(100, BARS, [(TREBLE, 52, 6), (WHOLE, 70, 6), (WHOLE, 170, 6)], [])])
    assert V.read(pdf, log=lambda *a: None) is None


def test_read_steps_aside_for_text_only_pdf(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), 'Shenandoah - words only, no music here at all.', fontname='helv', fontsize=12)
    path = str(tmp_path / 'text.pdf')
    doc.save(path)
    logged = []
    assert V.read(path, log=logged.append) is None
    assert logged == []                                          # nothing claimed about notes
