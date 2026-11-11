# Choral-experiments

Experiments in synthesizing a men's chorus (tenor 1, tenor 2, baritone, bass) entirely in code —
no samples and no recordings — and in rendering written sheet music with it.

## What is here

| Path | What it is |
|---|---|
| `choral/voice.py` | The voice engine. Each singer is simulated: vocal-fold pulses one at a time, breath noise, a moving vocal tract, and a "brain" that hunts for pitch, enters late or early, and drifts with its section. |
| `choral/score.py`, `choral/lyrics.py` | Reader for a plain-text score format that mirrors the printed page, and the sung-text-to-phoneme step. See [docs/score-format.md](docs/score-format.md). |
| `choral/piano.py`, `choral/render.py` | Piano, stage (48 singers on risers in front of a stereo pair, section leaders on close mics), hall, mix. Every section is kept on its own stem, so one part can be brought forward, left out, or heard alone. |
| `choral/__main__.py` | The program: sheet music in, audio out (see below). |
| `choral/presets.py` | Estimates what differs from piece to piece - tempo and its bends, hall, how close the microphones are, how loud the accompaniment sits - from practice tracks, from a speech recognizer, or from the score alone. |
| `choral/timing.py` | Finds where every beat of the score falls in a recording: one tempo and start time, sharpened on the accompaniment's note attacks, then any ritardando or held last chord. |
| `choral/reference.py` | Takes a set of practice tracks apart (balanced, accompaniment, "part predominant" or "part muted") into voices alone, accompaniment alone and one part alone, and says how cleanly they separated. |
| `choral/hear.py` | The speech recognizer used as a stand-in for ears. |
| `tools/pdf2score.py` | Reads a vector PDF exported from Finale (Maestro font) straight into the score format: pitches from notehead positions, note values from stems, beams, flags and dots, ties, key changes, and lyrics re-joined into words. Scans still have to be read by eye. |
| `tools/fit.py` | Fits the piano, or the voice, to a recording by rendering on the recording's own timing and comparing mel spectrograms, one setting at a time, with held-out passages as the test. |
| `tools/listen.py` | Uses a speech recognizer as ears: transcribes a render and reports how many of the score's words came through. |
| `tools/check_part.py`, `tools/check_mix.py` | Check a transcription against a recording: pitch-track one isolated part, or test every written note against a recording of all voices. |
| `tools/calibrate.py` | Fits the engine's tone to a recording of a real singer on the same notes. |
| `tools/tone.py` | Tone, harmonic by harmonic: on every held vowel, compares the strength of each harmonic in a real solo recording and in the model. Only harmonic peaks count, so room reverb does not. |
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

- **MUSIC** is a score file ([docs/score-format.md](docs/score-format.md)) or a PDF exported from
  notation software, which `tools/pdf2score.py` reads directly. A scan or photo is a picture, not
  notes, and still has to be transcribed into a score file first - that step is not automated.
- **--accompaniment** sings over a recording instead of the built-in piano. The voices are lined
  up with it automatically: from the written piano part if the score has one, otherwise from a
  practice track of one voice part.
- **--balanced / --predominant / --muted** are practice tracks of the same piece, if you have
  them. They are only listened to (see below); nothing of them ends up in the output.
- **--tune** lets a speech recognizer choose the microphone distance (needs `whisper-cli` and
  `WHISPER_MODEL`).

### What gets estimated for each piece

A piece's settings are worked out once and kept beside the score as `NAME.preset.json`.

| Setting | From practice tracks | Without them |
|---|---|---|
| Tempo, the first beat, ritardandos, the held last chord | Measured: the predominant part is pitch-tracked against the score, the beat grid is sharpened on the accompaniment's note attacks, and only a drift that never returns to the pulse counts as a tempo change | The score's `tempo:` |
| Hall (amount and length) | Matched to how the recorded voices die away after each release | A rule from how short the quick syllables are |
| Accompaniment level | Measured from the balanced mix | A fixed default |
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

Three test pieces so far, all TTBB with piano, each with a real reference recording.

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
| voices alone | 63-71% | 25-33% |
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
  close-miked singer is not right for a section. The first two pieces score as before
  (piece 1: 73-75% voices alone, piece 2: 68-77%).
- A second real singer confirmed two things the scorecard had hinted at: soft singing has slower
  attacks (125 ms against 36 ms at mezzo-forte) and relatively stronger "s". The hiss was raised
  slightly; the attacks are not yet tied to dynamics.

The recognizer's score moves by several points between identical runs, and at these low levels
it cannot tell one setting from another - the tuner now says so and keeps the rule of thumb
instead of picking noise.

None of these numbers says the result would pass for a recording.
