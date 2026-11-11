# Palare-Piano

Experiments in synthesizing a men's chorus (tenor 1, tenor 2, baritone, bass) entirely in code —
no samples and no recordings — and in rendering written sheet music with it.

## What is here

| Path | What it is |
|---|---|
| `choral/voice.py` | The voice engine. Each singer is simulated: vocal-fold pulses one at a time, breath noise, a moving vocal tract, and a "brain" that hunts for pitch, enters late or early, and drifts with its section. |
| `choral/score.py`, `choral/lyrics.py` | Reader for a plain-text score format that mirrors the printed page, and the sung-text-to-phoneme step. See [docs/score-format.md](docs/score-format.md). |
| `choral/latin.py` | Church Latin by rule, syllable by syllable, with its own five vowels fitted to real singers. |
| `choral/piano.py`, `choral/render.py` | Piano, stage (48 singers on risers in front of a stereo pair, section leaders on close mics), hall, mix. Every section is kept on its own stem, so one part can be brought forward, left out, or heard alone. |
| `choral/__main__.py` | The program: sheet music in, audio out (see below). |
| `choral/presets.py` | Estimates what differs from piece to piece - tempo and its bends, hall, how close the microphones are, how loud the accompaniment sits - from practice tracks, from a speech recognizer, or from the score alone. |
| `choral/timing.py` | Finds where every beat of the score falls in a recording: one tempo and start time, sharpened on the accompaniment's note attacks, then any ritardando or held last chord. |
| `choral/reference.py` | Takes a set of practice tracks apart (balanced, accompaniment, "part predominant" or "part muted") into voices alone, accompaniment alone and one part alone, and says how cleanly they separated. |
| `choral/hear.py` | The speech recognizer used as a stand-in for ears: English directly; other languages through the multilingual model, told the piece's vocabulary. |
| `tools/scan2score.py` | Reads a *scanned* score: cuts each page into systems, has the open-source recognition engine `homr` read the notes, decides which staves are voices and which the piano, splits two voices sharing a staff into their parts, finds the barlines, and takes the words (and tempo marks) from the page by text recognition. |
| `tools/pdf2score.py` | Reads a vector PDF exported from Finale (Maestro font) straight into the score format: pitches from notehead positions, note values from stems, beams, flags and dots, ties, key changes, and lyrics re-joined into words. Scans still have to be read by eye. |
| `tools/fit.py` | Fits the piano, or the voice, to a recording by rendering on the recording's own timing and comparing mel spectrograms, one setting at a time, with held-out passages as the test. |
| `tools/listen.py` | Uses a speech recognizer as ears: transcribes a render and reports how many of the score's words came through. |
| `tools/check_part.py`, `tools/check_mix.py` | Check a transcription against a recording: pitch-track one isolated part, or test every written note against a recording of all voices. |
| `tools/calibrate.py` | Fits the engine's tone to a recording of a real singer on the same notes. |
| `tools/tone.py` | Tone, harmonic by harmonic: on every held vowel, compares the strength of each harmonic in a real solo recording and in the model. Only harmonic peaks count, so room reverb does not. |
| `tools/compare.py`, `choral/compare.py` | Spectral comparison: one real singer alone beside the same part sung by simulated singers on the recording's timing, measured the same way note by note (tone in 16 bands, loudness through each note, colour through the note, entries by consonant type, releases, loud against soft, steadiness) - the simulated ones first placed in a room matched to the recording's, so that like is compared with like. Lists what differs, largest first; given several singers, lists what they have in common. `python -m choral` writes this report on its own whenever practice tracks let it isolate a real voice. |
| `tools/realism.py` | Scorecard: renders one simulated singer on a part and measures it beside a real singer's isolated recording of the same part — pitch glides and scoops, attacks, how notes are held, harmonics versus noise, consonant strength. |
| `experiments/` | The stand-alone experiments that led here (a vowel-only "Shenandoah", and an original pop number in three engine generations). |
| `scores/demo_shenandoah.score` | A short public-domain example. |

## Running it

```
pip install -r requirements.txt
python -m choral scores/demo_shenandoah.score --part bass
```

writes, into `out/`: the full rendering (*balanced*), *voices only*, and for the part you named
*Bass predominant* (the others quiet behind it), *Bass muted* (everyone else, to sing against)
and *Bass alone*.

```
python -m choral MUSIC [--part tenor1|tenor2|baritone|bass] [--accompaniment TRACK]
                       [--balanced TRACK --predominant TRACK | --muted TRACK] [--tune] [--out DIR]
```

- **MUSIC** is a score file ([docs/score-format.md](docs/score-format.md)) or a PDF. A PDF exported
  from notation software is read directly (`tools/pdf2score.py`); a scanned PDF is recognized
  (`tools/scan2score.py`, about half a minute a page). Either way the program writes a `.score`
  file beside the PDF and sings from that, so a misread note or word can be corrected by hand
  and the next run uses the correction.
- **--part** may name several parts (`--part tenor1,tenor2,bass`, or `solo`); in three-part music
  "bass" is the baritones and basses together. `--predominant` may list one practice track per
  part named, and timing is then taken from whichever of them is singing.
- **--accompaniment** sings over a recording instead of the built-in piano. The voices are lined
  up with it automatically: from the written piano part if the score has one, otherwise from a
  practice track of one voice part.
- **--balanced / --predominant / --muted** are practice tracks of the same piece, if you have
  them. They are only listened to (see below); nothing of them ends up in the output.
  When they let the program isolate one real singer, it also writes `TITLE - compared with the
  real PART.txt`: where the simulated voice differs from that singer, largest differences first.
- **--tune** lets a speech recognizer choose the microphone distance (needs `whisper-cli` and
  `WHISPER_MODEL`; for a score that is not in English, the multilingual model in `WHISPER_MODEL_MULTI`).

### Reading scans

Scans need a music-recognition engine. This project uses [homr](https://github.com/liebharc/homr)
(AGPL-licensed, so it is installed beside the project and called as a separate program, not
copied in):

```
python3.12 -m venv .venv-omr && .venv-omr/bin/pip install "homr[cpu]"
```

It needs Python 3.11-3.14 and downloads its models the first time it runs. Words are read with
macOS's built-in text recognition (`tools/ocr.swift`, compiled on first use); without it the
notes come out with no words. What is and is not reliable yet is in the status section below.

### What gets estimated for each piece

A piece's settings are worked out once and kept beside the score as `NAME.preset.json`.

| Setting | From practice tracks | Without them |
|---|---|---|
| Tempo, the first beat, ritardandos, the held last chord | Measured: the predominant part is pitch-tracked against the score, the beat grid is sharpened on the accompaniment's note attacks, and only a drift that never returns to the pulse counts as a tempo change | The score's `tempo:` |
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

## What is not here

Audio, sheet music, and transcriptions of copyrighted arrangements are never committed
(`.gitignore` blocks `*.wav`, `*.mp3`, `*.pdf`, `scores/private/` and the per-piece preset and timing
files). Renders go to `out/`.

## Honest status

Six test pieces so far, for men's voices, each with a real reference recording.

**Reading the music.** The first piece was a phone scan, read by eye; it matched a real
baritone's isolated track on all 335 notes. The second was a vector PDF, read entirely by
`tools/pdf2score.py`: all 474 staff-measures add up, and 197 of 199 baritone notes pass the pitch
check against the recording.

**Voices.** The voice model was fitted to the first piece's real baritone with
`tools/realism.py` (clean tone, shorter consonants, living vowels, pitch scoops and glides).
The second piece then showed that this did not carry over: at a faster tempo the full choir was
far less intelligible than the solo voice. The cause was the room and the mix, not the singer -
less hall, and section leaders further forward, fixed most of it on both pieces.

Words a speech recognizer makes out (voices alone / with accompaniment):

| | real recording | this engine |
|---|---|---|
| piece 1 (100 bpm) | 76% / 84% | 77% / 84% (one render) |
| piece 2 (130 bpm) | - / 83% | 72-79% / 60-65% |

`tools/fit.py` can also fit the voice to a recording automatically. It brought the model 2 dB
closer to the real singer on held-out passages, but the recognizer then understood about 10
points fewer words: it had learned to imitate the recording's room with breath noise and blurred
vowels. Those settings are not used.

**Solo tone.** `tools/tone.py` compares held vowels harmonic by harmonic with the real baritone.
Fitting on half the piece and testing on the other half brought the error from 7.3 dB to 6.1 dB:
a 16-point colour curve (fuller fundamental, less 1-1.5 kHz, a filled-in 4 kHz region), a
stronger fundamental from the voice source, and slightly broader resonances. The fit also wanted
to move the vowels themselves toward the singer's more covered, central shapes; that took solo
word recognition from 79% to 68%, so the vowels were left alone. "s" is now a broad hiss from
4 kHz up, as measured, instead of a narrow band.

**Piano.** Fitted with `tools/fit.py` to the second piece's accompaniment track (distance on
held-out measures 8.6 dB -> 5.7 dB): sustain pedal, a longer aftersound, a warmer soundboard,
voiced chords. Instruments that are not in the vocal score (percussion, strings) are not rendered.

**The third piece** (144 bpm, soft, a scan read by eye; the real baritone's notes match the
transcription 99%) is where the engine is weakest so far, and the numbers say so:

| piece 3 | real recording | this engine |
|---|---|---|
| voices alone | 63-71% | 25-37% |
| baritone alone | 89% | 26-35% |

Two things in it are new. Two different texts are sung at once for long stretches, and much of
the text is quick drum syllables ("pum") on eighth notes. Changing the hall or the microphones
makes no measurable difference here; the loss is in the voices themselves.

What comparing the real baritone with the model on this piece showed, and what was done:

- On "pum" the real singer sings about 40% of the note on the vowel and hums the rest on the
  "m"; the model held the vowel and tacked on a 40 ms "m". Drum and bell syllables are now sung
  that way, and the hum's tone was fitted to the singer's 13 held "pum" notes (error against the
  recording 6.4 dB -> 2.7 dB, and it had been 11 dB too quiet).
- The real singer's consonant clusters are shorter than the model's, and his nasals are brighter.
  Copying either into ordinary text made a twelve-voice section *harder* to understand at speed
  (piece 2: 75% -> 58% of words with both), so both are switched off: what is right for one
  close-miked singer is not right for a section. The first two pieces score as before, within
  the recognizer's noise (latest runs, voices alone: piece 1 78-84%, piece 2 59-68%).
- A second real singer confirmed two things the scorecard had hinted at: soft singing has slower
  attacks (125 ms against 36 ms at mezzo-forte) and relatively stronger "s". The hiss was raised
  slightly; the attacks are not yet tied to dynamics.

Following that up: one simulated singer alone is now heard saying the drum syllables verbatim,
and scores 54-60% on this baritone part against the real singer's 89%. The rest of the loss
happens when twelve of them sing together: the section alone drops to about 25%. Tightening the
section's timing helped the section by itself (24% -> 36%) but made no measurable difference to the
full choir, so it is not adopted. One timing fault was measured and fixed on the way: the puff of
air after p, t and k came after the beat and delayed the vowel by 30-40 ms; real singers have
the vowel at full level on the beat.

The recognizer's score moves by several points between identical runs - a full-choir score can
differ by ten points between two random sets of singers - and at low levels it cannot tell one
setting from another. The tuner now says so and keeps the rule of thumb instead of picking noise.

**The fourth piece** was a fresh test of the whole chain: three parts instead of four, in Latin,
with a tempo change, mixed 10/8 and 6/8 bars, a repeat and a D.S. al Coda, from an 11-page scan.

- *Reading it.* Written out as 87 measures in performance order; every bar added up on the first
  pass. The practice tracks separated cleanly (the accompaniment cancels by 29 dB), which gave
  all three parts in isolation. The first reading matched them on 93-95% of notes; the
  mismatches pointed straight at three misread bars, and after correcting those the parts match
  on 97%, 99% and 98%. Most of what remains is the middle note of quick triplets, which the pitch
  tracker cannot resolve.
- *Timing.* Both tempos were found without help (120.0, then 138.0), after the timing code was
  generalized to fit each tempo section separately.
- *Pronunciation.* Two questions were settled by measuring the real singers rather than by the
  rule book: there is no breath noise before the vowel of "Hosanna" (the h is silent), and its s
  is the softened, voiced s the chant books describe - the voice carries on under a light hiss.
  (An English recognizer had heard the engine's version of that as "l", and for a while a full
  unvoiced s was used instead; a recognizer that can follow Latin hears the real choir sing
  "hozana", and the measurement agrees.)
- *Vowels.* Against two real tenors and a real bass, the engine's "ee" was far too thin - its
  second harmonic 17 dB weaker than theirs - and its "oo" likewise. Trained singers keep their
  vowels closer together than speech does. Latin now has its own five vowels, fitted to the three
  singers and taken 65% of the way there: tone error 7.9 dB -> 6.2 dB, and going further starts
  to cost recognized words. English vowels are unchanged (an earlier attempt to move them cost
  ten points of intelligibility).
- *Note shape.* These singers let every held note fade at about 12 dB a second (the piece is
  marked "bell like"); the engine sustained them. That is now a per-piece setting measured from
  the recording: fade -1.4 -> -11.8 dB/s against the real -14.2, and the share of each note sung
  at full voice 93% -> 80% against 77%.

*Words.* Whisper barely knows Latin - the real choir scored 25% - so the yardstick for Latin is the
multilingual model hearing the singing as Italian, with the piece's vocabulary given to it as
context. It cannot invent the text from that: the accompaniment alone, and the choir singing
every note on "ah", both score 0%.

| piece 4 (Latin) | real recording | this engine |
|---|---|---|
| all voices | 62% | 57% |
| tenor 1 / tenor 2 / bass alone | 59% / 71% / 56% | 46% / 52% / 55% |

So on this piece the words come through nearly as well as the real choir's. The same yardstick
settled the vowel question properly: speech-like vowels are understood slightly better (single
voices 70% against 67%) and the singers' own vowels sound more like them (tone error 6.0 dB
against 7.9 dB); the 65% setting keeps most of the tone for a few points of words. Fading notes
cost no words.

Giving the recognizer the vocabulary on the third piece narrows its gap but does not close it:
the render goes from 26% to 48%, the real voices from 69% to 75%. That piece's problem is real.

What is still clearly wrong on the Latin piece: the simulated tenors' fundamental is about 10 dB
too strong against the second harmonic (real 1-3 dB, model 10-14), which none of the obvious
settings fixes.

**The fifth piece** (a slow carol for a soloist and four-part choir, an 8-page scan, 125 measures)
was read entirely by `tools/scan2score.py` - the first piece with no hand transcription - and
went from PDF to finished audio in one command, about a minute and a half.

- *Notes.* All 125 measures add up as read. Against the isolated real singers, 52 of the
  soloist's 53 notes and 138 of the baritone's 145 are right (the misses: a voice crossing, and
  one system where the choir shares a single staff). On the pages also read by hand, the two
  readings agree, and the automatic one settled several notes the hand reading had marked doubtful.
- *Layout.* 22 systems of five different shapes (piano alone; solo and piano; solo, two choir
  staves and piano; two choir staves and piano; one shared choir staff and piano) were all
  assigned correctly. Barlines are found from what every staff of a system shares, which a note
  stem never does.
- *Words.* The weak part. Most syllables land on the right notes, hyphens are found on the page
  itself, but text recognition drops small syllables and garbles some, more so where two lines of
  text sit under one staff: about fifty words of this piece came out as non-words. They are easy
  to see and fix in the score file, but they are not yet right unaided.
- *Timing.* The piece breathes (ritardandos, a faster last verse). Tempo marks are picked up from
  the page, and the tempo map now follows stretches where several entries in a row sit off the
  pulse. On the final clock the soloist's notes all line up with the real singer; 121 of the
  baritone's 144 do.
- *A solo voice* is new: one singer on a close microphone, `SOLO:` in the score format.

| piece 5 (words recognized) | real recording | this engine |
|---|---|---|
| soloist alone | 64% | 60% |
| all voices | 58% | 34% |
| baritone alone | 42% | 20% |

The simulated soloist is understood about as well as the real one. The choir is not, and here
part of that is the misread words it was given to sing.

**The scan reader against the earlier pieces.** Three of the earlier pieces were scans that had
been transcribed by hand and checked against recordings, so they could grade the reader. Voice
parts only; "right" means the same note in the same order as the hand transcription.

| scan | measures (hand / read) | pitches right | pitch and length right | syllables on the right note | words right (tenor 1 / baritone) |
|---|---|---|---|---|---|
| piece 1 (a phone scan) | 83 / 83 | 99.8% | 95.7% | 89% | 84% / 90% |
| piece 3 | 99 / 99 | 98.5% | 96.6% | 91% | 96% / 88% |
| piece 4 (Latin, 10/8 and 6/8 bars, triplets) | 75 / 75 | 98.4% | 96.5% | 92% | 81% / 87% |
| piece 5 (the part read by hand) | - | 98.6% | 98.1% | - | 96% (soloist) |

The printed tempo was found on every one (in piece 3 as half notes, which the reader converts).
What the first run on these exposed, and what was done:

- On a slightly tilted scan, four-staff systems were being cut in two and the choir's staves taken
  for piano (piece 4 came out 73% right). The line that joins a system's staves is now looked for
  with a little tolerance: measured, it scores 0.73-1.00 within a system and under 0.4 between.
- Most of what is left in "length" is ties: a note tied across the end of a line is struck again,
  because each system is read on its own. Where the words show it (the same pitch, first in the
  new system, no syllable of its own) the tie is restored. Applying the same idea inside a bar
  made things much worse - text recognition misses too many syllables to lean on - so it is not used.
- Words were the weak part: at first only 64-76% of syllables landed on the right note. What changed that:
  - The recognition engine records where every note stands on the page. Syllables are now matched
    to notes by position across the whole system, instead of being spread evenly inside each bar;
    that took the wrongly placed syllables on piece 4 from 21% to 2%.
  - A note left with no word is looked at again by itself, close up, where its word must be.
  - Hyphens are settled by dividing each line into dictionary words, with what was seen on the page
    as the tie-breaker (sung syllables such as "pum" count as words, or they get glued to their
    neighbours). Without a dictionary - Latin - a word seen twice with its hyphens lends them.
  - A note that still has no word takes the one another part sings at that moment; a staff with
    nothing printed under it sings the words of the staff that has them.
  - Words printed above the top staff belong to its upper voice where that voice moves alone.
  - Chord symbols, "poco rit.", "a tempo" and their misreadings are kept out of the lyrics.

  What is left: about one syllable in ten is still missing, misread or wrongly hyphenated.

**Repeats, D.S. and codas** are now unrolled. The score format has a `play:` line giving the order
the printed measures are performed in, and the scan reader writes it: repeat barlines come from the
recognition engine, the words ("D.S. al Coda", "to Coda", "Coda", "Fine") from text recognition
above each system, and the segno sign from its shape (about three staff spaces tall with two
separate dots beside it). On piece 4 it found all five things on the page - a repeat, the sign,
"to coda", the D.S. and the coda - and wrote the correct order. The unrolled result has the same
87 measures and 349 beats as the hand-unrolled transcription, and against the isolated real
singers 97% of the first tenor's notes and 98% of the second tenor's are right.

Two things had to be fixed to get there. A "measure" holding only the clef and key before a
repeat sign was being counted. And the engine's reading of time signatures is unreliable (it
gave 3/4, 5/4 and 15/8 where the page has 4/4 and 10/8), so each measure's length is now counted
from its notes - the total most voices agree on - which reproduced the printed sequence exactly.

From scan to audio in one command, measured by the recognizer: the carol's simulated soloist is
understood at 72% (the real soloist 85%, both judged against the text as read from the scan), and
its choir at 48% (real 73%). The Latin piece from its scan stays at 40% of words, against 57% when
rendered from the hand transcription and 62% for the real choir - better words on the page did not
move that number, which says the rest of that gap is not in the words read.

Not yet done for scans: first and second endings; D.C. and "al Fine" are written but untested;
different words on a repeat; about one syllable in ten is still wrong or missing; and where
there are no practice tracks nothing checks the notes except that every measure adds up. The
sign detector also reported two signs on piece 1 that are not there - harmless without a D.S.,
but a reason to look at the `play:` line it writes.

**The sixth piece** is unaccompanied: a trio of soloists over a four-part choir, in Latin, slow and
soft, with chanted verses between the refrains. Its practice tracks are "one voice with the rest
quietly", with no accompaniment to subtract; taking the right share of the balanced mix out of
each (the share that leaves the quietest moments quietest) isolates four real voices. The scan
reader, told nothing, recognized that there is no piano (words are printed under the lowest staff)
and that the staves are a small group over the choir; on the first refrain 217 of the 221 notes
of those four voices match the real singers.

Only that refrain (80 seconds) is rendered so far. The whole form is not assembled automatically:
the recognition engine could not read the first line of chant, the later verses are printed after
the refrain with nothing but words to say where they go, and the choir's lyrics on this copy are
partly covered by pencil marks.

**Voice realism, with nine real singers to compare against.** The four new voices brought the
number of isolated real singers to nine, and three things that had looked like quirks of one
piece turned out to be consistent:

- *Tone.* The voice's colour curve had been fitted to the first piece's baritone. Against the
  other eight singers it was wrong in the same direction every time: 6-10 dB too much below
  400 Hz, too little around 1.6 kHz and 2.5-3 kHz, too much at 3.5 kHz. Refitted to the median of
  all nine, the tone error falls from 7.4 dB to 6.4 dB (better for eight singers, worse for the
  one it used to be fitted to), and the fundamental, which had been 6-13 dB stronger than the
  second harmonic where real voices have it 2-5 dB weaker, now sits within 3-5 dB of them.
- *Unsteadiness.* Real voices waver quickly by 4-5 cents on a held note; the model's wavered by
  about 2 on every piece. A quick random pitch component now gives 3.4-3.7.
- *Entries.* How fast a phrase begins depends on how loudly it is sung: the rise to full voice
  takes about 36 ms at mezzo-forte, 125 ms at mezzo-piano and 200 ms at piano on real singers,
  and took 35-55 ms at any dynamic in the model. It now follows the dynamic (177-186 ms on this
  piece, against 195-226 ms).

One more is measured per piece from a recording, like the bell-like fade before: how far under
the note a phrase begins (these singers hardly scoop: 14-21 cents; the model had 67-73).

The recognizer was the check on all of it: single voices on the English pieces score 54 / 84 / 72
/ 88% after the changes against 53 / 74 / 72 / 86% before, and the full choirs are unchanged
within its noise.

**The shape of a single note.** Every simulated note used to sit at full voice for 96% of its
length; on this piece the real ones manage 66-70%. Slicing each held note into tenths and
comparing levels, singer by singer, showed what the real voices do and when:

| | level through the note, dB under its loudest fifth (ten slices, start to end) |
|---|---|
| real, soft and slow (three singers, one piece) | -8 -7 -5 -4 -2 -1 -2 -3 -5 -7 |
| real, soft and slow (the soloist of another) | -6 -4 -3 -2 -1 -1 -1 -3 -5 -7 |
| real, mezzo-forte and quicker (another piece) | -1 -1 -1 -1 -1 -1 -1 -3 -7 -10 |
| the model, before | 0 -1 -1 -1 -1 -1 -1 -1 -4 -7 |
| the model, now, on the first of these | -9 -7 -5 -3 -2 0 0 0 -4 -8 |

In soft, slow singing a note grows for about two thirds of its length and eases off again. The
first note of a phrase takes longer to arrive, the last one does not swell and tapers instead,
and long notes taper further. No two notes are alike: the swell ranges from nothing to twice the
usual and peaks anywhere from half way to four fifths through. None of it happens at mezzo-forte
and above, and the same singers did not do it on the soft held notes of a quick piece. The voice
now does all of this (`choral/voice.py`, the `swell` setting): by rule where there is no recording
(6.5 dB at piano and softer, in slow music only), and at the depth measured from one isolated
real voice where there is one (10.5 dB on this piece, 5.3 dB on the soft solo of the carol).

Measured again afterwards: the share of each note at full voice is 72-77% on this piece (real
66-70%) and 94% on the carol's solo (real 83%); the note-to-note spread is close (on both sides a
tenth of the notes do not swell at all and a tenth swell nearly twice as far as the middle one);
and the peak falls at 58-67% of the note (real 64-66%). The recognizer
lost nothing: with the swell switched on and off for the same singers, the soft solo scores 80%
against 79%, and two of the three upper voices on this piece 50% against 42% and 48% against 45%.
Loud and quick pieces render exactly as before.

**Comparing spectra, so that problems show themselves.** The note shapes above went unnoticed for
five pieces because nothing was looking for them: every earlier measurement answered a question
somebody had thought to ask. `tools/compare.py` asks none. It sets a real singer beside the model
on the same notes and the same timing, measures both spectra note by note, and lists whatever
differs. All eleven isolated real singers take 19 seconds.

Its first version made a mistake worth recording. It reported three differences on nearly every
singer, and two of them were not differences between voices at all:

- *"The model's sound drops 17 dB for a tenth of a second before every stop; real singers' barely
  dips."* The real recordings have a room around the voice and the simulated singer was dry. A
  room fills a consonant's gap; silence does not. Measured two ways that a room cannot fool -
  with the model placed in a room matched to how each recording dies away, and by timing the
  sound's fall and its next rise - the real singers' breaks are as long as the model's or longer
  (before "t": 142 ms real, 116 ms model), and the levels around a syllable's start agree within
  1-3 dB in every band below 3.6 kHz.
- *"Real held notes wander twice as much in level and brightness."* The same room: in it the
  model wanders as much as the singers do (level 0.23-0.72 dB real, 0.33-1.02 model).

So the comparison now puts the simulated voices in a plain room chosen to make them die away
after phrase ends as the recording does, and only then measures. Like with like, what is left on
the eleven singers is:

- *Tone above 3.5 kHz.* The model has a peak around 4 kHz that the singers do not (10 dB, 10 of
  11 singers) and too little above 5.6 kHz while a note is held (12-16 dB, 11 of 11). It is the
  voice, not the recordings' noise: that band stands 10-31 dB above its own level in the rests.
  The earlier tone fit could see neither - it compared harmonic peaks only, in wider bands.
- *Loudness through a note* within 3 dB of the real singers at every tenth, in the room as well:
  the note shaping holds.
- Smaller things on some singers only: after a consonant the model's brightness arrives 20-40 ms
  sooner than the singers' (7-8 of 11), and in two pieces the real singers grow much louder on
  their high notes than the model does (8-14 dB against 2-4).

None of these numbers says the result would pass for a recording.
