"""choral/app.py: the local web page's server - where pieces are kept, what it accepts, and who it answers.

These are the program's security boundaries: it must answer only this computer, do work only for its own page
(the token), and never read or write outside its library."""
import http.client
import json
import os
import threading
from http.server import ThreadingHTTPServer

import pytest

from choral import app


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """An empty library of pieces, and no work queue being worked."""
    d = tmp_path / 'library'
    d.mkdir()
    monkeypatch.setattr(app, 'LIB', str(d))
    monkeypatch.setattr(app, 'waiting', [])
    monkeypatch.setattr(app, 'now', {})
    import queue
    monkeypatch.setattr(app, 'jobs', queue.Queue())
    return d


@pytest.fixture
def server(lib):
    srv = ThreadingHTTPServer(('127.0.0.1', 0), app.Page)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def request(port, method, path, body=b'', headers=None, host=None):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    h = {'Host': host or f'127.0.0.1:{port}'}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


def post(port, path, payload=None, token=None, **kw):
    hdr = {'X-Palare': app.TOKEN if token is None else token, 'Content-Type': 'application/json'}
    hdr.update(kw.pop('headers', {}))
    return request(port, 'POST', path, json.dumps(payload or {}).encode(), hdr, **kw)


def demo_bytes():
    return open(os.path.join(app.ROOT, 'scores', 'demo_shenandoah.score'), 'rb').read()


# ---- piece ids never leave the library

@pytest.mark.parametrize('pid', ['', '.', '..', '.hidden', '../etc', 'a/b', '/etc/passwd', None])
def test_folder_refuses_anything_but_a_plain_name(lib, pid):
    with pytest.raises(ValueError):
        app.folder(pid)


@pytest.mark.skipif(os.name != 'nt', reason='backslash is a separator only on Windows')
def test_folder_refuses_backslash_on_windows(lib):
    with pytest.raises(ValueError):
        app.folder('..\\x')


def test_folder_accepts_a_piece_name(lib):
    assert app.folder('Shenandoah (2)') == os.path.join(str(lib), 'Shenandoah (2)')


# ---- adding a piece

def test_add_keeps_a_pdf_inside_the_library(lib):
    pid = app.add('My Song.pdf', b'%PDF-1.7 rest')
    assert pid == 'My Song'
    d = app.load(pid)
    assert d['file'] == 'My Song.pdf' and d['status'] == 'reading'
    assert open(app.music(pid), 'rb').read() == b'%PDF-1.7 rest'
    assert app.score_of(pid).endswith(os.path.join('My Song', 'source', 'My Song.score'))
    assert app.jobs.get_nowait() == ('read', pid, {})


@pytest.mark.parametrize('name', ['../../evil.pdf', '..%2F..%2Fevil.pdf', '/tmp/evil.pdf', 'C:\\x\\..\\evil.pdf', '..\\evil.pdf'])
def test_add_strips_any_path_from_the_file_name(lib, name):
    pid = app.add(name, b'%PDF-1.4')
    assert os.path.dirname(app.folder(pid)) == str(lib)
    assert os.listdir(lib) == [pid]
    assert '/' not in pid and '\\' not in pid and not pid.startswith('.')


@pytest.mark.parametrize('name', ['.. .pdf', ' ..pdf', ' .pdf'])
def test_add_names_a_nameless_file_piece(lib, name):
    assert app.add(name, b'%PDF-1.4') == 'Piece'


def test_add_strips_odd_characters(lib):
    assert app.add('My <Song>|"*?.pdf', b'%PDF-1.4') == 'My Song'


def test_add_numbers_a_second_piece_of_the_same_name(lib):
    assert app.add('Song.pdf', b'%PDF') == 'Song'
    assert app.add('Song.pdf', b'%PDF') == 'Song (2)'
    assert app.add('Song.pdf', b'%PDF') == 'Song (3)'


@pytest.mark.parametrize('name, data, message', [
    ('song.docx', b'xx', 'PDF'),
    ('song', b'%PDF', 'PDF'),
    ('song.pdf', b'<html>', 'not a PDF'),
])
def test_add_refuses_what_is_not_sheet_music(lib, name, data, message):
    with pytest.raises(ValueError, match=message):
        app.add(name, data)
    assert os.listdir(lib) == []


def test_add_accepts_a_score_file(lib):
    pid = app.add('demo.score', demo_bytes())
    assert app.load(pid)['file'] == 'demo.score'


def test_save_merges_and_writes_atomically(lib):
    pid = app.add('a.pdf', b'%PDF')
    app.save(pid, status='read', extra=1)
    d = app.load(pid)
    assert d['status'] == 'read' and d['extra'] == 1 and d['title'] == 'a'
    assert not os.path.exists(app.info_file(pid) + '.part')


def test_pieces_lists_newest_first_and_skips_strangers(lib):
    a = app.add('a.pdf', b'%PDF'); app.save(a, added=1)
    b = app.add('b.pdf', b'%PDF'); app.save(b, added=2)
    (lib / 'not a piece').mkdir()
    (lib / '.settings.json').write_text('{}')
    assert [d['id'] for d in app.pieces()] == [b, a]


def test_pieces_lists_only_tracks_that_exist(lib):
    pid = app.add('a.pdf', b'%PDF')
    (lib / pid / 'a - Baritone.mp3').write_bytes(b'x')
    app.save(pid, tracks=['a - Baritone.mp3', 'gone.mp3'])
    assert app.pieces()[0]['tracks'] == ['a - Baritone.mp3']


# ---- what the page asks for (act)

def test_unknown_request_is_refused(lib):
    with pytest.raises(KeyError):
        app.act('/api/nonsense', {}, b'')


def test_tempo_is_changed_within_range_only(lib):
    pid = app.add('demo.score', demo_bytes())
    for bad in (0, 29, 241, 1000):
        with pytest.raises(ValueError, match='between 30 and 240'):
            app.act('/api/tempo', {'id': pid, 'bpm': bad}, b'')
    app.act('/api/tempo', {'id': pid, 'bpm': 72}, b'')
    text = open(app.score_of(pid)).read()
    assert 'tempo: 72\n' in text and 'tempo: 66' not in text


def test_render_needs_a_part_that_was_read(lib):
    pid = app.add('a.pdf', b'%PDF')
    app.save(pid, status='read', read={'parts': [['BR', 'Baritone'], ['BS', 'Bass']]})
    app.waiting.clear(); app.jobs.get_nowait()
    with pytest.raises(ValueError, match='Choose your part'):
        app.act('/api/render', {'id': pid, 'part': 'T1'}, b'')
    app.act('/api/render', {'id': pid, 'part': 'BR'}, b'')
    assert app.load(pid)['status'] == 'queued'
    assert app.jobs.get_nowait()[:2] == ('render', pid)
    with pytest.raises(ValueError, match='busy'):
        app.act('/api/render', {'id': pid, 'part': 'BR'}, b'')


def test_act_with_a_traversing_id_is_refused(lib):
    for path in ('/api/tempo', '/api/reveal', '/api/score', '/api/fix/open', '/api/render'):
        with pytest.raises((ValueError, KeyError)):
            app.act(path, {'id': '../..', 'bpm': 60}, b'')


# ---- the update line

def test_version_needs_a_full_commit_id(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    root.mkdir()
    monkeypatch.setattr(app, 'ROOT', str(root))
    vf = tmp_path / 'version.json'
    vf.write_text(json.dumps({'version': 'abc'}))
    assert app.version() is None
    vf.write_text(json.dumps({'version': 'a' * 40, 'channel': 'main'}))
    assert app.version()['version'] == 'a' * 40
    assert app.channel() == 'main'
    vf.write_text('not json')
    assert app.version() is None


def test_update_line_fetches_from_this_project_on_github(monkeypatch):
    monkeypatch.setattr(app, 'version', lambda: None)
    line = app.line()
    assert 'https://raw.githubusercontent.com/BillReyor/Palare-Piano/stable/install' in line


def test_what_is_new_leaves_out_the_housekeeping_and_sends_nothing_of_this_computer(monkeypatch):
    import io
    import urllib.request
    titles = ['A first fix', 'Journal: what was learned', 'Tests for the reader', 'Merge pull request #3 from someone/a-branch', 'A second fix']
    body = json.dumps({'commits': [{'commit': {'message': t + '\n\nand why'}} for t in titles]}).encode()
    asked = {}

    def github(req, timeout=None):
        asked.update(url=req.full_url, headers={k.lower() for k, _ in req.header_items()}, body=req.data)
        return io.BytesIO(body)
    monkeypatch.setattr(urllib.request, 'urlopen', github)
    monkeypatch.setattr(app, 'version', lambda: {'version': 'a' * 40})
    monkeypatch.setattr(app, 'newer', {})
    app.look_for_newer()
    assert app.newer['count'] == 5
    assert app.newer['news'] == ['A second fix', 'A first fix']          # newest first; what a singer would notice, no more
    assert asked == dict(url='https://api.github.com/repos/BillReyor/Palare-Piano/compare/' + 'a' * 40 + '...stable',
                         headers={'user-agent', 'accept'}, body=None)


def test_no_answer_from_github_is_not_an_error_on_the_page(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(OSError('no network')))
    monkeypatch.setattr(app, 'version', lambda: {'version': 'a' * 40})
    monkeypatch.setattr(app, 'newer', {})
    app.look_for_newer()
    assert app.newer['error'] == 'OSError' and 'news' not in app.newer


# ---- the report keeps private things out

def test_report_has_no_music_and_no_home_folder(lib, monkeypatch):
    monkeypatch.setattr(app, 'version', lambda: None)
    monkeypatch.setattr(app, 'computer', lambda: None)
    monkeypatch.setattr(app, 'voices_state', lambda: {'ready': False})
    pid = app.add('demo.score', demo_bytes())
    app.save(pid, error=[f'failed reading {os.path.expanduser("~")}/Music/x.pdf'])
    text = app.report()
    assert 'Shen-' not in text and 'f4/e' not in text            # nothing of the score itself
    home = os.path.expanduser('~')
    assert home not in text


# ---- the server answers only this computer, and works only for its own page

def test_page_is_served_with_its_token(server):
    status, hdr, body = request(server, 'GET', '/')
    assert status == 200 and hdr['Content-Type'].startswith('text/html')
    assert app.TOKEN.encode() in body and b'{{TOKEN}}' not in body


@pytest.mark.parametrize('host', ['evil.example', 'evil.example:80', '127.0.0.1.evil.example', '0.0.0.0', ''])
def test_requests_named_for_another_host_are_refused(server, host):
    # a web page that rebinds its own name to 127.0.0.1 still sends its own name as Host
    for method, path in (('GET', '/'), ('GET', '/api/state'), ('GET', '/file/x/y'), ('POST', '/api/quit')):
        status, _, _ = request(server, method, path, headers={'X-Palare': app.TOKEN}, host=host or ' ')
        assert status == 403, (method, path, host)


@pytest.mark.parametrize('host', ['localhost', 'localhost:1234', '127.0.0.1'])
def test_local_host_names_are_accepted(server, host):
    assert request(server, 'GET', '/api/ping', host=host)[0] == 200


@pytest.mark.parametrize('token', ['', 'wrong', 'x' * 24])
def test_work_needs_the_page_token(server, lib, token):
    status, _, _ = post(server, '/api/demo', token=token)
    assert status == 403
    assert os.listdir(lib) == []


def test_with_the_token_the_page_can_add_a_piece(server, lib):
    status, _, body = post(server, '/api/demo')
    assert status == 200
    assert json.loads(body)['id'] in os.listdir(lib)


def test_upload_over_the_wire_is_kept_inside_the_library(server, lib):
    status, _, body = request(server, 'POST', '/api/add', b'%PDF-1.4',
                              {'X-Palare': app.TOKEN, 'X-Filename': '..%2F..%2Fescape.pdf'})
    assert status == 200
    assert os.listdir(lib) == ['escape']
    assert not (lib.parent / 'escape.pdf').exists()


def test_oversized_upload_is_refused(server):
    c = http.client.HTTPConnection('127.0.0.1', server, timeout=10)
    c.putrequest('POST', '/api/add', skip_host=True)
    c.putheader('Host', f'127.0.0.1:{server}')
    c.putheader('X-Palare', app.TOKEN)
    c.putheader('Content-Length', str((300 << 20) + 1))
    c.endheaders()
    r = c.getresponse()
    assert r.status == 413
    c.close()


def test_bad_requests_get_a_plain_error(server):
    status, _, body = post(server, '/api/nonsense')
    assert status == 400 and 'error' in json.loads(body)
    status, _, body = post(server, '/api/tempo', {'id': '..', 'bpm': 60})
    assert status == 400


# ---- files: only a piece's own tracks

@pytest.fixture
def piece_with_track(lib):
    pid = app.add('Song.pdf', b'%PDF-secret-sheet-music')
    (lib / pid / 'Song - Bass.mp3').write_bytes(bytes(range(256)) * 4)
    app.save(pid, tracks=['Song - Bass.mp3'])
    (lib.parent / 'secret.txt').write_text('private')
    return pid


def test_a_track_is_served(server, piece_with_track):
    status, hdr, body = request(server, 'GET', f'/file/{piece_with_track}/Song%20-%20Bass.mp3')
    assert status == 200 and hdr['Content-Type'] == 'audio/mpeg' and len(body) == 1024


def test_a_track_is_served_in_ranges(server, piece_with_track):
    url = f'/file/{piece_with_track}/Song%20-%20Bass.mp3'
    status, hdr, body = request(server, 'GET', url, headers={'Range': 'bytes=10-19'})
    assert status == 206 and body == bytes(range(10, 20)) and hdr['Content-Range'] == 'bytes 10-19/1024'
    status, _, body = request(server, 'GET', url, headers={'Range': 'bytes=-4'})
    assert status == 206 and body == bytes(range(252, 256))
    status, hdr, _ = request(server, 'GET', url, headers={'Range': 'bytes=5000-'})
    assert status == 416 and hdr['Content-Range'] == 'bytes */1024'


def test_save_asks_the_browser_to_download(server, piece_with_track):
    _, hdr, _ = request(server, 'GET', f'/file/{piece_with_track}/Song%20-%20Bass.mp3?save')
    assert hdr['Content-Disposition'].startswith('attachment;')


@pytest.mark.parametrize('path', [
    '/file/{pid}/source/Song.pdf',                 # the sheet music itself is not a track
    '/file/{pid}/source%2Fpiece.json',
    '/file/{pid}/../../secret.txt',
    '/file/{pid}/..%2F..%2Fsecret.txt',
    '/file/..%2F/secret.txt',
    '/file/../secret.txt',
    '/file/{pid}/%2Fetc%2Fpasswd',
    '/file/{pid}',
    '/file/',
])
def test_nothing_but_listed_tracks_is_served(server, piece_with_track, path):
    status, _, body = request(server, 'GET', path.format(pid=piece_with_track))
    assert status == 404
    assert b'private' not in body and b'secret-sheet-music' not in body


# ---- what the page says about a piece: where a muted part is still heard
TWO_LINES = b'''title: Two Lines
tempo: 100
time: 4/4
key: 0
transpose: TEN -12

== 1
TEN: a4+c5/q=la a4+c5/q=la a4+c5/q=la a4+c5/q=la
LOW: c3+f3/q c3+f3/q c3+f3/q c3+f3/q
== 2
TEN: a4+c5/h=la a4+c5/h=la
LOW: c3/h d3/h
== 3
TEN: a4+c5/h=la a4/h=la
LOW: c3+f3/h c3+f3/h
'''


def test_measures_where_another_part_sings_the_same_notes_are_named(lib):
    # with the baritones left out of a track, their line is still heard where the basses sing it too: the page says where
    pid = app.add('two lines.score', TWO_LINES)
    got = app.what_was_read(pid)
    assert [p[0] for p in got['parts']] == ['tenor1', 'tenor2', 'baritone', 'bass']
    assert got['doubled'] == {'baritone': [2], 'bass': [2]}          # (a measure only half in unison, the third, is not one)
    assert got['measures'] == 3 and got['tempo'] == 100


def test_two_parts_on_one_line_throughout_are_one_part_not_a_doubling(lib):
    pid = app.add('one line.score', TWO_LINES.replace(b'c3+f3', b'c3').replace(b'a4+c5', b'a4'))
    got = app.what_was_read(pid)
    assert [p[0] for p in got['parts']] == ['tenor1', 'bass'] and all(len(p) == 3 for p in got['parts'])     # each with a word of explanation
    assert got['doubled'] == {}


# ---- the measure being heard, for tracks made before the page showed it
def with_tracks(lib, pid, stale=False):
    import time
    (lib / pid / 'x - Bass.mp3').write_bytes(b'x')
    app.save(pid, read=True, tracks=['x - Bass.mp3'], made=dict(part='bass', when=time.time() + (-1e6 if stale else 1e6)))


def test_measures_of_tracks_made_earlier_are_worked_out_from_the_score(lib):
    pid = app.add('two lines.score', TWO_LINES)
    with_tracks(lib, pid)
    app.find_measures()
    assert app.load(pid)['timeline'] == [[1.0, 1], [3.4, 2], [5.8, 3]]          # a second of silence, then 2.4 s a measure


def test_measures_are_not_guessed_for_a_score_changed_since_its_tracks(lib, monkeypatch):
    pid = app.add('two lines.score', TWO_LINES)
    with_tracks(lib, pid, stale=True)
    monkeypatch.setattr(app.subprocess, 'run', lambda *a, **k: pytest.fail('the tracks no longer follow this score'))
    app.find_measures()
    assert 'timeline' not in app.load(pid)


def test_a_piece_that_cannot_be_timed_is_left_alone(lib):
    pid = app.add('broken.score', b'title: x\n== 1\nTEN: this is not music\n')
    with_tracks(lib, pid)
    app.find_measures()                                                          # (says nothing, harms nothing)
    assert 'timeline' not in app.load(pid)


# ---- small files to send
def a_wav(path, seconds=.5):
    import wave
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(bytes(4 * int(44100 * seconds)))
    return str(path)


def test_squeeze_leaves_tracks_as_written_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv('PALARE_PLAIN_TRACKS', '1')
    assert app.squeeze(a_wav(tmp_path / 'a.wav')) is None
    assert os.listdir(tmp_path) == ['a.wav']


def test_squeeze_makes_an_mp3_where_the_computer_has_no_converter(tmp_path, monkeypatch):
    pytest.importorskip('lameenc')
    monkeypatch.delenv('PALARE_PLAIN_TRACKS', raising=False)
    monkeypatch.setattr(app.shutil, 'which', lambda name: None)                  # Windows, and most Linux
    assert app.squeeze(a_wav(tmp_path / 'a b.wav')) == 'a b.mp3'
    data = (tmp_path / 'a b.mp3').read_bytes()
    assert len(data) > 1000 and (data[:3] == b'ID3' or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0))
    assert len(data) < os.path.getsize(tmp_path / 'a b.wav')


def test_squeeze_with_nothing_to_make_a_small_file_says_so(tmp_path, monkeypatch):
    import sys
    monkeypatch.delenv('PALARE_PLAIN_TRACKS', raising=False)
    monkeypatch.setattr(app.shutil, 'which', lambda name: None)
    monkeypatch.setitem(sys.modules, 'lameenc', None)                            # not installed
    assert app.squeeze(a_wav(tmp_path / 'a.wav')) is None
    assert os.listdir(tmp_path) == ['a.wav']


# ---- the page's own sound ("Fix a note or a word")
def page_function(name):
    """The text of one of the page's functions.  (There is nothing here to run the page's script with: what can be
    held to is the order in which it does things.)"""
    html = open(os.path.join(os.path.dirname(app.__file__), 'app.html'), encoding='utf-8').read()
    start = html.index('function ' + name + '(')
    return html[start:html.index('\n}', start)]


def test_the_page_wakes_its_sound_in_the_click_before_it_waits_for_anything():
    # A browser lets a page make sound only just after a click.  A moved note used to sound when the change had been
    # written - seconds later on a computer busy making tracks - and by then the browser no longer allowed it.
    move = page_function('moveNote')
    assert 'sound()' in move and move.index('sound()') < move.index('await')
    assert '.would' in move and move.index('play(') < move.index("fixPost(pid, '/api/fix/move'")      # ... and sounds before it is sent
