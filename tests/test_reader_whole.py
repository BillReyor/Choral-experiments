"""The reader from one end to the other: a PDF drawn here (two staves joined into a system, the words as the PDF's
own text) -> tools/scan2score.py's main() -> a score -> choral.score.  No scan reader and no text recognition: this is
the path a PDF exported from notation software takes, and the one a fix to the reader is most likely to break."""
import pytest

import scan2score as S
import test_vector2score as T
from choral import render, score

pytest.importorskip('pymupdf')


def places(first, last):
    """Where the quarter notes stand: `first` in the first measure, four in each of three, `last` in the fifth."""
    head = [120] if first == 1 else [70 + 20 * j for j in range(first)]
    return head + [50 + 100 * m + 20 + 20 * j for m in range(1, 4) for j in range(4)] + [470 + 20 * j for j in range(last)]


@pytest.fixture
def read(tmp_path, monkeypatch, capsys):
    """read(first, last, words) -> (the score as text, what the reader said)."""
    def go(first=4, last=4, words=''):
        xs = places(first, last)
        pdf = T.build_pdf(tmp_path / 'my song.pdf',
                          [(100, T.BARS, [(T.TREBLE, 52, 6)] + [(T.HEAD, x, 6) for x in xs], []),
                           (180, T.BARS, [(T.BASS, 52, 6)] + [(T.HEAD, x, 8) for x in xs], [])],
                          joined=True, words=[(x + T.W / 2, 152, w) for x, w in zip(xs, words.split())])
        monkeypatch.setitem(S.TEXT, 'pages', {})
        monkeypatch.setattr(S, 'tesseract', lambda: None)             # the same on a computer that has it and one that has not
        monkeypatch.setattr('sys.argv', ['scan2score', pdf, str(tmp_path / 'out.score'), '--work', str(tmp_path / 'work'), '--exact-only', '--tempo', '100'])
        S.main()
        return (tmp_path / 'out.score').read_text(), capsys.readouterr().out
    return go


def numbers(text):
    return [int(line.split()[1]) for line in text.splitlines() if line.startswith('== ')]


def sung(text, part):
    sc = score.parse(text, warn=lambda *a: None)
    return sc, [(float(n['beat']), n['midi'], n['lyric']) for n in sc.parts[part]]


def test_a_drawn_pdf_becomes_a_score(read):
    text, said = read()
    assert 'read exactly' in said and '10 of 10 staff-measures add up' in said
    assert 'title: My Song' in text and 'tempo: 100' in text
    assert numbers(text) == [1, 2, 3, 4, 5]
    sc, tenors = sung(text, 'T1')
    assert [m for _, m, _ in tenors] == [55] * 20                     # the G above middle C, sung where tenors sing it
    assert [m for _, m, _ in sung(text, 'BS')[1]] == [43] * 20
    assert sc.measures[5] == (16.0, 4.0)


def test_an_upbeat_is_measure_0_so_that_the_numbers_are_the_pages(read):
    # one beat before the first barline, three in the last measure: the first whole measure is number 1 in print,
    # and the page shows a listener the number of the measure being heard
    text, said = read(first=1, last=3)
    assert 'upbeat' in said
    assert numbers(text) == [0, 1, 2, 3, 4]
    sc, tenors = sung(text, 'T1')
    assert sc.measures[0] == (0.0, 1.0) and sc.measures[1] == (1.0, 4.0)
    assert [n for _, n in render.measure_starts(sc, render.clock_for(sc))] == [0, 1, 2, 3, 4]


def test_a_short_first_measure_alone_is_enough(read):
    text, _ = read(first=1, last=4)                                   # (the last measure is whole: it is written out both ways)
    assert numbers(text) == [0, 1, 2, 3, 4]


def test_a_first_measure_a_beat_short_is_not_an_upbeat(read):
    text, said = read(first=3, last=4)                                # three of four, and nothing at the end to complete it
    assert 'upbeat' not in said
    assert numbers(text) == [1, 2, 3, 4, 5]


def test_the_words_of_the_pdf_are_set_under_the_notes(read):
    # a lost "fi" (stored as a digit), a word in two syllables, two letters said by name
    text, said = read(first=1, last=3, words='the wind is on the T V to- night and all the 9elds are still now')
    assert "taken from the PDF's own text" in said
    sc, tenors = sung(text, 'T1')
    assert [w for _, _, w in tenors] == ['the', 'wind', 'is', 'on', 'the', 't', 'v', 'to-', 'night', 'and', 'all', 'the', 'fields', 'are', 'still', 'now']
    assert [w for _, _, w in sung(text, 'BS')[1]] == [w for _, _, w in tenors]         # words between two staves are both staves'
