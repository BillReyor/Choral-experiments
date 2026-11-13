"""Does an installed copy work?  Open it the way a person would and do what a singer does, by its page's own requests.

    python tools/try_install.py [--part-all] [--plain] [--keep]

Run after install.sh (Mac, Linux) or install.ps1 (Windows).  It needs nothing but Python: it finds the installed copy
(PALARE_HOME, or where the installer puts it), starts it by what the installer left to start it with - the launcher on
a Mac, the script on Linux, the Start-menu shortcut on Windows - with a library of its own in a temporary folder, and
then, as the page would: adds the demo piece, waits for it to be read, moves a note and puts it back, makes the tracks
with the built-in voices, fetches one and listens for sound in it, makes the files to share, waits for the computer
check, saves a report, removes the piece and quits.  --part-all makes the tracks for every part and the files to share; --plain has
the tracks left as they were written (.wav), so that they can be listened to here: is there sound in them?  Anything that does not go as it should ends the run with what went wrong and the
last lines the program wrote.  This is what the automatic tests on GitHub run on each system (.github/workflows)."""
import json, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request

PORT = int(os.environ.get('PALARE_PORT') or 8791)
URL = f'http://127.0.0.1:{PORT}'


def base():
    if os.environ.get('PALARE_HOME'):
        return os.environ['PALARE_HOME']
    home = os.path.expanduser('~')
    if sys.platform == 'darwin':
        return os.path.join(home, 'Library', 'Application Support', 'Palare-Piano')
    if os.name == 'nt':
        return os.path.join(os.environ['LOCALAPPDATA'], 'Palare-Piano')
    return os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.join(home, '.local', 'share'), 'Palare-Piano')


def get(path, raw=False):
    with urllib.request.urlopen(URL + path, timeout=30) as r:
        data = r.read()
    return data if raw else json.loads(data)


def tail(path, n=25):
    try:
        return ''.join(open(path, encoding='utf-8', errors='replace').readlines()[-n:])
    except OSError:
        return f'(no {path})\n'


class Trial:
    def __init__(self):
        self.base = base()
        self.lib = tempfile.mkdtemp(prefix='palare-library-')
        self.token = ''

    def post(self, path, **data):
        req = urllib.request.Request(URL + path, json.dumps(data).encode(), {'X-Palare': self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            raise SystemExit(self.wrong(f'{path} was refused: {e.read().decode(errors="replace")}'))

    def wrong(self, what):
        out = [f'\nNOT RIGHT: {what}', '', '--- the last the program wrote (app.log):', tail(os.path.join(self.base, 'app.log'))]
        for root, _, files in os.walk(self.lib):
            for f in files:
                if f.endswith('.log'):
                    out += [f'--- {os.path.relpath(os.path.join(root, f), self.lib)}:', tail(os.path.join(root, f))]
        return '\n'.join(out)

    def piece(self, pid):
        return next((p for p in get('/api/state')['pieces'] if p['id'] == pid), None)

    def wait(self, what, test, seconds):
        t0, last = time.time(), None
        while time.time() - t0 < seconds:
            try:
                got = test()
            except (OSError, ValueError) as e:
                got, last = None, e
            if got:
                print(f'  {what}: {time.time() - t0:.0f} s', flush=True)
                return got
            time.sleep(1)
        raise SystemExit(self.wrong(f'waited {seconds} s for: {what}' + (f' ({last})' if last else '')))

    def start(self):
        try:
            v = json.load(open(os.path.join(self.base, 'version.json'), encoding='utf-8'))
        except (OSError, ValueError) as e:
            raise SystemExit(f'NOT RIGHT: no installed copy in {self.base} ({e})')
        print(f'installed copy: version {v["version"][:12]}, started by {v["start"]}', flush=True)
        if not os.path.exists(v['start']):
            raise SystemExit(f'NOT RIGHT: what should start it is not there: {v["start"]}')
        os.environ.update(PALARE_LIBRARY=self.lib, PALARE_PORT=str(PORT), PALARE_NO_BROWSER='1')
        if '--plain' in sys.argv:
            os.environ['PALARE_PLAIN_TRACKS'] = '1'
        if os.name == 'nt':
            os.startfile(v['start'])                   # the shortcut, as a double-click would
        else:
            subprocess.run(['sh', v['start']], check=True)
        self.wait('the page answers', lambda: get('/api/ping').get('app') == 'Palare Piano', 90)
        m = re.search(r'const TOKEN = "([^"]+)"', get('/', raw=True).decode('utf-8'))
        if not m:
            raise SystemExit(self.wrong('the page does not carry its token'))
        self.token = m.group(1)
        s = get('/api/state')
        print(f'  library {s["library"]}; a Mac: {s["mac"]}; can update itself: {s["update"]["can"]}', flush=True)
        if os.path.normcase(os.path.realpath(s['library'])) != os.path.normcase(os.path.realpath(self.lib)):
            raise SystemExit(self.wrong(f'it is not using the library it was given ({s["library"]}): another copy was already open?'))

    def sing(self, everyone):
        pid = self.post('/api/demo')['id']
        p = self.wait('the demo piece is read', lambda: (lambda d: d if d and d['status'] in ('read', 'unreadable') else None)(self.piece(pid)), 180)
        if p['status'] != 'read':
            raise SystemExit(self.wrong(f'the demo piece could not be read: {p.get("error")}'))
        parts = p['read']['parts']
        print('  parts: ' + ', '.join(x[1] for x in parts), flush=True)

        # the fixer: move the first note of the second measure up a step, see that it moved, and undo it
        o = self.post('/api/fix/open', id=pid, n=2)
        staff = o['measure']['staves'][0]
        note = next(n for n in staff['notes'] if not n['rest'])
        was = note['pitches'][0]['midi']
        m = self.post('/api/fix/move', id=pid, n=2, line=staff['line'], t=note['t'], k=0, step=1)
        moved = next(s for s in m['measure']['staves'] if s['line'] == staff['line'])['notes'][note['t']]['pitches'][0]['midi']
        if moved <= was or m['changed'] != 1:
            raise SystemExit(self.wrong(f'the fixer did not move the note (was {was}, is {moved}, changed {m["changed"]})'))
        m = self.post('/api/fix/undo', id=pid, n=2)
        back = next(s for s in m['measure']['staves'] if s['line'] == staff['line'])['notes'][note['t']]['pitches'][0]['midi']
        if back != was or m['changed']:
            raise SystemExit(self.wrong('the fixer did not put the note back'))
        m = self.post('/api/fix/spoken', id=pid, n=2, line=staff['line'], t=note['t'], on=True)
        said = next(s for s in m['measure']['staves'] if s['line'] == staff['line'])['notes'][note['t']]['spoken']
        m = self.post('/api/fix/undo', id=pid, n=2)
        if not said or next(s for s in m['measure']['staves'] if s['line'] == staff['line'])['notes'][note['t']]['spoken']:
            raise SystemExit(self.wrong('the fixer did not mark the note as spoken, or did not put it back'))
        print('  the fixer moves a note, marks one as spoken, and puts both back', flush=True)

        part = 'all' if everyone else parts[min(1, len(parts) - 1)][0]
        self.post('/api/render', id=pid, part=part, voices='built-in', singers=4)
        p = self.wait('the tracks are made', lambda: (lambda d: d if d and d['status'] in ('ready', 'failed') else None)(self.piece(pid)), 1500)
        if p['status'] != 'ready':
            raise SystemExit(self.wrong(f'the tracks were not made: {p.get("error")}'))
        want = 5 * len(parts) if everyone else 5            # three of one's own and two all share; for everyone, a set for each part
        print(f'  {len(p["tracks"])} tracks, the first: {p["tracks"][0]}', flush=True)
        if len(p['tracks']) != want:
            raise SystemExit(self.wrong(f'{len(p["tracks"])} tracks where {want} were expected: {p["tracks"]}'))
        for t in p['tracks']:
            data = get('/file/' + urllib.parse.quote(pid) + '/' + '/'.join(urllib.parse.quote(x) for x in t.split('/')), raw=True)
            size = len(data)
            if size < 30000:
                raise SystemExit(self.wrong(f'the track {t} is only {size} bytes'))
            if t.endswith('.wav'):                     # (a squeezed track is taken on trust; a plain one is listened to)
                import array, io, wave
                with wave.open(io.BytesIO(data)) as w:
                    a = array.array('h', w.readframes(w.getnframes()))
                loud = max(abs(x) for x in a[::7]) if a else 0
                if loud < 1000:
                    raise SystemExit(self.wrong(f'the track {t} is silent (its loudest moment is {loud} of 32768)'))
        kind = os.path.splitext(p['tracks'][0])[1]
        if '--plain' in sys.argv and kind != '.wav':
            raise SystemExit(self.wrong(f'the tracks were to be left as written, and are {kind}'))
        if '--plain' not in sys.argv and kind == '.wav':
            raise SystemExit(self.wrong('the tracks were not saved small: nothing here did it (the Mac\'s converter, ffmpeg, or the MP3 encoder the installer adds)'))
        print(f'  every track was fetched from the page ({kind}, about {size // 1024} KB each)' + (' and has sound in it' if kind == '.wav' else ''), flush=True)
        if everyone:
            self.post('/api/share', id=pid)
            zips = [f for _, _, fs in os.walk(os.path.join(self.lib, pid)) for f in fs if f.endswith('.zip')]
            if len(zips) != len(parts):
                raise SystemExit(self.wrong(f'{len(zips)} files to share where {len(parts)} were expected: {zips}'))
            print(f'  {len(zips)} files to share, one for each part', flush=True)
        return pid

    def computer(self):
        c = self.wait('the computer check has finished', lambda: (lambda s: s['computer'] if s['computer'] and not s['checking'] else None)(get('/api/state')), 300)
        mc = c['machine']
        print(f'  this computer: {mc["chip"]}, {mc["memory"]} GB, {mc["cores"]} processors, {mc["disk"]} GB free; {c["slow"]} times as slow as the reference', flush=True)
        for r in c['rows']:
            print(f'    {r["what"]:26} {r["level"]:5} {r["time"]:18} {r["why"]}', flush=True)
        quick = next(r for r in c['rows'] if r['key'] == 'quick')
        if quick['level'] == 'no' or not mc['memory'] or not mc['cores']:
            raise SystemExit(self.wrong('the check does not know this computer, or says a quick listen will not work on it'))

    def report(self, pid):
        r = self.post('/api/report')
        text, name = r['text'], os.path.basename(os.path.expanduser('~'))
        for want in ('Palare Piano report', 'version:', 'computer:', '== Shenandoah', 'tracks:'):
            if want not in text:
                raise SystemExit(self.wrong(f'the report has no "{want}" in it:\n{text[:1500]}'))
        if os.path.expanduser('~') in text:
            raise SystemExit(self.wrong('the report names the home folder: it should not say whose computer this is'))
        print(f'  the report: {r["name"]}, {len(text.splitlines())} lines, and it does not name the home folder ({name})', flush=True)

    def end(self, pid):
        self.post('/api/remove', id=pid)
        if self.piece(pid) or os.path.isdir(os.path.join(self.lib, pid)):
            raise SystemExit(self.wrong('the piece is still there after it was removed'))
        self.post('/api/quit')

        def gone():
            try:
                get('/api/ping')
            except OSError:
                return True
        self.wait('it has quit', gone, 30)


def main():
    t = Trial()
    t.start()
    try:
        pid = t.sing('--part-all' in sys.argv)
        t.computer()
        t.report(pid)
    except BaseException:
        try:
            t.post('/api/quit')
        except BaseException:
            pass
        raise
    t.end(pid)
    if '--keep' not in sys.argv:
        import shutil
        shutil.rmtree(t.lib, ignore_errors=True)
    print('ALL RIGHT: it installs, opens, reads, fixes, sings and quits here.', flush=True)


if __name__ == '__main__':
    main()
