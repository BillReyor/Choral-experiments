# How it works

## The files

| Path | What it is |
|---|---|
| `choral/voice.py` | The voice engine. Each singer is simulated: vocal-fold pulses one at a time, breath noise, a moving vocal tract, and a "brain" that hunts for pitch, enters late or early, and drifts with its section. |
| `choral/score.py`, `choral/lyrics.py` | Reader for a plain-text score format that mirrors the printed page, and the sung-text-to-phoneme step. See [docs/score-format.md](score-format.md). |
| `choral/latin.py` | Church Latin by rule, syllable by syllable, with its own five vowels fitted to real singers. |
| `choral/piano.py`, `choral/render.py` | Piano, stage (48 singers on risers in front of a stereo pair, section leaders on close mics), hall, mix. Every section is kept on its own stem, so one part can be brought forward, left out, or heard alone. |
| `choral/__main__.py` | The program: sheet music in, audio out (see below). |
| `choral/app.py`, `choral/app.html` | The page for people who do not use a terminal: a web server only this computer can reach. Add a PDF, have it read, choose a part, make the tracks, play them. It runs `python -m choral` for each piece, one at a time, follows what it says, and keeps every piece in a folder of its own under `~/Music/Palare Piano`. |
| `choral/fix.py` | "Fix a note or a word" on the page: shows one measure as the printed page has it - where each note sits on its staff, what it sounds as under the key signature and the accidentals before it, the word under it - and changes one note or one word in the score file, leaving every other character as it was. The score is copied first, so that everything can be undone. |
| `choral/check.py` | "What this computer can do": looks at the chip, the memory and the free disk, sings a few seconds with one voice and (with real voices installed) converts a few, and reckons from figures measured on one machine whether each thing will work here and how long it will take. Its count of how many singers to sing at once is passed to the render as `CHORAL_WORKERS`. |
| The update check | `choral/app.py` asks GitHub, when the page starts and every six hours, what has been published on the branch `stable` since the version the installer wrote down (`version.json` beside the program), says so on the page with the list of what is new, and "Update now" runs the installer as a program of its own: it closes the running copy, installs the newest, starts it, and the open page finds it. Nothing about the computer or its music is sent - only the version, in the address of a public page. `stable` is what everyone is given: `tools/release.sh` moves it on to where `main` is, and only to a version that has passed the unit tests and the test of an install on Linux and Windows (on GitHub) and on a Mac (the one it is run on); GitHub refuses any other push to it. |
| `install.sh`, `install.ps1` | The one-step install - the first for an Apple-chip Mac and for Linux, the second for Windows: a Python of its own (through uv), the program, the scan reader, and something to open it with. [install-by-hand.md](install-by-hand.md) says what they do and where. |
| `tools/try_install.py`, `tools/try_here.sh`, `.github/workflows/install.yml` | The test of an install. The first opens an installed copy the way a person would and does what a singer does with the demo piece, by the page's own requests. The second is the whole test on one computer, in an empty home made for the purpose: the installer, that use of it, the installer again over it, the uninstall. GitHub runs it on Linux, and the same steps on Windows, at every change to the program; the Mac is tested on a Mac when a version is given out. |
| "Save a report" | `choral/app.py` writes, for someone whose copy has gone wrong, a text file to send to whoever is helping: the version, the computer, and what the program noted about each piece - no score, no track, and the home folder's name taken out. |
| A sound when tracks are ready | `choral/app.py` (`ding`): when a render ends, the computer itself plays its own "done" sound - the Mac's Glass through `afplay`, a Windows system sound, a Linux desktop's sound theme - and another if it went wrong; not if someone stopped it. The computer and not the page, because a browser lets a page make sound only just after a click, and after an hour the page may be in the background or closed. A switch on the page turns it off; switched on, it is played once so that it is known what to listen for. |
| Where a track is in the music | A render writes down when each measure begins (`render.measure_starts`, from the same clock the voices were timed by) and the page keeps it with the piece. Under each player it shows the measure being heard, opens "Fix a note or a word" at that measure, and starts the track from any measure asked for. Tracks made before this was kept get it worked out from the score, if the score has not been changed since. From the same record the player repeats a passage - from the beginning of one measure to the end of another, the end met by a clock of its own, since a browser says where a track is only four times a second - and it plays any track slower at the same pitch, which is the browser's own doing: nothing is made again. The reckoning in the page's script is run by `tests/test_page.py`, with node or the Mac's own JavaScript. |
| `choral/setup_voices.py`, `choral/seedvc_driver.py` | Adding real voices: the first installs the voice model and the voices and tries them once; the second is the program the model is run through (it runs in the model's own Python and imports nothing from here). |
| `choral/presets.py` | Estimates what differs from piece to piece - tempo and its bends, hall, how close the microphones are, how loud the accompaniment sits - from practice tracks, from a speech recognizer, or from the score alone. |
| `choral/timing.py` | Finds where every beat of the score falls in the recordings: a first, steady fit from one isolated voice, then a follower that tracks the written piano attacks through the accompaniment track and every isolated voice's notes together (position and tempo both), plus the checks that say how well the result fits - singers on pitch, voices against the accompaniment. |
| `choral/reference.py` | Takes a set of practice tracks apart (balanced, accompaniment, "part predominant" or "part muted") into voices alone, accompaniment alone and one part alone, and says how cleanly they separated. |
| `choral/revoice.py` | Optional (`--voice`): seats the recordings of real voices among the parts, hands every simulated singer's track to an outside voice-conversion model, which returns it in the voice of its recording, and puts the result back where the original was - lined up with it, and as loud as it at every moment. |
| `tools/vocalset_voices.py` | Fetches ten men's voices from the public VocalSet collection and names each for the part it sings, as voices for `--voice`. |
| `choral/hear.py` | The speech recognizer used as a stand-in for ears: English directly; other languages through the multilingual model, told the piece's vocabulary. |
| `tools/scan2score.py` | Reads a score from page images (a scan, or any PDF the shape reader cannot read): cuts each page into systems, has the open-source recognition engine `homr` read the notes - a system whose reading does not match the staves on the page is read again in parts - decides which staves are voices and which the piano (by the names printed beside them - "T 1", "Bar.", "Cl.", "Keybd." - where there are any, otherwise by counting; an instrument's staff is read and left out), adds a staff the engine did not find, corrects a clef it misread (a part keeps its clef through a piece), splits two voices sharing a staff, finds the barlines, follows repeats, D.S. and codas, and puts the words under the notes: from the PDF's own text if it has one, otherwise by text recognition (macOS's, or Tesseract). |
| `tools/vector2score.py` | Reads the notes of a notation-software PDF exactly, from the symbols it is drawn with: any PDF in a standard (SMuFL) music font - Bravura, Leland and the like, as exported by MuseScore, Dorico, Sibelius and recent Finale - and Finale's older Maestro font, whose characters it translates into the standard's (also where a PDF maker has stored them as Greek letters). Staff lines give the pitch of each notehead; stems make chords and tell two voices on a staff apart; beams, flags, dots and tuplet numbers give the note values; accidentals last to the barline; curves are ties or slurs. It checks itself (do the measures add up?) and steps aside if they do not. |
| `tools/pdf2score.py` | An earlier reader for Finale's Maestro font, built around the first pieces; now only tried when the exact reader steps aside. |
| `tools/fit.py` | Fits the piano, or the voice, to a recording by rendering on the recording's own timing and comparing mel spectrograms, one setting at a time, with held-out passages as the test. |
| `tools/listen.py` | Uses a speech recognizer as ears: transcribes a render and reports how many of the score's words came through. |
| `tools/check_part.py`, `tools/check_mix.py` | Check a transcription against a recording: pitch-track one isolated part, or test every written note against a recording of all voices. |
| `tools/calibrate.py` | Fits the engine's tone to a recording of a real singer on the same notes. |
| `tools/tone.py` | Tone, harmonic by harmonic: on every held vowel, compares the strength of each harmonic in a real solo recording and in the model. Only harmonic peaks count, so room reverb does not. |
| `tools/compare.py`, `choral/compare.py` | Spectral comparison: one real singer alone beside the same part sung by simulated singers on the recording's timing, measured the same way note by note (tone in 16 bands, loudness through each note, colour through the note, entries by consonant type, releases, loud against soft, steadiness) - the simulated ones first placed in a room matched to the recording's, so that like is compared with like. Lists what differs, largest first; given several singers, lists what they have in common. `python -m choral` writes this report on its own whenever practice tracks let it isolate a real voice. |
| `tools/realism.py` | Scorecard: renders one simulated singer on a part and measures it beside a real singer's isolated recording of the same part — pitch glides and scoops, attacks, how notes are held, harmonics versus noise, consonant strength. |
| `tests/`, `tools/test.sh`, `.github/workflows/tests.yml` | The unit tests: each part on its own - the score reader, the words, Latin, the voices, the piano, the mix, timing, the PDF and scan readers (from single rules up to a whole PDF drawn for the purpose and read from one end to the other), re-voicing (with a stand-in for the voice model), "Fix a note or a word", the check of the computer, and the page's server (that it answers only this computer, works only for its own page, and keeps to its library). `sh tools/test.sh` runs them here, in a Python it makes for the purpose; GitHub runs them on Linux and Windows at every change and pull request; a version is given out only when they pass on all three. See [How a change is made](#how-a-change-is-made). |
| `tools/reread.sh` | The reader tried on real sheet music - your own, which stays on your computer: reads every PDF under `scores/private/` and says which readings differ from the ones accepted last time. Run before and after a change to the reader. |
| `scores/demo_shenandoah.score` | A short public-domain example. |

The stand-alone experiments that led here (a vowel-only "Shenandoah", and an original pop number in three
generations of the engine) were in `experiments/` up to version `a92d7df` and are in the history from there.


## Reading a score from a PDF

A PDF exported from notation software is not a picture: every notehead is a character of a music
font at an exact place. Where that font is a standard one or Finale's older Maestro
(`tools/vector2score.py`), the notes are read off exactly and at once, and the words come from
the PDF's own text. Any other PDF - a scan, a photocopy - has its pages rendered and
recognized (`tools/scan2score.py`, about half a minute a page). Either way a `.score` file is
written beside the PDF and the program sings from that, so a misread note or word can be corrected
by hand and the next run uses the correction. The file is signed: if nobody has edited it and the
reader has changed since, the PDF is read again (`--reread` asks for that outright), so an old
reading is never kept merely because it is there.

Scans need a music-recognition engine. This project uses [homr](https://github.com/liebharc/homr)
(AGPL-licensed, so it is installed beside the project and called as a separate program, not
copied in):

```
python3.12 -m venv .venv-omr && .venv-omr/bin/pip install "homr[cpu]"
```

It needs Python 3.11-3.14 and downloads its models the first time it runs. Words are read with
macOS's built-in text recognition (`tools/ocr.swift`, compiled on first use); without it the
notes come out with no words. What is and is not reliable yet is in the status section below.


What the reader works out without being told, and from what:

- **Which staves are sung.** From the names printed beside them where there are any, and on the
  systems without names from the system that looked the same. A treble and a bass staff joined by
  a brace are a keyboard in most music; with a line of words between them they are the choir.
- **An instrument's staff.** A staff named for an instrument ("Cl.", "Flute") is not sung. Its
  line goes to the accompaniment as `IN:` lines, because where the choir rests it is the tune:
  without it an interlude is held chords and nothing else. It is played only if its key signature
  is the choir's - a part in another key is written for a transposing instrument and sounds
  elsewhere than it is written - and never if it is drums. Two notations of such parts are
  understood: a tremolo (two notes, each written as long as the measure, beamed together) is the
  two notes in turn, and notes that overfill a measure by exactly half are a triplet whose
  bracket was not read.
- **How long a measure is.** Counted from its notes: the total most voices agree on. A voice
  that is a single rest does not count against a voice with notes - the recognition engine gives
  such a rest whatever length it took the measure to have.
- **Which print under a staff is words to sing.** Not all of it is. A footnote at the foot of a
  page and a direction ("slide on beat") are set like any sentence: the words a space apart,
  every gap alike. Words to sing are spread under their notes, and no two gaps are the same. A
  line of three or more words set the first way is left out, and so is a line as tight beneath
  it (the ragged end of a footnote). A line that is nothing but a part's name ("Tenor I",
  "BASS", with or without a rehearsal letter) is the name of a staff. The run says what it left
  out and where.
- **A choir on two staves.** A piece that is pairs of staves from beginning to end is a keyboard
  piece - or a choir written short, tenors on the upper staff and basses on the lower, as hymns and
  brief unaccompanied pieces are. Words between the two staves say which.
- **Words above the top staff** are the first tenors' own, where they differ from the others'. A
  whole line of them is sung by the upper voice wherever the staff beneath carries two. And the
  staff above does not take them for its own: a line of words far below a lowest staff is asked
  which neighbours it sounds like - voices that sing together sing much the same words.
- **Where one system ends.** Staves joined at their left end by a line are one system. The line
  must stand where the staves begin: three spaces in stands the clef, and a clef's tail, a
  measure number and the next clef's top in one column look much like a line.
- **A staff with no barlines** (a line of chant). The recognition engine finds a staff by its
  barlines and clefs and returns nothing for one that has neither clearly; such a staff is shown
  to it again with a barline drawn at its end.
- **The language.** Latin is known by its words (*sanctus, dominus, gratia, et, in ...* against
  *the, and, of ...*); `--language english` or `latin` overrides.
- **The order of performance.** Repeat signs, D.S. and D.C., "to Coda" and "Fine", and numbered
  endings. An ending's bracket is found by its shape - a level line above the staff with a
  short stroke down from its left end - and the passes it is for are read under that corner
  ("1.", "1., 2.", "3."). Each ending is played on the passes it names and stepped over on the
  others. The order is written into the score as a `play:` line, which can be corrected.
- **The tempo.** A metronome mark; failing that a heading in words ("Moderately slow", "Quietly
  flowing"), looked up in a table; failing that a guess, announced in capitals.

Where the words come from: the PDF's own text when it has one (exact; nothing to install);
otherwise text recognition - macOS's built-in one, or [Tesseract](https://tesseract-ocr.github.io/)
on Linux and Windows (`SCAN_OCR=tesseract` forces it; it gets fewer syllables right, see the
journal).

## A real voice's sound (optional)

The engine's singers are a model of a larynx and a mouth. By every measure taken here they sing
like the real singers they were fitted to - tone, how notes begin and end, how straight they hold
a pitch - and they are still heard as synthetic. What is left is the texture of the method itself.

`--voice VOICE.wav` changes the sound and nothing else. The engine sings as before; then each
singer's dry track is cut into pieces of singing and given to a voice-conversion model together
with a recording of a real voice, and comes back as that voice singing the same notes and words
at the same moments. `choral/revoice.py` then puts each piece back where its original was (the
model may be a few milliseconds off) and deals with what the model gets wrong.

**The sung tone is built again.** The model's held notes are rough: measured cycle by cycle as a
voice clinic does, they have three times the jitter and twice the shimmer of the same man's own
recording, however the model is set - a listener called it a slight spasmodic dysphonia, plainest
on long notes. And the model is told the pitch only in coarse steps (15 to 43 cents wide in a
man's range), so its pitch wanders. So each singer's sung sound is taken apart with the WORLD
analysis (`pip install pyworld`) into its colour, its breath and its pitch, and built again:

- **Pitch**: the engine's, read from the engine's own sound cycle by cycle. (A pitch tracker's
  reading wobbles more than the singer does, and a voice rebuilt on it flutters.)
- **Colour and breath**: steadied a little everywhere and, inside every vowel the engine holds,
  steadied as a whole from just after the attack.
- **Loudness and pitch inside a held vowel**: steadied too.
- **The top end**: the model's sound has a fizz above 5 kHz that the voice it copies does not
  (on sung notes up to 19 dB too much above 12 kHz). Each singer's track is lowered above
  3.6 kHz by what his sung notes have too much of against the recording of his voice.

Consonants and rests stay the model's. This was made for a soloist; a listener then preferred
the whole chorus rebuilt as well, at some cost to how well a section's words are understood.

A part sung by one person has its consonants put right too, because alone they are heard. The
model's are weaker than the engine's, so each is raised to the engine's strength, by at most
10 dB. And the model sings through a stop - the d of "do" came out with no closure and almost no
click - so where the engine is closed before a stop the voice is brought down to it, and the
click of the release is the engine's own, above 2 kHz. Section singers get neither: twelve
clicks a few milliseconds apart make the words harder to follow, not easier.
Without pyworld the model's own sound is kept, its pitch nudged back onto the engine's and its
loudness made to follow the engine's, and the run says that held notes will be rougher.

The pieces are at most 15 seconds long and are cut at rests and breaths. A model works on one
window of sound at a time (half a minute less the recording of the voice, here) and joins windows
by crossing one rendering over into another; a piece that fits one window has no such join in it.
Of a recording of a voice, the first 13 seconds are used.

One thing is done before the model, not after it: a part sung by one person is sung by the
engine with consonants a third longer than usual when it is to be re-voiced. The model blurs
consonants; given longer ones, a re-voiced soloist is understood about as well as the engine's own
(a re-voiced section is understood the same either way, and is left alone).

**Whose voice.** Fifteen to thirty seconds of one person singing alone, without accompaniment - a
phone's recording will do, in any common format (WAV, m4a, mp3 ...; other than WAV needs ffmpeg,
or a Mac). Use your own, or that of someone who has agreed to it - not a singer lifted from a
practice track.

**Several voices** (`--voice a.wav,b.wav` or `--voice FOLDER`) are seated the way a choir seats its
people. A recording whose file name begins with a part's name - `Bass 2.wav`, `Tenor 1 - Sam.wav`,
`solo.wav` - sings in that part. The rest are put in order by the pitch of what is sung in them and
shared out among the remaining parts, lowest to the basses; a part sung by one person takes the
voice that lies nearest its notes. Within a section the voices go round, so neighbours differ. The
run prints who was seated where.

**More singers than voices.** One recording given to six singers is one man six times: a
speaker-recognition network scores the six as the same voice (0.98-0.99), however differently the
engine's six sang. So every further singer who gets the same recording gets it a little larger or
smaller: the recording is played up to 3.5% slower or faster before the model hears it, which moves
every resonance the way a larger or smaller throat and mouth would (the pitch sung still comes
from the engine). In a test, six sizes of one man spread wider than that (0.9 semitone either
way) scored 0.87-0.98 against each other - relatives, not strangers (two different men score
0.3-0.8) - and sang the notes and words as well as before. A
voice that has to serve several sections is larger in the lower ones, so one voice alone still
gives darker basses than tenors. A soloist keeps the voice as recorded.

**Voices to start with.** `python tools/vocalset_voices.py` writes ten men's voices into
`.svc/voices`, already named for their parts, from
[VocalSet](https://zenodo.org/records/1193957) (Wilkins, Seetharaman, Wahl and Pardo, ISMIR 2018;
Creative Commons Attribution 4.0): professional singers recorded alone for research. It fetches
only the ten clips it needs (about 30 MB), or reads them from the archive if you give it one. Then
`--voice .svc/voices`. Those men all sing the same songs in the same key, so pitch could not seat
them; they are seated by the size of the voice instead - how low its resonances lie, measured on
the songs they share. The soloist is the one a listener chose from five auditions, re-voiced from
his "straight" singing, which gives a quarter of the catches in the voice that his normal singing
gives. To move a
man to another part, rename his file; to drop him, delete it. Anything published that was made
with these voices should carry the credit.

**The model.** `revoice.py` only needs a command that takes a list of jobs
(`{"source": wav, "reference": wav, "out": wav}`) and writes each `out`; the command is the JSON
list in `.svc/command.json` (or in the file `CHORAL_REVOICE` names). The one used so far is
[Seed-VC](https://github.com/Plachtaa/seed-vc)'s singing model. `python -m choral.setup_voices`
sets all of it up - the page's "Add real voices" button runs the same thing - and what it does can
be done by hand:

```
python3.12 -m venv .svc/venv
.svc/venv/bin/pip install -r install/voice-model.txt          # torch 2.6.0, librosa 0.10.2, transformers 4.46.3 ...
# Seed-VC at the commit this was tested with (51383ef), unpacked as .svc/seed-vc
python tools/vocalset_voices.py -o .svc/voices                # the voices
pip install pyworld "setuptools<81"                           # in the program's own Python: steadies held notes
# .svc/command.json:  [".svc/venv/bin/python", "choral/seedvc_driver.py", ".svc/seed-vc"]   (full paths)
```

`choral/seedvc_driver.py` loads the model once and runs the jobs with that project's own functions.
Seed-VC is under the GPL-3.0 and the driver follows its code; it used to be kept outside this
repository for that reason, and is part of it now that the whole project is under the GPL. The
first run fetches about 2.3 GB of model files. On an Apple M-series machine it converts about four times as fast as real
time (ten refinement steps, which measured the same as thirty): a three-minute piece for four
parts of twelve is an hour and a half of singing, so about 25 minutes; with `--singers 4`, about
10. That is with the model's two heavy stages, the diffusion and the vocoder, in half precision,
as that project's own script runs them by default (`torch.autocast` around both): 0.6 of the time
of full precision and the same sound - over 32 stretches the spectra lie 0.13 dB apart, where a
second draw of the same singer lies 1.8 dB away, and a recognizer hears the same words. Have the
driver do a stretch again in full precision if it comes out as not-a-number or silence. Running
several copies of the model side by side gains nothing - the graphics chip is already full - and
neither does giving it four stretches at once.

What has been converted is kept (`.svc/cache`, up to 4 GB; `CHORAL_CACHE_GB` sets another size),
each stretch under the very bytes that were handed over. The engine sings a piece the same way
every time, so rendering it again - for another part's rehearsal tracks, say - takes no
conversion. After a correction to the score, only what the correction touches is converted again:

- Each breath of each singer draws its chance - how late he is, how he tunes and shapes each note -
  from a run of random numbers of its own, named by the singer and the beat the phrase starts on
  (`voice.breath_rng`). A phrase is the same take whatever was changed before it.
- Where a singer's part is cut into stretches is measured against its loudest moment taken to the
  nearest 6 dB, so that a new take of the loudest phrase does not move every cut in the part.
- Conversions are kept as they finish, ten at a time. A render stopped half way through goes on
  from there the next time, and stopping a render stops the model.

The unit is the phrase, from one rest to the next. One corrected word in the middle of a
three-minute piece sends about a twentieth of it to the model again. In slow music with few rests
a phrase can last half a minute, and a correction there costs all of it. A change that moves the
music in time - a tempo, the length of a measure - still converts everything after it.

## How a change is made

Test first. A fault someone hears, or a thing the program should newly do, becomes a test before it becomes a
change to the program:

1. **Write the test, and see it fail.** The smallest piece of music that shows the fault - three notes, a line of
   words, a page drawn for the purpose - and what should come of it. A test that passes before the fault is
   mended has not found it.
2. **Mend the program until it passes**, with every other test (`sh tools/test.sh`, under a minute).
3. **Take the mending out again and see the test fail.** A test that passes either way guards nothing. (The tests
   of a week's work were checked like this in one go: each rule broken on purpose, one at a time, to see that
   some test noticed. Forty of forty did; one of them had found a fault of its own on the way.)
4. **For a change to the reader, read real music before and after** (`sh tools/reread.sh`): every measure that now
   reads differently is either what the change was for or a mistake, and is looked at against its page.
5. **A version is given out** (`sh tools/release.sh`) only when the unit tests and the test of an install pass on
   Linux, on Windows and on a Mac, at exactly that version.

What the tests are made of matters here more than in most programs:

- **No sheet music, no words of a song, no recording that is somebody's.** The tests draw their own music and
  make up their own words. A piece that showed a fault is not named, and its words are not quoted - a made-up
  line that goes wrong the same way does the same work.
- **A sound's note is not asked of a pitch tracker.** The worst fault so far - real voices leaping an octave and
  sliding about - was first declared mended on a pitch tracker's word, and the tracker was what had been misled
  in the first place. The tests tell a note from which overtones carry the sound's strength, and from how well
  it repeats after one cycle of the note it should be on.
- **A test says what was heard.** Its name is the rule in plain words, and where a listener's remark led to it,
  the remark is beside it: the next person to break it should know what will be heard if they do.
- **What a test cannot tell is how it sounds.** That takes ears - a person's, in the end. A passing test means
  the rule holds, not that the singing is good.

## What gets estimated for each piece

A piece's settings are worked out once and kept beside the score as `NAME.preset.json`.

| Setting | From practice tracks | Without them |
|---|---|---|
| Tempo, the first beat, ritardandos, holds | Measured: the written piano attacks are followed through the accompaniment track and every isolated voice's notes through its own track, together, so the voices stay with the accompaniment; the run reports how well both fit | The score's `tempo:` |
| Hall (amount and length) | Matched to how the recorded voices die away after each release | A rule from how short the quick syllables are |
| Accompaniment level | Measured from the balanced mix | A fixed default |
| Note shape (sustained, fading like a bell, or swelling into each note) | Measured on one real singer: how fast held notes fade, and how far soft ones swell in | Sustained; soft notes in slow music swell in by a rule |
| Where a soloist sits against the beat | With the recording's beat, as sung | 70 ms behind the engine's placement (`solo_late`): the engine puts vowels on the beat and consonants before it, which one voice alone over a piano is heard to rush; a listener chose 70 ms from four placements |
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

