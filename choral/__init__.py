"""Palare Piano: sheet music in, a sung rendering out."""
import os, subprocess, sys


def utf8():
    """On Windows a Python program reads and writes text in the system's old code page unless told otherwise, and a
    score has curly apostrophes in its words.  Called first thing by every program here: if this is Windows and
    Python is not in its UTF-8 mode, the program is started again in it (and so is everything it starts)."""
    if os.name == 'nt':
        os.environ['PYTHONUTF8'] = '1'
        if not sys.flags.utf8_mode:
            raise SystemExit(subprocess.call([sys.executable] + sys.orig_argv[1:]))


def helper():
    """What each helper process does first (the initializer of every Pool here).  On Linux a helper is a copy of the
    program that started it, and so answers a request to stop the way that program does (__main__): politely, when it
    next gets round to it.  A helper waiting for work that will never come does not get round to it, and the program
    then waits for that helper for ever, at its very end: seen in one run in twelve on Linux.  A helper just stops."""
    import signal
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def hidden():
    """On Windows, a program started by one that has no window of its own opens a black window unless told not to."""
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def show(path, as_text=False):
    """Open a folder, or a file, the way this computer opens things; as_text: in its plain text editor.
    -> whether it could (a computer with no desktop has nothing to open it with; PALARE_NO_BROWSER, for tests, says not to)."""
    if os.environ.get('PALARE_NO_BROWSER'):
        return False
    try:
        if sys.platform == 'darwin':
            return not subprocess.run(['open', '-e', path] if as_text else ['open', path]).returncode
        if os.name == 'nt':
            subprocess.Popen(['notepad', path]) if as_text else os.startfile(path)
            return True
        return not subprocess.run(['xdg-open', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except OSError:
        return False
