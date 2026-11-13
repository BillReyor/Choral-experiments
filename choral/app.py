"""Palare Piano in a browser window, for people who never open a terminal.

    python -m choral.app            start it (or find the one already running) and open its page

It is a small web server that only this computer can reach (127.0.0.1).  Its page adds a piece - a PDF of the sheet
music - has it read, makes the rehearsal tracks and plays them.  Every piece gets a folder in ~/Music/Palare Piano
(PALARE_LIBRARY names another place): the tracks are in it, and the PDF, the score read from it and the working
files are in its "source" folder.  The work is done by `python -m choral`, run as a program of its own, one piece at
a time; this module only starts it, follows what it says, and shows that."""
import json, os, platform, queue, re, secrets, shutil, signal, subprocess, sys, threading, time, urllib.parse
os.environ.setdefault('ORT_DISABLE_TELEMETRY', '1')        # nothing started from here reports its use to anyone
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import hidden, show as show_path, utf8

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = re.sub(r'(?i)pythonw(\.exe)$', r'python\1', sys.executable)         # (Windows starts this without a window; what it runs needs to be heard)
LIB = os.environ.get('PALARE_LIBRARY') or os.path.join(os.path.expanduser('~'), 'Music', 'Palare Piano')
VOICES = os.path.join(ROOT, '.svc', 'voices')
TOKEN = secrets.token_urlsafe(18)          # the page carries it; nothing else on this computer or the web can ask for work
NAMES = {'T1': 'Tenor 1', 'T2': 'Tenor 2', 'BR': 'Baritone', 'BS': 'Bass', 'SOLO': 'Solo'}
ASK = {'T1': 'tenor1', 'T2': 'tenor2', 'BR': 'baritone', 'BS': 'bass', 'SOLO': 'solo'}
ORDER = ('balanced', 'predominant', 'muted', 'alone', 'voices only')
SHARE = 'To share'                         # the folder of zip files, one for each part
CREDIT = ('The voices on these tracks are from VocalSet: Julia Wilkins, Prem Seetharaman, Alison Wahl and Bryan Pardo,\n'
          '"VocalSet: A Singing Voice Dataset", ISMIR 2018, https://zenodo.org/records/1193957, licensed CC BY 4.0\n'
          '(https://creativecommons.org/licenses/by/4.0/).  The notes, words and timing were sung by Palare Piano and\n'
          're-voiced with Seed-VC.  Keep this credit with the tracks if you share them.\n')

BOOT = secrets.token_hex(6)                # which run of the program this is: the page starts afresh when it changes
REPO = 'BillReyor/Palare-Piano'
CHANNEL = 'stable'                         # the branch people are given: moved on only to a version that passed the tests on
#                                            a Mac, Windows and Linux (tools/release.sh); work in progress is on "main"
newer = {'checked': 0., 'count': 0, 'news': [], 'error': '', 'updating': False}

lock = threading.RLock()
jobs = queue.Queue()
waiting = []                               # ids of the pieces in the queue, in order
now = {}                                   # the job being done: id, kind, stage, progress, eta, proc
setup = {'running': False, 'stage': '', 'progress': None, 'error': ''}
checking = {'running': False}


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
            if d.get('read'):                          # the places to look at, briefly: the page asks for the whole of one when it shows it
                d['unsure'] = [dict(key=u['key'], title=u['title'], go=u['measures'][0] if u['measures'] else None) for u in unsure(pid)]
            try:                                       # corrected since its tracks were made: they are out of date
                sf = os.path.splitext(os.path.join(folder(pid), 'source', d['file']))[0] + '.score'
                d['stale'] = bool(d['tracks']) and os.path.getmtime(sf) > (d.get('made') or {}).get('when', 1e18)
            except (OSError, KeyError):
                d['stale'] = False
            out.append(d)
    return sorted(out, key=lambda d: -d.get('added', 0))


_unsure = {}


def unsure(pid, everything=False):
    """The places in a piece the program was unsure of (choral/fix.py), without those someone has said are right."""
    from . import fix
    try:
        sf = score_of(pid)
        log = os.path.join(folder(pid), 'source', 'read.log')
        stamp = (os.path.getmtime(sf), os.path.getmtime(log) if os.path.exists(log) else 0)
        if _unsure.get(pid, (None,))[0] != stamp:
            _unsure[pid] = (stamp, fix.doubts(sf, open(log, errors='replace').read() if os.path.exists(log) else ''))
        done = set() if everything else set(load(pid).get('checked', []))
        return [d for d in _unsure[pid][1] if d['key'] not in done]
    except Exception:
        return []


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


# ---- is there a newer version?

def version():
    """What install.sh wrote down about this copy: which version it is, when it was installed, where its launcher is.
    None for a copy that was not installed by it (a programmer's own): that one is not offered updates."""
    try:
        v = json.load(open(os.path.join(os.path.dirname(ROOT), 'version.json')))
        return v if re.fullmatch(r'[0-9a-f]{40}', v.get('version', '')) else None
    except (OSError, ValueError):
        return None


def channel():
    """Which branch this copy follows: the one it was installed from, or the one everybody is given."""
    return (version() or {}).get('channel') or CHANNEL


def line():
    """What installs the program, and brings it up to date, on this kind of computer."""
    raw = f'https://raw.githubusercontent.com/{REPO}/{channel()}/install'
    return f'irm {raw}.ps1 | iex' if os.name == 'nt' else f'wget -qO- {raw}.sh | sh' if sys.platform != 'darwin' and not shutil.which('curl') else f'curl -fsSL {raw}.sh | sh'


def look_for_newer():
    """Ask GitHub what has been published since this copy's version.  Nothing about this computer or its music is
    sent: it is the address of a public page, with the version in it."""
    import urllib.request
    v = version()
    if not v:
        return
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/compare/{v['version']}...{channel()}",
                                     headers={'User-Agent': 'palare-piano', 'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        titles = [c['commit']['message'].split('\n')[0].strip() for c in d.get('commits', [])][::-1]       # newest first
        newer.update(checked=time.time(), count=len(titles), news=[t for t in titles if not t.lower().startswith('journal')][:8], error='')
    except Exception as e:
        newer.update(checked=time.time(), error=f'{type(e).__name__}')


def keep_looking():
    while True:
        look_for_newer()
        time.sleep(6 * 3600)


def update_now():
    """Bring this copy up to date from the page: run the installer as a program of its own - it closes this copy, puts the
    new one in its place and starts it - and let the page wait for the new one to answer."""
    v = version()
    if not v:
        raise ValueError('This copy was not installed by the installer, so it cannot update itself.')
    with lock:
        if now or waiting:
            raise ValueError('Something is being made. Let it finish, or stop it, and then update.')
        newer.update(updating=True)
    home = os.path.dirname(ROOT)
    start = v.get('start') or os.path.join(v.get('launcher') or '', 'Contents', 'MacOS', 'launcher')      # what starts the program again
    env = dict(os.environ, PALARE_HOME=home, PALARE_NO_OPEN='1', PALARE_NO_BROWSER='1', PALARE_CHANNEL=channel(), **({'PALARE_LAUNCHER': v['launcher']} if v.get('launcher') else {}))
    log = open(os.path.join(home, 'update.log'), 'w')
    if os.name == 'nt':                                # (the page that is open finds the new copy by itself: no second window)
        again = f"; Start-Process -FilePath '{start}'" if os.path.exists(start) else ''
        subprocess.Popen(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', f'{line()}{again}'], stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, env=env, cwd=home, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        again = f'sh "{start}"' if os.path.exists(start) else 'true'
        subprocess.Popen(['/bin/sh', '-c', f'{line()}; {again}'], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, cwd=home, start_new_session=True)


# ---- the voices

def voices_state():
    from . import revoice
    ready = revoice.command() is not None and os.path.isdir(VOICES) and any(f.lower().endswith('.wav') for f in os.listdir(VOICES))
    can = sys.platform == 'darwin' and platform.machine() == 'arm64'
    why = '' if can else 'Real voices are only set up for Macs with an Apple chip so far. The built-in voices work on this computer, and someone with such a Mac can make real-voice tracks for every part and share them.'
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
    for p in have:                                     # (what to ask for, what to call it, a word of explanation if any)
        if p == 'BS' and 'BR' in have and same('BR', 'BS'):
            parts = [x for x in parts if x[0] != 'baritone'] + [('bass', 'Bass', 'Baritones and basses sing one line in this piece.')]
        elif p == 'T2' and 'T1' in have and same('T1', 'T2'):
            parts = [x for x in parts if x[0] != 'tenor1'] + [('tenor1', 'Tenor', 'The tenors sing one line in this piece.')]
        else:
            parts.append((ASK[p], NAMES[p]))
    # Where another part sings a part's very notes - a passage in unison - leaving that part out of a track does not
    # take its line out of it.  The page says so beside the "muted" track: the measures where every note of the part
    # is some other part's note too (the same pitch as it sounds, at the same moment, for as long).
    same_note = lambda n: (round(n['beat'] * 96), round(n['dur'] * 96), n['midi'])
    doubled = {}
    for ask, *_ in parts:
        mine = [p for p in have if ASK[p] == ask]
        if ask == 'bass' and 'baritone' not in [x[0] for x in parts] and 'BR' in have:
            mine = ['BR', 'BS']
        if ask == 'tenor1' and 'tenor2' not in [x[0] for x in parts] and 'T2' in have:
            mine = ['T1', 'T2']
        others = {same_note(n) for p in have if p not in mine for n in sc.parts[p]}
        per = {}
        for p in mine:
            for n in sc.parts[p]:
                m = (sc.printed or {}).get(n['m'], n['m'])
                per[m] = per.get(m, True) and same_note(n) in others
        if any(per.values()):
            doubled[ask] = sorted(m for m, v in per.items() if v)
    text = open(score_of(pid)).read()
    tempo = re.search(r'(?m)^tempo:\s*([\d.]+)', text)
    log = open(os.path.join(folder(pid), 'source', 'read.log'), errors='replace').read() if os.path.exists(os.path.join(folder(pid), 'source', 'read.log')) else ''
    unsure = [l.strip() for l in log.splitlines() if l.startswith(('  !', '  ?'))]
    secs = float(sc.beats) * 60 / float(tempo.group(1)) if tempo else 0.
    return dict(title=sc.title or load(pid)['title'], measures=len(sc.measures), parts=parts, minutes=round(secs / 60, 1),
                tempo=float(tempo.group(1)) if tempo else None, tempo_guessed='NO TEMPO IS PRINTED' in log and not load(pid).get('tempo_set'),
                latin=bool(re.search(r'(?m)^language:\s*latin', text)), unsure=unsure[:60], unsure_count=len(unsure),
                spelled=sum('is not in the dictionary' in l for l in said), doubled=doubled)


def computer():
    """What the last check of this computer found (choral/check.py), or None."""
    try:
        return json.load(open(os.path.join(LIB, '.computer.json')))
    except (OSError, ValueError):
        return None


def report():
    """What to send when something has not gone right: the version, the computer, and what the program noted about each
    piece.  Not the music: no score and no track is in it.  The reader's remarks name measures and parts, and here and
    there a single word it stumbled over; the name of the home folder is taken out of every path.  -> the text"""
    v, c, base = version() or {}, computer() or {}, os.path.dirname(ROOT)
    mc = c.get('machine') or {}
    out = [f'Palare Piano report, {time.strftime("%Y-%m-%d %H:%M")}', '',
           f'version:   {v["version"][:12]}, following "{channel()}", installed {v.get("installed", "?")}' if v else 'version:   a copy that the installer did not put here',
           f'system:    {platform.platform()}; Python {platform.python_version()}',
           f'computer:  {mc.get("chip", "?")}; {mc.get("memory", "?")} GB of memory; {mc.get("cores", "?")} processors; {mc.get("disk", "?")} GB free'
           + (f'; {c.get("slow")} times as slow as the reference; {c.get("at_once")} voices sung at once' if c else '; the check has not run'),
           *[f'           {r["what"]}: {r["level"]} {r.get("time") or ""} {r.get("why") or ""}'.rstrip() for r in c.get('rows', [])],
           f'voices:    real voices {"added" if voices_state()["ready"] else "not added"}',
           f'updates:   {newer["count"]} newer; {("could not ask: " + newer["error"]) if newer["error"] else "asked"}']
    said = lambda title, lines: [f'  --- {title}:'] + [f'      {l}' for l in lines] if lines else []
    for d in pieces():
        pid = d['id']
        src = os.path.join(folder(pid), 'source')
        try:
            f = os.path.join(src, d['file'])
            kind = f'{os.path.splitext(f)[1] or "?"}, {max(1, os.path.getsize(f) // 1024)} KB' + (', read as a scan' if os.path.isdir(os.path.splitext(f)[0] + '.scan') else '')
        except (OSError, KeyError):
            kind = 'its file is missing'
        r, made = d.get('read') or {}, d.get('made') or {}
        out += ['', f'== {d.get("title") or pid}  [{d.get("status")}]  ({kind})']
        if r:
            out.append('  read: ' + ', '.join(str(p[1]) for p in r.get('parts', [])) + ''.join(f'; {k} {r[k]}' for k in ('measures', 'minutes', 'tempo', 'tempo_guessed', 'latin', 'spelled') if r.get(k) not in (None, False)))
        if made:
            out.append(f'  tracks: {len(d.get("tracks", []))} made for {made.get("part")} with {made.get("voices")} voices, {made.get("singers")} to a part' + ('; corrected since' if d.get('stale') else ''))
        out += said('what went wrong', d.get('error') or [])
        doubts = unsure(pid, everything=True) if r else []
        out += said(f'{len(doubts)} places the reader was unsure of', [f'{u.get("title")} (measures {", ".join(map(str, u.get("measures", [])[:8])) or "-"})' for u in doubts[:40]])
        out += said('the end of what the reader said', tail(os.path.join(src, 'read.log'), 60))
        out += said('the end of what the singing said', tail(os.path.join(src, 'render.log'), 30))
    out += ['', '== the program itself']
    for title, path, n in (('started', os.path.join(base, 'app.log'), 40), ('last update', os.path.join(base, 'update.log'), 15),
                           ('computer check', os.path.join(LIB, '.computer.log'), 8), ('adding real voices', os.path.join(LIB, '.voices-setup.log'), 20)):
        out += said(title, tail(path, n))
    text = '\n'.join(out) + '\n'
    for home in {os.path.expanduser('~'), os.path.realpath(os.path.expanduser('~'))}:
        text = text.replace(home, '~')
    return text[:300000]


def run(cmd, logfile, follow=None):
    """Run a program, keep what it says in `logfile`, and hand every line to `follow`.  -> its exit code."""
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    found = computer()
    if found and found.get('at_once'):                 # a machine short of memory sings fewer voices at once (render.at_once)
        env.setdefault('CHORAL_WORKERS', str(found['at_once']))
    with open(logfile, 'w') as log:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', env=env, **hidden())
        now['proc'] = p
        if shutil.which('caffeinate'):                 # a Mac left alone goes to sleep; not while this is working
            subprocess.Popen(['caffeinate', '-i', '-w', str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for line in p.stdout:
            log.write(line); log.flush()
            if follow:
                follow(line)
        return p.wait()


def do_read(pid, again=False):
    now.update(stage='Reading the music', progress=None, eta=None)
    src = os.path.join(folder(pid), 'source')
    if again and music(pid).lower().endswith('.pdf') and os.path.exists(score_of(pid)) and not os.path.exists(score_of(pid) + '.as-read'):
        os.remove(score_of(pid))                       # what was read before and never touched: read the PDF afresh

    code = run([PY, '-m', 'choral', music(pid), '--read'], os.path.join(src, 'read.log'))
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
    everyone = opt['part'] == 'all'                    # tracks for every part, to hand round the chorus
    parts = load(pid)['read']['parts']
    asked = ','.join(x[0] for x in parts) if everyone else opt['part']
    cmd = [PY, '-m', 'choral', music(pid), '--part', asked, '--singers', str(singers), '--out', wavs]
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
    if now.get('stopped'):                             # (the tracks made before, if any, are still there and still shown)
        return save(pid, status='ready' if load(pid).get('tracks') else 'read', note='Stopped. What was finished is kept: starting again goes on from there.')
    if code:
        return save(pid, status='failed', error=tail(os.path.join(src, 'render.log')))
    now.update(stage='Writing the tracks')
    try:                                               # when each measure begins in these tracks (the page shows it as one plays)
        timeline = json.load(open(os.path.join(wavs, 'measures.json')))
    except (OSError, ValueError):
        timeline = None
    here = folder(pid)
    for f in load(pid).get('tracks', []):              # what was made before goes: these replace it
        if os.path.exists(os.path.join(here, f)):
            os.remove(os.path.join(here, f))
    for d in [x[1] for x in parts] + [SHARE]:
        if os.path.isdir(os.path.join(here, d)):
            shutil.rmtree(os.path.join(here, d))
    if os.path.exists(os.path.join(here, 'Credits.txt')):
        os.remove(os.path.join(here, 'Credits.txt'))
    names = {}                                         # the name of each mix -> the track file made from it
    for f in sorted(os.listdir(wavs)):
        if not f.endswith('.wav'):
            continue
        names[f[:-4]] = squeeze(os.path.join(wavs, f)) or f       # (with nothing here to make it small: the track as it was written)
    rank = lambda f: next((i for i, k in enumerate(ORDER) if f.rsplit('.', 1)[0].endswith(k)), 9)
    made = []
    if everyone:                                       # a folder for each part, whole in itself: its three tracks and the two all share
        for _, label, *_ in parts:
            os.makedirs(os.path.join(here, label), exist_ok=True)
            mine = [f for n, f in names.items() if n.endswith((' - balanced', ' - voices only', f' - {label} predominant', f' - {label} muted', f' - {label} alone'))]
            for f in sorted(mine, key=rank):
                shutil.copy(os.path.join(wavs, f), os.path.join(here, label, f)); made.append(f'{label}/{f}')
            if real:
                open(os.path.join(here, label, 'Credits.txt'), 'w').write(CREDIT)
    else:
        for f in sorted(names.values(), key=rank):
            shutil.move(os.path.join(wavs, f), os.path.join(here, f)); made.append(f)
        if real:
            open(os.path.join(here, 'Credits.txt'), 'w').write(CREDIT)
    shutil.rmtree(wavs, ignore_errors=True)
    save(pid, status='ready', tracks=made, made=dict(part=opt['part'], voices='real' if real else 'built-in', singers=singers, when=time.time()), error=None, note=None,
         timeline=timeline)
    settings(part=opt['part'], voices='real' if real else 'built-in', singers=singers)


def squeeze(wav):
    """A track as it was written (a .wav file, large) -> a small one beside it, made with what this computer has: the
    Mac's own converter, or ffmpeg (-> .m4a), or the MP3 encoder the installer adds on Windows and Linux (-> .mp3).
    -> the small file's name, or None where there is nothing to make one with."""
    stem = wav[:-4]
    if os.environ.get('PALARE_PLAIN_TRACKS'):          # (for tests, which listen to the track as it was written)
        return None
    for cmd in (['afconvert', '-f', 'm4af', '-d', 'aac', '-b', '192000', wav, stem + '.m4a'],
                ['ffmpeg', '-y', '-loglevel', 'error', '-i', wav, '-c:a', 'aac', '-b:a', '192k', stem + '.m4a']):
        if shutil.which(cmd[0]) and not subprocess.run(cmd, capture_output=True, **hidden()).returncode:
            return os.path.basename(stem + '.m4a')
    try:
        import lameenc, wave
        with wave.open(wav) as w:
            enc = lameenc.Encoder()
            enc.set_bit_rate(192); enc.set_in_sample_rate(w.getframerate()); enc.set_channels(w.getnchannels()); enc.set_quality(2)
            getattr(enc, 'silence', lambda: None)()
            data = bytes(enc.encode(w.readframes(w.getnframes()))) + bytes(enc.flush())
        with open(stem + '.mp3', 'wb') as o:
            o.write(data)
        return os.path.basename(stem + '.mp3')
    except Exception:
        return None


def share(pid):
    """One zip file for each part, in a folder of their own: what to send to each section.  -> that folder."""
    import zipfile
    d, here = load(pid), folder(pid)
    if (d.get('made') or {}).get('part') != 'all':
        return here
    out = os.path.join(here, SHARE)
    os.makedirs(out, exist_ok=True)
    groups = {}
    for t in d.get('tracks', []):
        label, _, f = t.partition('/')
        groups.setdefault(label, []).append(f)
    title = re.sub(r'[^\w \-,.()\']', '', d.get('title') or pid).strip(' .') or pid
    for label, files in groups.items():
        z = os.path.join(out, f'{title} - {label}.zip')
        newest = max(os.path.getmtime(os.path.join(here, label, f)) for f in files)
        if os.path.exists(z) and os.path.getmtime(z) >= newest:
            continue
        with zipfile.ZipFile(z + '.part', 'w', zipfile.ZIP_STORED) as zf:      # (the tracks are compressed already)
            for f in files + (['Credits.txt'] if os.path.exists(os.path.join(here, label, 'Credits.txt')) else []):
                zf.write(os.path.join(here, label, f), f'{title} - {label}/{f}')
        os.replace(z + '.part', z)
    return out


def do_check(opt):
    """The short test of what this computer can do; with real voices installed, of how fast they are here too."""
    checking.update(running=True)
    logfile = os.path.join(LIB, '.computer.log')
    got = {}

    def follow(line):
        if line.startswith('result: '):
            got.update(json.loads(line[8:]))
    try:
        code = run([PY, '-m', 'choral.check'] + (['--voices'] if opt.get('voices') else []), logfile, follow)
        if not code and got:
            json.dump(got, open(os.path.join(LIB, '.computer.json'), 'w'))
    finally:
        checking.update(running=False)


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
    code = run([PY, '-m', 'choral.setup_voices'], logfile, follow)
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
                if voices_state()['ready']:            # now that they are here: how fast are they on this machine?
                    do_check({'voices': True})
            elif kind == 'check':
                do_check(opt)
            elif not os.path.exists(info_file(pid)):
                pass                                   # removed while it waited
            elif kind == 'read':
                do_read(pid, opt.get('again'))
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


def find_measures():
    """Tracks made by an earlier version of the program do not know where their measures begin.  For a piece whose
    score has not been touched since its tracks were made, that can be worked out again - the tracks were timed by
    the score's tempo marks and nothing else - without making them again (which, with real voices, is an hour)."""
    for d in pieces():
        if d.get('tracks') and d.get('read') and not d.get('timeline') and not d.get('stale'):
            try:
                r = subprocess.run([PY, '-m', 'choral', score_of(d['id']), '--measures'], cwd=ROOT, capture_output=True, text=True, errors='replace',
                                   timeout=180, env=dict(os.environ, PYTHONUNBUFFERED='1'), **hidden())
                line = next(l for l in r.stdout.splitlines() if l.startswith('measures: '))
                if os.path.exists(info_file(d['id'])):
                    save(d['id'], timeline=json.loads(line[len('measures: '):]))
            except Exception:
                pass                                   # no harm done: the page simply does not show the measure for this one


def stop_now():
    p = now.get('proc')
    if p and p.poll() is None:
        now['stopped'] = True
        if os.name == 'nt':                            # Windows has no polite way to ask: end it and everything it started
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True, **hidden())
        else:
            p.send_signal(signal.SIGTERM)


# ---- what the page asks

def state():
    with lock:
        job = {k: now.get(k) for k in ('id', 'kind', 'stage', 'progress', 'eta')} if now else None
        v = version()
        return dict(pieces=pieces(), job=job, waiting=list(waiting), voices=voices_state(), library=LIB, computer=computer(), checking=checking['running'],
                    boot=BOOT, mac=sys.platform == 'darwin', update=dict(can=bool(v), installed=(v or {}).get('installed'), version=((v or {}).get('version') or '')[:7], line=line(),
                                           count=newer['count'], news=newer['news'], checked=newer['checked'], error=newer['error'], updating=newer['updating']),
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
        if q.get('part') not in [p[0] for p in d['read']['parts']] + (['all'] if len(d['read']['parts']) > 1 else []):
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
        return {} if show_path(folder(pid)) else {'where': folder(pid)}
    if path.startswith('/api/fix/'):                   # "Fix a note or a word": one measure, shown and changed (choral/fix.py)
        from . import fix
        with lock:
            if now.get('id') == pid or pid in waiting:
                raise ValueError('Wait until this piece has finished, then fix it.')
        sf, n = score_of(pid), int(q.get('n') or 0)
        try:
            if path == '/api/fix/open':
                o = fix.outline(sf)
                return dict(outline=o, measure=fix.measure(sf, n if n in o['measures'] else o['measures'][0], unsure(pid)), unsure=unsure(pid))
            if path == '/api/fix/measure':
                return dict(measure=fix.measure(sf, n, unsure(pid)))
            if path == '/api/fix/right':                  # "it is right as it is": that doubt is not raised again
                save(pid, checked=sorted(set(load(pid).get('checked', [])) | {q.get('key', '')}))
                return dict(measure=fix.measure(sf, n, unsure(pid)), unsure=unsure(pid))
            if path == '/api/fix/move':
                fix.move(sf, n, int(q['line']), int(q['t']), int(q['k']), int(q.get('step') or 0), q.get('sign'))
            elif path == '/api/fix/word':
                fix.word(sf, n, int(q['line']), int(q['t']), q.get('text', ''))
            elif path == '/api/fix/spoken':
                fix.spoken(sf, n, int(q['line']), int(q['t']), bool(q.get('on')))
            elif path == '/api/fix/find':
                return dict(found=fix.find(sf, q.get('text', '')))
            elif path == '/api/fix/undo':
                fix.undo_all(sf)
                save(pid, checked=[])
                o = fix.outline(sf)
                n = n if n in o['measures'] else o['measures'][0]
            else:
                raise KeyError(path)
        except fix.Refused as e:
            raise ValueError(str(e))
        return dict(measure=fix.measure(sf, n, unsure(pid)), changed=fix.outline(sf)['changed'], unsure=unsure(pid))
    if path == '/api/share':
        where = share(pid)
        return {} if show_path(where) else {'where': where}
    if path == '/api/score':
        return {} if show_path(score_of(pid), as_text=True) else {'where': score_of(pid)}
    if path == '/api/readagain':                       # a piece that could not be read: try once more (a newer reader may manage it)
        with lock:
            if now.get('id') == pid or pid in waiting:
                raise ValueError('This piece is busy.')
            waiting.append(pid)
        save(pid, status='reading', error=None)
        jobs.put(('read', pid, {'again': True}))
        return {}
    if path == '/api/reread':                          # after the score was corrected by hand: look at it again
        save(pid, read=what_was_read(pid))
        return {}
    if path == '/api/remove':
        with lock:
            if now.get('id') == pid or pid in waiting:
                raise ValueError('Stop it first.')
            trash = os.path.join(os.path.expanduser('~'), '.Trash')
            if sys.platform == 'darwin' and os.path.isdir(trash):       # to the Trash, where it can be got back
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
    if path == '/api/update/look':
        look_for_newer()
        return {}
    if path == '/api/update':
        update_now()
        return {}
    if path == '/api/report':
        return dict(name=f'Palare Piano report {time.strftime("%Y-%m-%d %H%M")}.txt', text=report())
    if path == '/api/check':
        if not checking['running']:
            checking.update(running=True)
            jobs.put(('check', None, {'voices': voices_state()['ready']}))
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
                if name not in load(pid).get('tracks', []):        # only what this piece's tracks are: nothing else on the disk
                    raise ValueError(name)
                f = os.path.join(folder(pid), name)
                size = os.path.getsize(f)
            except (ValueError, OSError):
                return self.send(404, {'error': 'no such track'})
            kind = {'.m4a': 'audio/mp4', '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.txt': 'text/plain; charset=utf-8'}.get(os.path.splitext(f)[1].lower(), 'application/octet-stream')
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
    utf8()
    if sys.stdout is None:                             # started without a window (Windows): what it says is kept in a file
        sys.stdout = sys.stderr = open(os.path.join(os.path.dirname(ROOT), 'app.log'), 'a', buffering=1, encoding='utf-8')
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
    v = (version() or {}).get('version')
    newer_here = bool(v) and settings().get('version') != v                  # this is the first start of this version here
    if v:
        settings(version=v)
    with lock:                                         # whatever was under way when it was last closed did not finish
        for d in pieces():
            if d.get('status') in ('reading',):
                waiting.append(d['id']); jobs.put(('read', d['id'], {}))
            elif d.get('status') == 'unreadable' and newer_here:        # the newer reader may manage what the older could not
                waiting.append(d['id']); save(d['id'], status='reading', error=None); jobs.put(('read', d['id'], {'again': True}))
            elif d.get('status') in ('queued', 'rendering'):
                save(d['id'], status='ready' if d.get('tracks') else 'read', note='This was interrupted. What was finished is kept: starting again goes on from there.')
            elif d.get('status') == 'read' and d.get('tracks'):        # (an earlier version hid a piece's tracks when a second making of them was stopped)
                save(d['id'], status='ready')
    if computer() is None:                             # first time here: see what this computer can do
        checking.update(running=True)
        jobs.put(('check', None, {'voices': voices_state()['ready']}))
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=keep_looking, daemon=True).start()
    threading.Thread(target=find_measures, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: (stop_now(), os._exit(0)))
    print(f'Palare Piano is at http://127.0.0.1:{port}/  (pieces are kept in {LIB})', flush=True)
    show(f'http://127.0.0.1:{port}/')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_now()


if __name__ == '__main__':
    main()
