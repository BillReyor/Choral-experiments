"""What can this computer do?  A short test, and from it a plain answer for each thing the program does.

    python -m choral.check [--voices]        prints  result: {...}  (one line of JSON)

The page runs it when it is first opened, and again when real voices have been added (choral/app.py).  It looks at
the machine - its chip, its memory, its free disk - sings a few seconds with one built-in voice to see how fast one
processor is, and with --voices converts a few seconds with the voice model to see how fast that is.  From those it
says, for a piece of three minutes: will this work here, and about how long will it take.

What the answers rest on.  Everything was measured on one machine, an Apple M5 Max with 18 processors and 128 GB:

  built-in voices, a piece of 3 minutes 24 seconds, twelve singers to a part, by how many are sung at once:
      10 at once: 61 s, 7.2 GB at the peak;  4: 80 s, 4.5 GB;  2: 109 s, 3.6 GB
  so about 127 processor-seconds of singing, shared among those singing at once, and 48 s of work that one processor
  does alone (mixing, the hall, writing); and about 3 GB however it is done, plus half a gigabyte for each singer
  sung at once.  The voice model: four times as fast as the singing lasts, and 9 GB of memory at its peak.

A slower processor is taken to be slower at all of it in the same proportion as it is at the few seconds sung here.
No smaller machine has been tried: the answers for one are reckoned from these figures, not seen."""
import json, os, platform, shutil, subprocess, sys, tempfile, time, wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF_SING = 0.22            # seconds the machine above takes for the test below (its fastest of three)
REF_PIECE = 204.           # the measured piece: seconds of music, 48 singers
SUNG, ALONE = 127., 48.    # on the machine above: processor-seconds of singing, and seconds of work done by one processor
MODEL_GB, MODEL_DISK_GB = 9., 6.


def sysctl(name):
    try:
        return subprocess.run(['sysctl', '-n', name], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ''


def machine():
    mem = 0.
    try:
        mem = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2 ** 30
    except (ValueError, OSError):
        pass
    chip = sysctl('machdep.cpu.brand_string') or platform.processor() or platform.machine()
    return dict(chip=chip, apple=sys.platform == 'darwin' and platform.machine() == 'arm64', memory=round(mem), cores=os.cpu_count() or 1,
                disk=round(shutil.disk_usage(os.path.expanduser('~')).free / 2 ** 30), system=platform.mac_ver()[0] or platform.platform())


def at_once(memory, cores):
    """How many singers to sing at the same time on a machine with this much memory: each takes about half a gigabyte."""
    by_memory = 2 if memory <= 8 else 4 if memory <= 12 else 6 if memory <= 18 else 10
    return max(1, min(10, cores, by_memory))


def sing_once():
    """Seconds this machine takes to sing the demo's baritone line with one built-in voice (the fastest of three)."""
    import contextlib, io
    import numpy as np
    from . import render as R, score as scoremod, voice
    with contextlib.redirect_stdout(io.StringIO()):
        sc = scoremod.load(os.path.join(ROOT, 'scores', 'demo_shenandoah.score'))
        clock = R.clock_for(sc, None)
        total = float(np.interp(sc.beats, *clock)) + 4.0
        notes = R.engine_notes(sc, 'BR')
        best = 1e9
        for _ in range(3):
            t0 = time.perf_counter()
            voice.render_singer(('BR', 4, notes, (*clock, total)))
            best = min(best, time.perf_counter() - t0)
    return best


def model_rate():
    """Seconds of singing the voice model converts in a second here, or None if it is not installed or does not run."""
    from . import revoice
    cmd, voices = revoice.command(), os.path.join(ROOT, '.svc', 'voices')
    if cmd is None or not os.path.isdir(voices):
        return None
    refs = sorted(os.path.join(voices, f) for f in os.listdir(voices) if f.endswith('.wav'))
    if len(refs) < 2:
        return None
    import re
    with tempfile.TemporaryDirectory() as tmp:
        with wave.open(refs[0]) as w:
            rate, data = w.getframerate(), w.readframes(w.getframerate() * 6)
            src = os.path.join(tmp, 'try.wav')
            with wave.open(src, 'wb') as o:
                o.setnchannels(w.getnchannels()); o.setsampwidth(w.getsampwidth()); o.setframerate(rate); o.writeframes(data)
        jobs = [dict(source=src, reference=refs[-1], out=os.path.join(tmp, f'out{i}.wav'), seed=i) for i in range(4)]
        json.dump(jobs, open(os.path.join(tmp, 'jobs.json'), 'w'))
        r = subprocess.run(cmd + [os.path.join(tmp, 'jobs.json')], capture_output=True, text=True, env=dict(os.environ, EVERY='1'))
        said = re.findall(r're-voiced (\d+) of \d+ stretches: ([\d.]+) s of singing in ([\d.]+) s', r.stdout)
    if r.returncode or len(said) < 4:
        return None
    (_, s1, t1), (_, s4, t4) = said[0], said[-1]                # the first stretch pays for getting the chip ready: leave it out
    took = float(t4) - float(t1)
    return (float(s4) - float(s1)) / took if took > .2 else None


def minutes(seconds):
    m = seconds / 60
    return 'about a minute' if m < 1.5 else f'about {m:.0f} minutes' if m < 90 else f'about {m / 60:.1f} hours'.replace('.0 hours', ' hours')


def verdicts(mc, slow, rate, voices):
    """For each thing the program does: {what, level: yes | slow | no, time, why} - for a piece of three minutes."""
    w = at_once(mc['memory'], mc['cores'])
    piece = 180 / REF_PIECE

    def quick(singers=12):
        return (SUNG * singers / 12 / w + ALONE * (.5 + .5 * singers / 12)) * slow * piece

    def real(singers):
        if not rate:
            return None
        singing = 180 * .8 * 4 * singers
        return singing / rate + singing * .04 * slow + quick(singers)
    out = [dict(key='read', what='Reading sheet music', detail='PDFs from notation software, and scans', level='yes', secs=None, time='', why='')]
    q = quick()
    tight = mc['memory'] and mc['memory'] < 8
    out.append(dict(key='quick', what='Quick listen', detail='built-in voices', level='slow' if tight or q > 900 else 'yes', secs=round(q), time=minutes(q),
                    why='This computer has little memory, so long pieces may be slow.' if tight else ''))
    for key, name, detail, singers in (('small', 'Real voices, small choir', 'four singers to a part', 4), ('full', 'Real voices, full choir', 'twelve singers to a part', 12)):
        t = real(singers)
        if not mc['apple']:
            row = dict(level='no', why='Real voices need a Mac with an Apple chip (M1 or later).')
        elif mc['memory'] and mc['memory'] < 12:
            row = dict(level='no', why=f"Real voices need about {MODEL_GB:.0f} GB of memory for themselves, and this Mac has {mc['memory']} GB.")
        elif not voices and mc['disk'] < MODEL_DISK_GB:
            row = dict(level='no', why=f"Adding real voices needs about {MODEL_DISK_GB:.0f} GB of free disk, and this Mac has {mc['disk']} GB free.")
        elif t is None:
            row = dict(level='yes', why='Should work. How long it takes is measured once real voices are added.' if not voices else
                       'Real voices are installed, but the speed test did not finish.')
        else:
            row = dict(level='slow' if t > 3600 or mc['memory'] < 16 else 'yes',
                       why='It will work, but this Mac has little memory to spare for it: close other apps first.' if mc['memory'] < 16 else
                       'It will work; expect a long wait.' if t > 3600 else '')
        if row['level'] == 'no':
            t = None
        out.append(dict(key=key, what=name, detail=detail, secs=round(t) if t else None, time=minutes(t) if t else '', **row))
    return out, w


def main():
    voices = '--voices' in sys.argv
    mc = machine()
    took = sing_once()
    slow = took / REF_SING
    from . import revoice
    have = revoice.command() is not None
    rate = model_rate() if voices and have else None
    rows, w = verdicts(mc, slow, rate, have)
    print('result: ' + json.dumps(dict(machine=mc, sing=round(took, 3), slow=round(slow, 2), rate=round(rate, 2) if rate else None,
                                       at_once=w, rows=rows, when=time.time(), voices=have)), flush=True)


if __name__ == '__main__':
    main()
