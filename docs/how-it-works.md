# How it works

## The files

| Path | What it is |
|---|---|
| `choral/voice.py` | The voice engine. Each singer is simulated: vocal-fold pulses one at a time, breath noise, a moving vocal tract, and a "brain" that hunts for pitch, enters late or early, and drifts with its section. |
| `choral/score.py`, `choral/lyrics.py` | Reader for a plain-text score format that mirrors the printed page, and the sung-text-to-phoneme step. See [docs/score-format.md](score-format.md). |
| `choral/latin.py` | Church Latin by rule, syllable by syllable, with its own five vowels fitted to real singers. |
| `choral/piano.py`, `choral/render.py` | Piano, stage (48 singers on risers in front of a stereo pair, section leaders on close mics), hall, mix. Every section is kept on its own stem, so one part can be brought forward, left out, or heard alone. |
| `choral/__main__.py` | The program: sheet music in, audio out (see below). |
| `choral/presets.py` | Estimates what differs from piece to piece - tempo and its bends, hall, how close the microphones are, how loud the accompaniment sits - from practice tracks, from a speech recognizer, or from the score alone. |
| `choral/timing.py` | Finds where every beat of the score falls in the recordings: a first, steady fit from one isolated voice, then a follower that tracks the written piano attacks through the accompaniment track and every isolated voice's notes together (position and tempo both), plus the checks that say how well the result fits - singers on pitch, voices against the accompaniment. |
| `choral/reference.py` | Takes a set of practice tracks apart (balanced, accompaniment, "part predominant" or "part muted") into voices alone, accompaniment alone and one part alone, and says how cleanly they separated. |
| `choral/hear.py` | The speech recognizer used as a stand-in for ears: English directly; other languages through the multilingual model, told the piece's vocabulary. |
| `tools/scan2score.py` | Reads a score from page images (a scan, or any PDF the shape reader cannot read): cuts each page into systems, has the open-source recognition engine `homr` read the notes - a system whose reading does not match the staves on the page is read again in parts - decides which staves are voices and which the piano, splits two voices sharing a staff, finds the barlines, follows repeats, D.S. and codas, and puts the words under the notes: from the PDF's own text if it has one, otherwise by text recognition (macOS's, or Tesseract). |
| `tools/vector2score.py` | Reads the notes of a notation-software PDF exactly, from the symbols it is drawn with: any PDF in a standard (SMuFL) music font - Bravura, Leland and the like, as exported by MuseScore, Dorico, Sibelius and recent Finale. Staff lines give the pitch of each notehead; stems make chords and tell two voices on a staff apart; beams, flags, dots and tuplet numbers give the note values; accidentals last to the barline; curves are ties or slurs. It checks itself (do the measures add up?) and steps aside if they do not. |
| `tools/pdf2score.py` | The same idea for older Finale exports in the Maestro font. |
| `tools/fit.py` | Fits the piano, or the voice, to a recording by rendering on the recording's own timing and comparing mel spectrograms, one setting at a time, with held-out passages as the test. |
| `tools/listen.py` | Uses a speech recognizer as ears: transcribes a render and reports how many of the score's words came through. |
| `tools/check_part.py`, `tools/check_mix.py` | Check a transcription against a recording: pitch-track one isolated part, or test every written note against a recording of all voices. |
| `tools/calibrate.py` | Fits the engine's tone to a recording of a real singer on the same notes. |
| `tools/tone.py` | Tone, harmonic by harmonic: on every held vowel, compares the strength of each harmonic in a real solo recording and in the model. Only harmonic peaks count, so room reverb does not. |
| `tools/compare.py`, `choral/compare.py` | Spectral comparison: one real singer alone beside the same part sung by simulated singers on the recording's timing, measured the same way note by note (tone in 16 bands, loudness through each note, colour through the note, entries by consonant type, releases, loud against soft, steadiness) - the simulated ones first placed in a room matched to the recording's, so that like is compared with like. Lists what differs, largest first; given several singers, lists what they have in common. `python -m choral` writes this report on its own whenever practice tracks let it isolate a real voice. |
| `tools/realism.py` | Scorecard: renders one simulated singer on a part and measures it beside a real singer's isolated recording of the same part — pitch glides and scoops, attacks, how notes are held, harmonics versus noise, consonant strength. |
| `experiments/` | The stand-alone experiments that led here (a vowel-only "Shenandoah", and an original pop number in three engine generations). |
| `scores/demo_shenandoah.score` | A short public-domain example. |


## Reading a score from a PDF

A PDF exported from notation software is not a picture: every notehead is a character of a music
font at an exact place. Where that font is a standard one (`tools/vector2score.py`) or Finale's
older Maestro (`tools/pdf2score.py`), the notes are read off exactly and at once, and the words
come from the PDF's own text. Any other PDF - a scan, a photocopy - has its pages rendered and
recognized (`tools/scan2score.py`, about half a minute a page). Either way a `.score` file is
written beside the PDF and the program sings from that, so a misread note or word can be corrected
by hand and the next run uses the correction.

Scans need a music-recognition engine. This project uses [homr](https://github.com/liebharc/homr)
(AGPL-licensed, so it is installed beside the project and called as a separate program, not
copied in):

```
python3.12 -m venv .venv-omr && .venv-omr/bin/pip install "homr[cpu]"
```

It needs Python 3.11-3.14 and downloads its models the first time it runs. Words are read with
macOS's built-in text recognition (`tools/ocr.swift`, compiled on first use); without it the
notes come out with no words. What is and is not reliable yet is in the status section below.


Where the words come from: the PDF's own text when it has one (exact; nothing to install);
otherwise text recognition - macOS's built-in one, or [Tesseract](https://tesseract-ocr.github.io/)
on Linux and Windows (`SCAN_OCR=tesseract` forces it; it gets fewer syllables right, see the
journal).

## What gets estimated for each piece

A piece's settings are worked out once and kept beside the score as `NAME.preset.json`.

| Setting | From practice tracks | Without them |
|---|---|---|
| Tempo, the first beat, ritardandos, holds | Measured: the written piano attacks are followed through the accompaniment track and every isolated voice's notes through its own track, together, so the voices stay with the accompaniment; the run reports how well both fit | The score's `tempo:` |
| Hall (amount and length) | Matched to how the recorded voices die away after each release | A rule from how short the quick syllables are |
| Accompaniment level | Measured from the balanced mix | A fixed default |
| Note shape (sustained, fading like a bell, or swelling into each note) | Measured on one real singer: how fast held notes fade, and how far soft ones swell in | Sustained; soft notes in slow music swell in by a rule |
| How close the microphones are | The recognizer walks a ladder from dry-and-close to wet-and-blended and keeps the most blended setting that does not cost words (`--tune`) | The same rule |

On the three test pieces the track separation recovers, with no hand-tuning, what had earlier
been worked out by hand: the accompaniment's gain in each mix, the other voices' level in the
"predominant" mix, the first beat to within a few hundredths of a second and the tempo to 0.01
bpm. It also reports when a set of tracks is *not* one recording at different levels (piece 2),
and then uses the accompaniment for timing only.

`python -m choral.render SCORE OUT.wav` is still there as the plain renderer.

The workflow for a new piece of sheet music:

1. **Transcribe** the pages into the score format (or let `tools/pdf2score.py` do it). Every line
   has to add up to its measure, so most rhythm misreadings are caught immediately. For a scan,
   the words can be taken from the page by text recognition instead of retyped (`lyricsfile:`).
2. **Check** it, if a recording exists: `tools/check_part.py` against an isolated part,
   `tools/check_mix.py` against all voices.
3. **Run** `python -m choral`, then **listen by proxy** with `tools/listen.py`, and compare with
   the same tool run on a real recording.

