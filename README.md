# Choral-experiments

Experiments in synthesizing a men's chorus (tenor 1, tenor 2, baritone, bass) entirely in code —
no samples and no recordings — and in rendering written sheet music with it.

## What is here

| Path | What it is |
|---|---|
| `choral/voice.py` | The voice engine. Each singer is simulated: vocal-fold pulses one at a time, breath noise, a moving vocal tract, and a "brain" that hunts for pitch, enters late or early, and drifts with its section. |
| `choral/score.py`, `choral/lyrics.py` | Reader for a plain-text score format that mirrors the printed page, and the sung-text-to-phoneme step. See [docs/score-format.md](docs/score-format.md). |
| `choral/piano.py`, `choral/render.py` | Piano, stage (48 singers on risers in front of a stereo pair, section leaders on close mics), hall, mix. |
| `tools/pdf2score.py` | Reads a vector PDF exported from Finale (Maestro font) straight into the score format: pitches from notehead positions, note values from stems, beams, flags and dots, ties, key changes, and lyrics re-joined into words. Scans still have to be read by eye. |
| `tools/fit.py` | Fits the piano, or the voice, to a recording by rendering on the recording's own timing and comparing mel spectrograms, one setting at a time, with held-out passages as the test. |
| `tools/listen.py` | Uses a speech recognizer as ears: transcribes a render and reports how many of the score's words came through. |
| `tools/check_part.py`, `tools/check_mix.py` | Check a transcription against a recording: pitch-track one isolated part, or test every written note against a recording of all voices. |
| `tools/calibrate.py` | Fits the engine's tone to a recording of a real singer on the same notes. |
| `tools/realism.py` | Scorecard: renders one simulated singer on a part and measures it beside a real singer's isolated recording of the same part — pitch glides and scoops, attacks, how notes are held, harmonics versus noise, consonant strength. |
| `experiments/` | The stand-alone experiments that led here (a vowel-only "Shenandoah", and an original pop number in three engine generations). |
| `scores/demo_shenandoah.score` | A short public-domain example. |

## Rendering a score

```
pip install -r requirements.txt
python -m choral.render scores/demo_shenandoah.score out/demo.wav --voices out/demo_voices.wav
```

The workflow for a new piece of sheet music:

1. **Transcribe** the pages into the score format. Every line has to add up to its measure, so
   most rhythm misreadings are caught immediately.
2. **Check** it, if a recording exists: `tools/check_part.py` against an isolated part (two
   mixes that differ by one voice can be subtracted to isolate it), `tools/check_mix.py` against
   all voices.
3. **Render**, then **listen by proxy** with `tools/listen.py`, and compare with the same tool
   run on a real recording.

## What is not here

Audio, sheet music, and transcriptions of copyrighted arrangements are never committed
(`.gitignore` blocks `*.wav`, `*.mp3`, `*.pdf` and `scores/private/`). Renders go to `out/`.

## Honest status

Two test pieces so far, both TTBB with piano, each with a real reference recording.

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

**Piano.** Fitted with `tools/fit.py` to the second piece's accompaniment track (distance on
held-out measures 8.6 dB -> 5.7 dB): sustain pedal, a longer aftersound, a warmer soundboard,
voiced chords. Instruments that are not in the vocal score (percussion, strings) are not rendered.

None of these numbers says the result would pass for a recording.
