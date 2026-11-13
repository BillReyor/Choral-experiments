# Installing by hand, and the command line

The [README](../README.md) installs Palare Piano in one step - on a Mac, on Windows or on Linux - and
runs it from a page in the browser. This is the other way: for Intel Macs, and for anyone who wants
the commands. Everything the page does is one of these commands underneath.

## Quickstart

```
pip install -r requirements.txt
python -m choral scores/demo_shenandoah.score --part bass
```

This writes into `out/`: the full rendering (*balanced*), *voices only*, and for the part named
*Bass predominant*, *Bass muted* (everyone else, to sing against) and *Bass alone*.

With your own music:

```
python -m choral MUSIC.pdf --part baritone                           # sung with the built-in piano
python -m choral MUSIC.pdf --part baritone --accompaniment ACC.mp3   # sung over a recorded accompaniment
python -m choral MUSIC.pdf --part baritone --accompaniment ACC.mp3 \
       --balanced BALANCED.mp3 --predominant BARITONE_PREDOMINANT.mp3    # and learn from practice tracks
```

- **MUSIC** is a PDF (exported from notation software, or a scan) or a plain-text score
  ([docs/score-format.md](score-format.md)). A PDF is read once into a `.score` file beside it;
  correct a misread note or word there and the next run uses the correction.
- **--part** takes `tenor1`, `tenor2`, `baritone`, `bass`, `solo`, or several with commas.
- **--accompaniment** lines the voices up with a recording instead of using the built-in piano.
- **--balanced / --predominant / --muted** are practice tracks of the same piece, if you have them.
  They are only listened to - for the timing, the room, how the notes are shaped - and nothing of
  them ends up in the output. The run then reports how well it fits them: the share of the real
  singer's notes that are on pitch where the timing puts them, how closely the voices sit on the
  accompaniment, and where the simulated voice differs most from the real one.
- **--tune** lets a speech recognizer choose how close the microphones are (needs whisper.cpp).
- **--voice VOICE.wav** (or several, or a folder of them) gives the singers the sound of real
  voices: 15-30 seconds each of someone singing alone - you, or people who have agreed to it.
  Several voices are seated like a choir, the low ones in the low parts.
  `tools/vocalset_voices.py` fetches ten men's voices from a public research collection to start
  with. This is the one thing here that is not done in code: an outside voice-conversion model,
  installed separately ([docs/how-it-works.md](how-it-works.md)), re-voices each simulated
  singer, keeping the notes, words and timing the engine sang. It is slow - a three-minute piece
  takes 15 to 50 minutes, by the size of the choir - but only the first time for a piece: after
  a correction to the score, only the phrases it touches are converted again.

## Install

| For | You need |
|---|---|
| Everything above from a `.score` file or a PDF exported from notation software (MuseScore, Dorico, Sibelius, Finale): read exactly, in seconds | Python 3.10+, `pip install -r requirements.txt` |
| Scans and photocopies | the [homr](https://github.com/liebharc/homr) recognition engine beside the project: `python3.12 -m venv .venv-omr && .venv-omr/bin/pip install "homr[cpu]"` (AGPL; it is called as a separate program) |
| Words from a scan | nothing on macOS (with the Xcode command-line tools); elsewhere [Tesseract](https://tesseract-ocr.github.io/). A PDF that carries its text needs neither. |
| Audio other than WAV | `ffmpeg` (or macOS's `afconvert`); the page also saves its tracks as MP3 with `pip install -r install/tracks.txt` |
| `--voice` | `python -m choral.setup_voices`, which installs the voice model, fetches the voices and tries them once (about 4 GB; it needs a C compiler for one package, pyworld). It has been tried on Apple-chip Macs only; [how-it-works.md](how-it-works.md) says what it sets up, for doing it by hand elsewhere |
| `--tune`, and the listening checks in `tools/` | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) and a model, named in `WHISPER_MODEL` |


## The page, by hand

```
python -m choral.app
```

starts the page the installer's app opens (`choral/app.py`): a web server only this computer can
reach, which keeps pieces in `~/Music/Palare Piano` (`PALARE_LIBRARY` names another folder).

## What the installers do

`install.sh` (Mac, Linux) and `install.ps1` (Windows) put everything in one folder: [uv](https://docs.astral.sh/uv/),
a Python of its own that uv fetches, this program, and two sets of packages at the versions they
were tested with (`install/app.txt` for the program, `install/scan-reader.txt` for homr; on Windows
and Linux also `install/tracks.txt`, the MP3 encoder). They leave one thing to open it with, which
runs `python -m choral.app`, and a note of which version was installed (`version.json`), which is
what the page's update button goes by. They ask for no password and touch nothing else.

| | the program's folder | what opens it |
|---|---|---|
| Mac | `~/Library/Application Support/Palare-Piano` | `~/Applications/Palare Piano.app` |
| Linux | `~/.local/share/Palare-Piano` | `~/.local/share/applications/palare-piano.desktop` |
| Windows | `%LOCALAPPDATA%\Palare-Piano` | a shortcut in the Start menu and on the Desktop |

Real voices are added later from the page, on a Mac, by `python -m choral.setup_voices`
(`install/voice-model.txt`).

## Testing an install

```
python tools/try_install.py --part-all
```

opens an installed copy by what the installer left to open it with and does what a singer does, by
the page's own requests: adds the demo piece, moves a note and puts it back, makes the tracks,
fetches them, makes the files to share, waits for the computer check, removes the piece, quits.
`.github/workflows/install.yml` runs the installer and this on Linux, Windows and a Mac at every
change. The repository holds no sheet music but the demo piece, so reading a PDF is not part of it.

## Giving out a new version

Work is pushed to the branch `main`. The install lines and the page's update button take the newest
version on the branch `stable`, so a change reaches people only when `stable` is moved on to it:

```
sh tools/release.sh --look      # what people would get
sh tools/release.sh             # test it on the three systems if that has not been done, then move stable
```

It moves `stable` only to a version the test above has passed, at exactly that version.
`PALARE_CHANNEL=main` in front of the install line installs the work in progress instead, and that
copy then follows `main`.
