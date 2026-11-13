"""Add real voices: install the voice model, fetch the voices, and try them once.

    python -m choral.setup_voices

The page's "Add real voices" button runs this (choral/app.py); it can be run by hand as well.  Everything goes into
.svc/ beside the program:

    .svc/venv        the voice model's own Python packages (install/voice-model.txt; about 1.2 GB)
    .svc/seed-vc     Seed-VC (https://github.com/Plachtaa/seed-vc, GPL-3.0) at the commit this was tested with, and
                     the model's files, which it fetches from Hugging Face the first time it runs (2.3 GB)
    .svc/voices      ten men's voices from VocalSet (tools/vocalset_voices.py says whose, and under what licence)
    .svc/command.json   the command choral/revoice.py runs: that Python, choral/seedvc_driver.py, that folder

It says what it is doing in lines the page can follow - "step 2 of 6: ..." and "progress 40%" - and can be run again
after a failure: what is already there is kept."""
import json, os, shutil, subprocess, sys, tarfile, tempfile, threading, time, wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SVC = os.path.join(ROOT, '.svc')
SEEDVC = '51383efd921027683c89e5348211d93ff12ac2a8'         # the commit of Seed-VC the driver was written against
MODEL_KB = 2428080                                         # what the model's files come to, for the progress bar
STEPS = 6


def step(k, text):
    print(f'step {k} of {STEPS}: {text}', flush=True)


def sh(cmd, what, env=None):
    """Run a program, passing on what it says; stop with a plain sentence if it fails."""
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', env=env)
    if r.returncode:
        print(r.stdout[-3000:], flush=True)
        raise SystemExit(f'Could not finish: {what}.')
    return r.stdout


def fetch(url, dest):
    if shutil.which('curl'):                               # the system's own, with the system's certificates
        sh(['curl', '-fL', '--retry', '3', '-sS', '-o', dest, url], f'downloading {url}')
    else:
        import urllib.request
        urllib.request.urlretrieve(url, dest)


def size_kb(path):
    total = 0
    for d, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(d, f)).st_blocks // 2
            except OSError:
                pass
    return total


def main():
    os.makedirs(SVC, exist_ok=True)
    venv_py = os.path.join(SVC, 'venv', 'bin', 'python')
    repo = os.path.join(SVC, 'seed-vc')
    voices = os.path.join(SVC, 'voices')

    step(1, 'Checking this computer')
    if not (sys.platform == 'darwin' and os.uname().machine == 'arm64'):
        print('  ! real voices have only been tried on a Mac with an Apple chip; going on, but this may not work here', flush=True)
    free = shutil.disk_usage(SVC).free / 2 ** 30
    if free < 8 and not os.path.exists(os.path.join(repo, 'checkpoints')):
        raise SystemExit(f'Real voices need about 8 GB of free disk space to install; this disk has {free:.0f} GB free.')
    if sys.platform == 'darwin' and subprocess.run(['xcrun', '--find', 'clang'], capture_output=True).returncode:
        raise SystemExit("Apple's developer tools are missing. Open Terminal, type  xcode-select --install  and press Return, then try again.")

    step(2, "Installing the voice model's packages (about 1 GB)")
    if not os.path.exists(venv_py):
        sh([sys.executable, '-m', 'venv', os.path.join(SVC, 'venv')], 'making a place for the packages')
    sh([venv_py, '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', os.path.join(ROOT, 'install', 'voice-model.txt')], "installing the voice model's packages")

    step(3, 'Fetching the voice model program')
    if not os.path.exists(os.path.join(repo, 'inference.py')):
        with tempfile.TemporaryDirectory() as tmp:
            tgz = os.path.join(tmp, 'seed-vc.tar.gz')
            fetch(f'https://github.com/Plachtaa/seed-vc/archive/{SEEDVC}.tar.gz', tgz)
            with tarfile.open(tgz) as t:
                t.extractall(tmp, filter='data')
            src = os.path.join(tmp, f'seed-vc-{SEEDVC}')
            if os.path.exists(repo):
                shutil.rmtree(repo)
            shutil.move(src, repo)

    step(4, 'Fetching the voices (ten singers from VocalSet)')
    if not (os.path.isdir(voices) and len([f for f in os.listdir(voices) if f.endswith('.wav')]) >= 10):
        sh([sys.executable, os.path.join(ROOT, 'tools', 'vocalset_voices.py'), '-o', voices], 'fetching the voices')

    step(5, 'Building the part that steadies held notes')
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            import pyworld                                 # noqa: F401
    except Exception:
        sh([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '-q', 'pyworld==0.3.5', 'setuptools<81'], 'building pyworld')

    step(6, 'Downloading the voice model (2.3 GB) and trying it')
    cmd = [venv_py, os.path.join(HERE, 'seedvc_driver.py'), repo]
    json.dump(cmd, open(os.path.join(SVC, 'command.json.part'), 'w'), indent=1)
    with tempfile.TemporaryDirectory() as tmp:
        ref = sorted(os.path.join(voices, f) for f in os.listdir(voices) if f.endswith('.wav'))
        with wave.open(ref[0]) as w:                       # three seconds of one of the voices, sung again in another
            rate, data = w.getframerate(), w.readframes(w.getframerate() * 3)
            src = os.path.join(tmp, 'try.wav')
            with wave.open(src, 'wb') as o:
                o.setnchannels(w.getnchannels()); o.setsampwidth(w.getsampwidth()); o.setframerate(rate); o.writeframes(data)
        out = os.path.join(tmp, 'tried.wav')
        json.dump([dict(source=src, reference=ref[-1], out=out)], open(os.path.join(tmp, 'jobs.json'), 'w'))
        stop = threading.Event()

        def watch():                                       # the model's files arriving, as a share of the whole
            while not stop.wait(3):
                print('progress %d%%' % min(99, 100 * size_kb(os.path.join(repo, 'checkpoints')) // MODEL_KB), flush=True)
        threading.Thread(target=watch, daemon=True).start()
        try:
            sh(cmd + [os.path.join(tmp, 'jobs.json')], 'downloading and trying the voice model', env=dict(os.environ, HF_HUB_OFFLINE='0'))
        finally:
            stop.set()
        with wave.open(out) as w:
            import numpy as np
            x = np.frombuffer(w.readframes(w.getnframes()), '<i2') / 32768.
        if len(x) < rate or float(np.sqrt(np.mean(x ** 2))) < 1e-3:
            raise SystemExit('The voice model ran but what it sang is silent.')
    os.replace(os.path.join(SVC, 'command.json.part'), os.path.join(SVC, 'command.json'))
    print('progress 100%', flush=True)
    print('Real voices are ready.', flush=True)


if __name__ == '__main__':
    t0 = time.time()
    main()
    print('done in %.0f s' % (time.time() - t0), flush=True)
