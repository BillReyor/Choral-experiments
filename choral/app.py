"""Palare Piano in a browser window, for people who never open a terminal.

    python -m choral.app            start it (or find the one already running) and open its page

It is a small web server that only this computer can reach (127.0.0.1).  Its page adds a piece - a PDF of the sheet
music - has it read, makes the rehearsal tracks and plays them.  Every piece gets a folder in ~/Music/Palare Piano
(PALARE_LIBRARY names another place): the tracks are in it, and the PDF, the score read from it and the working
files are in its "source" folder.  The work is done by `python -m choral`, run as a program of its own, one piece at
a time; this module only starts it, follows what it says, and shows that."""
import json, os, queue, re, secrets, shutil, signal, subprocess, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.environ.get('PALARE_LIBRARY') or os.path.join(os.path.expanduser('~'), 'Music', 'Palare Piano')
VOICES = os.path.join(ROOT, '.svc', 'voices')
TOKEN = secrets.token_urlsafe(18)          # the page carries it; nothing else on this computer or the web can ask for work
NAMES = {'T1': 'Tenor 1', 'T2': 'Tenor 2', 'BR': 'Baritone', 'BS': 'Bass', 'SOLO': 'Solo'}
ASK = {'T1': 'tenor1', 'T2': 'tenor2', 'BR': 'baritone', 'BS': 'bass', 'SOLO': 'solo'}
ORDER = ('balanced', 'predominant', 'muted', 'alone', 'voices only')
CREDIT = ('The voices on these tracks are from VocalSet: Julia Wilkins, Prem Seetharaman, Alison Wahl and Bryan Pardo,\n'
          '"VocalSet: A Singing Voice Dataset", ISMIR 2018, https://zenodo.org/records/1193957, licensed CC BY 4.0\n'
          '(https://creativecommons.org/licenses/by/4.0/).  The notes, words and timing were sung by Palare Piano and\n'
          're-voiced with Seed-VC.  Keep this credit with the tracks if you share them.\n')

lock = threading.RLock()
jobs = queue.Queue()
waiting = []                               # ids of the pieces in the queue, in order
now = {}                                   # the job being done: id, kind, stage, progress, eta, proc
setup = {'running': False, 'stage': '', 'progress': None, 'error': ''}


# ---- pieces on disk

def folder(pid):
    if not pid or pid != os.path.basename(pid) or pid.startswith('.'):
        raise ValueError('no such piece')
    return os.path.join(LIB, pid)


def info_file(pid):
    return os.path.join(folder(pid), 'source', 'piece.json')


def load(pid):
    with lock:
        return json.load(open(info_file(pid)))


def save(pid, **changes):
    with lock:
        d = json.load(open(info_file(pid))) if os.path.exists(info_file(pid)) else {}
        d.update(changes)
        tmp = info_file(pid) + '.part'
        json.dump(d, open(tmp, 'w'), indent=1)
        os.replace(tmp, info_file(pid))
        return d


def pieces():
    out = []
    if os.path.isdir(LIB):
        for pid in sorted(os.listdir(LIB), key=str.lower):
            try:
                d = load(pid)
            except Exception:
                continue
            d['id'] = pid
            d['tracks'] = [t for t in d.get('tracks', []) if os.path.exists(os.path.join(folder(pid), t))]
            out.append(d)
    return sorted(out, key=lambda d: -d.get('added', 0))


def tail(path, n=12):
    try:
        return [l.rstrip() for l in open(path, errors='replace').read().splitlines() if l.strip()][-n:]
    except OSError:
        return []


def settings(**changes):
    f = os.path.join(LIB, '.settings.json')
    with lock:
        d = json.load(open(f)) if os.path.exists(f) else {}
        if changes:
            d.update(changes); json.dump(d, open(f, 'w'))
        return d


# ---- the voices

def voices_state():
    from . import revoice
    ready = revoice.command() is not None and os.path.isdir(VOICES) and any(f.lower().endswith('.wav') for f in os.listdir(VOICES))
    can = sys.platform == 'darwin' and os.uname().machine == 'arm64'
    why = '' if can else 'Real voices need a Mac with an Apple chip (M1 or later). The built-in voices work everywhere.'
    return dict(ready=bool(ready), can=can or bool(ready), why=why, **{k: setup[k] for k in ('running', 'stage', 'progress', 'error')})


# ---- adding and reading

def add(name, data):
    """A new piece from an uploaded file -> its id.  The file's name is the piece's name until the music says otherwise."""
    name = os.path.basename(urllib.parse.unquote(name)).replace('\\', '')
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext not in ('.pdf', '.score'):
        raise ValueError('Give it the sheet music as a PDF.')
    if ext == '.pdf' and not data.startswith(b'%PDF'):
        raise ValueError('That file is named .pdf but is not a PDF.')
    stem = re.sub(r'[^\w \-,.()\']', '', stem).strip(' .') or 'Piece'
    pid, k = stem, 1
    with lock:
        while os.path.exists(os.path.join(LIB, pid)):
            k += 1; pid = f'{stem} ({k})'
        os.makedirs(os.path.join(LIB, pid, 'source'))
        open(os.path.join(LIB, pid, 'source', stem + ext), 'wb').write(data)
        save(pid, title=stem, file=stem + ext, added=time.time(), status='reading')
        waiting.append(pid)
    jobs.put(('read', pid, {}))
    return pid


def music(pid):
    return os.path.join(folder(pid), 'source', load(pid)['file'])


def score_of(pid):
    return os.path.splitext(music(pid))[0] + '.score'


def what_was_read(pid):
    """Look at the score the reader wrote: what the page will say about the piece, and what it can offer."""
    from . import score as scoremod
    said = []
    sc = scoremod.load(score_of(pid), warn=said.append)
    same = lambda p, q: [(n['beat'], n['dur'], n['midi']) for n in sc.parts[p]] == [(n['beat'], n['dur'], n['midi']) for n in sc.parts[q]]
    have = [p for p in NAMES if sc.parts.get(p)]
    parts = []
    for p in have:
        if p == 'BS' and 'BR' in have and same('BR', 'BS'):
            parts = [x for x in parts if x[0] != 'baritone'] + [('bass', 'Bass (baritones and basses sing one line)')]
        elif p == 'T2' and 'T1' in have and same('T1', 'T2'):
            parts = [x for x in parts if x[0] != 'tenor1'] + [('tenor1', 'Tenor (the tenors sing one line)')]
        else:
            parts.append((ASK[p], NAMES[p]))
    text = open(score_of(pid)).read()
    tempo = re.search(r'(?m)^tempo:\s*([\d.]+)', text)
    log = open(os.path.join(folder(pid), 'source', 'read.log'), errors='replace').read() if os.path.exists(os.path.join(folder(pid), 'source', 'read.log')) else ''
    unsure = [l.strip() for l in log.splitlines() if l.startswith(('  !', '  ?'))]
    secs = float(sc.beats) * 60 / float(tempo.group(1)) if tempo else 0.
    return dict(title=sc.title or load(pid)['title'], measures=len(sc.measures), parts=parts, minutes=round(secs / 60, 1),
                tempo=float(tempo.group(1)) if tempo else None, tempo_guessed='NO TEMPO IS PRINTED' in log and not load(pid).get('tempo_set'),
                latin=bool(re.search(r'(?m)^language:\s*latin', text)), unsure=unsure[:60], unsure_count=len(unsure),
                spelled=sum('is not in the dictionary' in l for l in said))


def run(cmd, logfile, follow=None):
    """Run a program, keep what it says in `logfile`, and hand every line to `follow`.  -> its exit code."""
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    with open(logfile, 'w') as log:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', env=env)
        now['proc'] = p
        if shutil.which('caffeinate'):                 # a Mac left alone goes to sleep; not while this is working
            subprocess.Popen(['caffeinate', '-i', '-w', str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for line in p.stdout:
            log.write(line); log.flush()
            if follow:
                follow(line)
        return p.wait()


def do_read(pid):
    now.update(stage='Reading the music', progress=None, eta=None)
    src = os.path.join(folder(pid), 'source')

    def follow(line):
        m = re.search(r'finding the staves on (\d+) page', line)
        if m:
            now['stage'] = 'Reading the music (a scan takes about half a minute a page)'
    code = run([sys.executable, '-m', 'choral', music(pid), '--read'], os.path.join(src, 'read.log'), follow)
    if now.get('stopped'):
        return save(pid, status='unreadable', error=['Stopped.'])
    if code or not os.path.exists(score_of(pid)):
        return save(pid, status='unreadable', error=tail(os.path.join(src, 'read.log')))
    try:
        got = what_was_read(pid)
    except Exception as e:
        return save(pid, status='unreadable', error=[str(e)] + tail(os.path.join(src, 'read.log'), 6))
    if not got['parts']:
        return save(pid, status='unreadable', error=['No tenor, baritone or bass part was found in this music.'])
    save(pid, status='read', read=got, title=got['title'], error=None)


# ---- making the tracks

def do_render(pid, opt):
    src = os.path.join(folder(pid), 'source')
    wavs = os.path.join(src, 'wav')
    shutil.rmtree(wavs, ignore_errors=True)
    real = opt.get('voices') == 'real' and voices_state()['ready']
    singers = 4 if str(opt.get('singers')) == '4' else 12
    cmd = [sys.executable, '-m', 'choral', music(pid), '--part', opt['part'], '--singers', str(singers), '--out', wavs]
    if real:
        cmd += ['--voice', VOICES]
    now.update(stage='Reading the music', progress=None, eta=None)
    try:                                               # the score may have been corrected by hand since it was read
        save(pid, read=what_was_read(pid))
    except Exception:
        pass                                           # (if it no longer makes sense, the render says why)

    def follow(line):
        if 'the quick syllables last' in line:
            now.update(stage='The choir is singing')
        m = re.search(r're-voicing (\d+) singers: (\d+) minutes of singing in (\d+) stretches', line)
        if m:
            now.update(stage='Giving %s singers real voices' % m.group(1), progress=0., eta=None)
        m = re.search(r're-voiced (\d+) of (\d+) stretches: [\d.]+ s of singing in ([\d.]+) s', line)
        if m:
            k, n, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            now.update(progress=k / max(n, 1), eta=(n - k) * s / max(k, 1))
        if 'voices sung and re-voiced' in line:
            now.update(stage='Seating the choir', progress=None, eta=None)
        if line.startswith('preset:'):
            now.update(stage='Mixing', progress=None, eta=None)
        if line.startswith('  wrote '):
            now.update(stage='Writing the tracks')
    code = run(cmd, os.path.join(src, 'render.log'), follow)
    if now.get('stopped'):
        return save(pid, status='read', note='Stopped. What was finished is kept: starting again goes on from there.')
    if code:
        return save(pid, status='failed', error=tail(os.path.join(src, 'render.log')))
    now.update(stage='Writing the tracks')
    old = load(pid).get('tracks', [])
    made = []
    for f in sorted(os.listdir(wavs)):
        if not f.endswith('.wav'):
            continue
        out = f[:-4] + '.m4a'
        if shutil.which('afconvert') and not subprocess.run(['afconvert', '-f', 'm4af', '-d', 'aac', '-b', '192000', os.path.join(wavs, f), os.path.join(folder(pid), out)], capture_output=True).returncode:
            made.append(out)
        else:                                          # no converter here: the track as it was written
            shutil.move(os.path.join(wavs, f), os.path.join(folder(pid), f)); made.append(f)
    shutil.rmtree(wavs, ignore_errors=True)
    for f in old:
        if f not in made and os.path.exists(os.path.join(folder(pid), f)):
            os.remove(os.path.join(folder(pid), f))
    rank = lambda f: next((i for i, k in enumerate(ORDER) if f.rsplit('.', 1)[0].endswith(k)), 9)
    made.sort(key=rank)
    credit = os.path.join(folder(pid), 'Credits.txt')
    if real:
        open(credit, 'w').write(CREDIT)
    elif os.path.exists(credit):
        os.remove(credit)
    save(pid, status='ready', tracks=made, made=dict(part=opt['part'], voices='real' if real else 'built-in', singers=singers, when=time.time()), error=None, note=None)
    settings(part=opt['part'], voices='real' if real else 'built-in', singers=singers)


def do_setup():
    setup.update(running=True, stage='Starting', progress=None, error='')
    logfile = os.path.join(LIB, '.voices-setup.log')

    def follow(line):
        m = re.match(r'step (\d+) of (\d+): (.*)', line.strip())
        if m:
            setup.update(stage=f'Step {m.group(1)} of {m.group(2)}: {m.group(3)}', progress=None)
        m = re.match(r'progress (\d+)%', line.strip())
        if m:
            setup.update(progress=int(m.group(1)) / 100)
    code = run([sys.executable, '-m', 'choral.setup_voices'], logfile, follow)
    setup.update(running=False, progress=None, stage='', error='' if not code else '\n'.join(tail(logfile, 8)))


def worker():
    while True:
        kind, pid, opt = jobs.get()
        with lock:
            now.clear(); now.update(id=pid, kind=kind, stage='', progress=None, eta=None, started=time.time())
            if pid in waiting:
                waiting.remove(pid)
        try:
            if kind == 'setup':
                do_setup()
            elif not os.path.exists(info_file(pid)):
                pass                                   # removed while it waited
            elif kind == 'read':
                do_read(pid)
            else:
                save(pid, status='rendering', note=None)
                do_render(pid, opt)
        except Exception as e:
            if kind == 'setup':
                setup.update(running=False, error=str(e))
            elif os.path.exists(info_file(pid)):
                save(pid, status='failed' if kind == 'render' else 'unreadable', error=[f'{type(e).__name__}: {e}'])
        finally:
            with lock:
                now.clear()


def stop_now():
    p = now.get('proc')
    if p and p.poll() is None:
        now['stopped'] = True
        p.send_signal(signal.SIGTERM)


# ---- what the page asks

def state():
    with lock:
        job = {k: now.get(k) for k in ('id', 'kind', 'stage', 'progress', 'eta')} if now else None
        return dict(pieces=pieces(), job=job, waiting=list(waiting), voices=voices_state(), library=LIB,
                    last=settings(), demo=os.path.exists(os.path.join(ROOT, 'scores', 'demo_shenandoah.score')))


def act(path, q, body):
    """A request from the page -> what to answer."""
    pid = q.get('id')
    if path == '/api/add':
        return dict(id=add(q.get('name', ''), body))
    if path == '/api/demo':
        return dict(id=add('Shenandoah (demo).score', open(os.path.join(ROOT, 'scores', 'demo_shenandoah.score'), 'rb').read()))
    if path == '/api/render':
        d = load(pid)
        if d.get('status') not in ('read', 'ready', 'failed') or pid in waiting or now.get('id') == pid:
            raise ValueError('This piece is busy.')
        if q.get('part') not in [p for p, _ in d['read']['parts']]:
            raise ValueError('Choose your part first.')
        with lock:
            waiting.append(pid)
        save(pid, status='queued', error=None, note=None)
        jobs.put(('render', pid, dict(part=q['part'], voices=q.get('voices'), singers=q.get('singers'))))
        return {}
    if path == '/api/stop':
        with lock:
            if now.get('id') == pid:
                stop_now()
            elif pid in waiting:                       # not started yet: take it out of the line
                waiting.remove(pid)
                d = load(pid)
                save(pid, status='ready' if d.get('tracks') else 'read' if d.get('read') else 'unreadable')
        return {}
    if path == '/api/tempo':
        bpm = float(q.get('bpm', 0))
        if not 30 <= bpm <= 240:
            raise ValueError('A tempo is between 30 and 240 beats a minute.')
        text = open(score_of(pid)).read()
        text, n = re.subn(r'(?m)^tempo:\s*[\d.]+', 'tempo: %g' % bpm, text, count=1)
        if not n:
            raise ValueError('This score has no tempo line to change.')
        open(score_of(pid), 'w').write(text)
        save(pid, tempo_set=True)
        save(pid, read=what_was_read(pid))
        return {}
    if path == '/api/reveal':
        subprocess.run(['open', folder(pid)] if sys.platform == 'darwin' else ['xdg-open', folder(pid)])
        return {}
    if path == '/api/score':
        subprocess.run(['open', '-e', score_of(pid)] if sys.platform == 'darwin' else ['xdg-open', score_of(pid)])
        return {}
    if path == '/api/reread':                          # after the score was corrected by hand: look at it again
        save(pid, read=what_was_read(pid))
        return {}
    if path == '/api/remove':
        with lock:
            if now.get('id') == pid or pid in waiting:
                raise ValueError('Stop it first.')
            trash = os.path.join(os.path.expanduser('~'), '.Trash')
            if os.path.isdir(trash):                   # to the Trash, where it can be got back
                dest, k = os.path.join(trash, pid), 1
                while os.path.exists(dest):
                    k += 1; dest = os.path.join(trash, f'{pid} {k}')
                shutil.move(folder(pid), dest)
            else:
                shutil.rmtree(folder(pid))
        return {}
    if path == '/api/voices':
        if setup['running'] or voices_state()['ready']:
            return {}
        setup.update(running=True, stage='Waiting for its turn', error='')
        jobs.put(('setup', None, {}))
        return {}
    if path == '/api/quit':
        stop_now()
        threading.Timer(.3, lambda: os._exit(0)).start()
        return {}
    raise KeyError(path)


class Page(BaseHTTPRequestHandler):
    server_version = 'PalarePiano'

    def log_message(self, *a):
        pass

    def local(self):
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost')

    def send(self, code, body, kind='application/json', more=()):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in more:
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_GET(self):
        if not self.local():
            return self.send(403, {'error': 'only from this computer'})
        url = urllib.parse.urlparse(self.path)
        if url.path == '/':
            html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.html'), encoding='utf-8').read()
            return self.send(200, html.replace('{{TOKEN}}', TOKEN).encode(), 'text/html; charset=utf-8')
        if url.path == '/api/ping':
            return self.send(200, {'app': 'Palare Piano'})
        if url.path == '/api/state':
            return self.send(200, state())
        if url.path.startswith('/file/'):
            try:
                _, _, pid, name = urllib.parse.unquote(url.path).split('/', 3)
                f = os.path.join(folder(pid), os.path.basename(name))
                size = os.path.getsize(f)
            except (ValueError, OSError):
                return self.send(404, {'error': 'no such track'})
            kind = {'.m4a': 'audio/mp4', '.wav': 'audio/wav', '.txt': 'text/plain; charset=utf-8'}.get(os.path.splitext(f)[1].lower(), 'application/octet-stream')
            a, b = 0, size - 1
            m = re.match(r'bytes=(\d*)-(\d*)', self.headers.get('Range') or '')
            if m and (m.group(1) or m.group(2)):       # a player asks for the part it wants
                if m.group(1):
                    a = int(m.group(1)); b = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:
                    a = max(0, size - int(m.group(2)))
                if a > b or a >= size:
                    return self.send(416, b'', kind, [('Content-Range', f'bytes */{size}')])
            self.send_response(206 if m and (m.group(1) or m.group(2)) else 200)
            self.send_header('Content-Type', kind)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(b - a + 1))
            if m and (m.group(1) or m.group(2)):
                self.send_header('Content-Range', f'bytes {a}-{b}/{size}')
            if url.query == 'save':
                self.send_header('Content-Disposition', 'attachment; filename*=UTF-8\'\'' + urllib.parse.quote(os.path.basename(f)))
            self.end_headers()
            try:
                with open(f, 'rb') as fh:
                    fh.seek(a); left = b - a + 1
                    while left > 0:
                        chunk = fh.read(min(1 << 16, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.send(404, {'error': 'nothing here'})

    do_HEAD = do_GET

    def do_POST(self):
        if not self.local() or self.headers.get('X-Palare') != TOKEN:
            return self.send(403, {'error': 'Reload the page.'})
        url = urllib.parse.urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        if n > 300 << 20:
            return self.send(413, {'error': 'That file is too large.'})
        body = self.rfile.read(n) if n else b''
        try:
            if url.path == '/api/add':
                q = {'name': self.headers.get('X-Filename', '')}
            else:
                q = json.loads(body or b'{}')
            self.send(200, act(url.path, q, body))
        except (ValueError, KeyError, OSError) as e:
            self.send(400, {'error': str(e).strip("'") or 'That did not work.'})


def running(port):
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/ping', timeout=1) as r:
            return json.load(r).get('app') == 'Palare Piano'
    except Exception:
        return False


def show(url):
    if os.environ.get('PALARE_NO_BROWSER'):
        return
    if sys.platform == 'darwin':
        subprocess.run(['open', url])
    else:
        import webbrowser
        webbrowser.open(url)


def main():
    os.makedirs(LIB, exist_ok=True)
    note = os.path.join(LIB, '.server.json')
    try:
        port = json.load(open(note))['port']
        if running(port):                              # already open: bring its page to the front
            return show(f'http://127.0.0.1:{port}/')
    except Exception:
        pass
    server = None
    for port in [int(os.environ['PALARE_PORT'])] if os.environ.get('PALARE_PORT') else range(8765, 8790):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), Page); break
        except OSError:
            continue
    if server is None:
        raise SystemExit('No free port between 8765 and 8789 on this computer.')
    json.dump({'port': port, 'pid': os.getpid()}, open(note, 'w'))
    with lock:                                         # whatever was under way when it was last closed did not finish
        for d in pieces():
            if d.get('status') in ('reading',):
                waiting.append(d['id']); jobs.put(('read', d['id'], {}))
            elif d.get('status') in ('queued', 'rendering'):
                save(d['id'], status='ready' if d.get('tracks') else 'read', note='This was interrupted. What was finished is kept: starting again goes on from there.')
    threading.Thread(target=worker, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: (stop_now(), os._exit(0)))
    print(f'Palare Piano is at http://127.0.0.1:{port}/  (pieces are kept in {LIB})', flush=True)
    show(f'http://127.0.0.1:{port}/')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_now()


if __name__ == '__main__':
    main()
