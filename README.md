# Palare-Piano

Give it the sheet music of a piece for men's chorus and it sings it: a simulated choir (tenor 1,
tenor 2, baritone, bass) rendered entirely in code - no samples, no recordings - with the piano, or
over an accompaniment track you supply. Name your part and it also writes the rehearsal versions:
your part brought forward, your part left out, your part alone.

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
  ([docs/score-format.md](docs/score-format.md)). A PDF is read once into a `.score` file beside it;
  correct a misread note or word there and the next run uses the correction.
- **--part** takes `tenor1`, `tenor2`, `baritone`, `bass`, `solo`, or several with commas.
- **--accompaniment** lines the voices up with a recording instead of using the built-in piano.
- **--balanced / --predominant / --muted** are practice tracks of the same piece, if you have them.
  They are only listened to - for the timing, the room, how the notes are shaped - and nothing of
  them ends up in the output. The run then reports how well it fits them: the share of the real
  singer's notes that are on pitch where the timing puts them, how closely the voices sit on the
  accompaniment, and where the simulated voice differs most from the real one.
- **--tune** lets a speech recognizer choose how close the microphones are (needs whisper.cpp).

## Install

| For | You need |
|---|---|
| Everything above from a `.score` file or a PDF exported from notation software (MuseScore, Dorico, Sibelius, Finale): read exactly, in seconds | Python 3.10+, `pip install -r requirements.txt` |
| Scans and photocopies | the [homr](https://github.com/liebharc/homr) recognition engine beside the project: `python3.12 -m venv .venv-omr && .venv-omr/bin/pip install "homr[cpu]"` (AGPL; it is called as a separate program) |
| Words from a scan | nothing on macOS (with the Xcode command-line tools); elsewhere [Tesseract](https://tesseract-ocr.github.io/). A PDF that carries its text needs neither. |
| Audio other than WAV | `ffmpeg` (or macOS's `afconvert`) |
| `--tune`, and the listening checks in `tools/` | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) and a model, named in `WHISPER_MODEL` |

## Known limitations

- **It has never been listened to by its author.** Every judgement behind it is a measurement:
  against isolated recordings of real singers, against accompaniment tracks, and by a speech
  recognizer. Trust your ears over its reports.
- **Men's chorus only** (TTBB, TTB, soloist or trio over the choir), with piano or unaccompanied.
- **Reading scans is imperfect.** Typically 96-99% of the notes are right. About one syllable in
  ten is wrong or missing, more with Tesseract. (A PDF exported from current notation software is
  read exactly instead - but that reader has met only one such file so far, and does not yet
  follow "8va" lines or first and second endings. Exports from older software, whose fonts are
  stored under codes of their own, are recognized like scans.)
  Repeats, D.S. and codas are followed; first and second endings are not. Always look through the
  `.score` file it writes.
- **Words:** English (by dictionary) and church Latin (by rule). A word the dictionary does not
  have - a name, another language, a misread - is sung as it is spelled, by rough English rules:
  a near miss, which a `say:` line in the score corrects.
- **A full choir is harder to understand than a real one** on quick text, though single voices are
  about as clear as real singers.
- **Tone is the median of a dozen real singers.** A particular voice can differ from it by 10 dB
  in places.
- **Timing follows the accompaniment track** when there is one. Where the score as read does not
  match the recording (a misread ending, a cut), the run says so and the timing there is a guess.
- **Slow.** Half a minute a page to read a scan; about a minute to sing a three-minute piece.

## More

- [docs/how-it-works.md](docs/how-it-works.md) - what each file does, how PDFs are read, what is
  estimated for each piece and from what.
- [docs/score-format.md](docs/score-format.md) - the plain-text score format.
- [docs/journal.md](docs/journal.md) - the record of every test piece: what was measured, what was
  changed, and what did not work.
- `experiments/` - the stand-alone experiments that led here.

Audio, sheet music and transcriptions of copyrighted arrangements are never committed
(`.gitignore` blocks them, along with per-piece settings); renders go to `out/`.
