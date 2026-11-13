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
