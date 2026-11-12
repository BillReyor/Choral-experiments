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
- **--voice VOICE.wav** (or several, or a folder of them) gives the singers the sound of real
  voices: 15-30 seconds each of someone singing alone - you, or people who have agreed to it.
  Several voices are seated like a choir, the low ones in the low parts.
  `tools/vocalset_voices.py` fetches ten men's voices from a public research collection to start
  with. This is the one thing here that is not done in code: an outside voice-conversion model,
  installed separately ([docs/how-it-works.md](docs/how-it-works.md)), re-voices each simulated
  singer, keeping the notes, words and timing the engine sang. It is slow - a three-minute piece
  takes 15 to 50 minutes, by the size of the choir - but only the first time for a piece.

## Install

| For | You need |
|---|---|
| Everything above from a `.score` file or a PDF exported from notation software (MuseScore, Dorico, Sibelius, Finale): read exactly, in seconds | Python 3.10+, `pip install -r requirements.txt` |
| Scans and photocopies | the [homr](https://github.com/liebharc/homr) recognition engine beside the project: `python3.12 -m venv .venv-omr && .venv-omr/bin/pip install "homr[cpu]"` (AGPL; it is called as a separate program) |
| Words from a scan | nothing on macOS (with the Xcode command-line tools); elsewhere [Tesseract](https://tesseract-ocr.github.io/). A PDF that carries its text needs neither. |
| Audio other than WAV | `ffmpeg` (or macOS's `afconvert`) |
| `--voice` | the voice model ([docs/how-it-works.md](docs/how-it-works.md)), and `pip install pyworld`, which rebuilds the sung notes the model leaves rough (on a recent Python add `"setuptools<81"`, which pyworld needs to start) |
| `--tune`, and the listening checks in `tools/` | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) and a model, named in `WHISPER_MODEL` |

## Known limitations

- **It has never been listened to by its author.** Every judgement behind it is a measurement:
  against isolated recordings of real singers, against accompaniment tracks, and by a speech
  recognizer. Trust your ears over its reports.
- **Men's chorus only** (TTBB, TTB, soloist or trio over the choir), with piano or unaccompanied.
- **Reading scans is imperfect.** Typically 96-99% of the notes are right. About one syllable in
  ten is wrong or missing, more with Tesseract. (A PDF exported from notation software is read
  exactly instead, from its own symbols - in a current music font or Finale's older Maestro. That
  reader has met two such files so far, and does not yet follow "8va" lines or first and second
  endings. A PDF that stores its music font under private numbers is recognized like a scan.)
  Repeats, D.S. and codas are followed; first and second endings are not. Always look through the
  `.score` file it writes.
- **Words:** English (by dictionary) and church Latin (by rule). A word the dictionary does not
  have - a name, another language, a misread - is sung as it is spelled, by rough English rules:
  a near miss, which a `say:` line in the score corrects. Words spelled alike and said differently
  ("lives", "tears", "read") follow a short table of what a song usually means.
- **A full choir is harder to understand than a real one** on quick text, though single voices are
  about as clear as real singers.
- **Tone is the median of a dozen real singers.** A particular voice can differ from it by 10 dB
  in places.
- **Timing follows the accompaniment track** when there is one. Where the score as read does not
  match the recording (a misread ending, a cut), the run says so and the timing there is a guess.
- **From a PDF alone, the pacing is by rule.** A metronome mark is followed; a tempo given in words
  ("Moderately slow") is looked up in a table; a fermata adds about a beat, a "rall." slows to
  about three quarters until the next "a tempo". The accompaniment is the built-in piano playing
  the piano staves: no other instrument, and no pianist's judgement.
- **Slow.** Half a minute a page to read a scan; about a minute to sing a three-minute piece.

## The name

*Palare* is one spelling of [Polari](https://wp.lancs.ac.uk/fabulosa/whats-polari/) (from the
Italian *parlare*, "to talk"): the slang gay men in Britain spoke among themselves, picked up from
the theatre, the fairground and the merchant navy, in the years when being found out could mean
prison. It let two men talk about their lives in a pub or on a bus without anyone around them
following. The whole country heard it, mostly without knowing what it was hearing, from Julian
and Sandy on the BBC's *Round the Horne* in the 1960s. After the law changed in 1967 there was
less need for it and it faded, leaving English a few of its words: *naff*, *zhoosh*, *camp*,
*drag*.

*Piano* is the instrument under the voices here, and the Italian for "softly". *Parlare piano*:
to speak quietly - which is what Polari was for.

Gay choruses are the other half of that history: the same people, no longer keeping their voices
down. The [San Francisco Gay Men's Chorus](https://www.sfgmc.org/our-story), founded by Jon Reed
Sims in the autumn of 1978 and the first chorus to put the word "gay" in its name, sang in public
for the first time on the steps of City Hall on 27 November 1978, at the candlelight vigil on
the night Harvey Milk and George Moscone were killed. Its tour of nine cities in 1981 left new
choruses behind it. [GALA Choruses](https://en.wikipedia.org/wiki/GALA_Choruses), the
association they formed in 1982, now has more than two hundred member choruses and over ten
thousand singers. Through the AIDS years they went on singing while they buried their own; the
San Francisco chorus remembers the more than three hundred members it lost as its "fifth
section".

This program was written to help one such chorus learn its notes.

## Credits

- **Voices.** The men's voices that `tools/vocalset_voices.py` fetches for `--voice` are from
  [VocalSet](https://zenodo.org/records/1193957): Julia Wilkins, Prem Seetharaman, Alison Wahl
  and Bryan Pardo, "VocalSet: A Singing Voice Dataset", ISMIR 2018, licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Fourteen seconds of each of nine of
  its singers, with the silences cut out, serve as references for voice conversion. None of the
  recordings are in this repository. **Anything you share that was sung with these voices - a rehearsal track included -
  must carry this credit.**
- **Voice conversion** (`--voice`) is done by [Seed-VC](https://github.com/Plachtaa/seed-vc)
  (GPL-3.0), installed separately and run as its own program; none of its code is here.
- **Each re-voiced singer's tone** is rebuilt with [WORLD](https://github.com/mmorise/World) (Masanori Morise;
  modified BSD) through [pyworld](https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder)
  (MIT).
- **Reading scans** is done by [homr](https://github.com/liebharc/homr) (AGPL-3.0), likewise
  installed and run separately.
- **Listening checks** use [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (MIT) with
  OpenAI's Whisper models; **pronunciation** uses the CMU Pronouncing Dictionary.

## More

- [docs/how-it-works.md](docs/how-it-works.md) - what each file does, how PDFs are read, what is
  estimated for each piece and from what.
- [docs/score-format.md](docs/score-format.md) - the plain-text score format.
- [docs/journal.md](docs/journal.md) - the record of every test piece: what was measured, what was
  changed, and what did not work.
- `experiments/` - the stand-alone experiments that led here.

Audio, sheet music and transcriptions of copyrighted arrangements are never committed
(`.gitignore` blocks them, along with per-piece settings); renders go to `out/`.
