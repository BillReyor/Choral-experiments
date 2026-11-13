# Installing by hand, and the command line

The [README](../README.md) installs Palare Piano on a Mac in one step and runs it from a page in the
browser. This is the other way: for Linux and Windows, for Intel Macs, and for anyone who wants the
commands. Everything the page does is one of these commands underneath.

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
| Audio other than WAV | `ffmpeg` (or macOS's `afconvert`) |
| `--voice` | `python -m choral.setup_voices`, which installs the voice model, fetches the voices and tries them once (about 4 GB; it needs a C compiler for one package, pyworld). It has been tried on Apple-chip Macs only; [how-it-works.md](how-it-works.md) says what it sets up, for doing it by hand elsewhere |
| `--tune`, and the listening checks in `tools/` | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) and a model, named in `WHISPER_MODEL` |


## The page, by hand

```
python -m choral.app
```

starts the page the installer's app opens (`choral/app.py`): a web server only this computer can
reach, which keeps pieces in `~/Music/Palare Piano` (`PALARE_LIBRARY` names another folder).

## What the Mac installer does

`install.sh` puts everything under `~/Library/Application Support/Palare-Piano`: [uv](https://docs.astral.sh/uv/),
a Python of its own that uv fetches, this program, and two sets of packages at the versions they
were tested with (`install/app.txt` for the program, `install/scan-reader.txt` for homr). It makes
`~/Applications/Palare Piano.app`, a launcher that runs `python -m choral.app`. It asks for no
password and touches nothing else. Real voices are added later from the page, by
`python -m choral.setup_voices` (`install/voice-model.txt`).
