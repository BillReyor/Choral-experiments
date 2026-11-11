# Choral-experiments

Experiments in synthesizing a men's chorus (tenor 1, tenor 2, baritone, bass) entirely in code —
no samples and no recordings — and in rendering written sheet music with it.

## What is here

| Path | What it is |
|---|---|
| `choral/voice.py` | The voice engine. Each singer is simulated: vocal-fold pulses one at a time, breath noise, a moving vocal tract, and a "brain" that hunts for pitch, enters late or early, and drifts with its section. |
| `choral/score.py`, `choral/lyrics.py` | Reader for a plain-text score format that mirrors the printed page, and the sung-text-to-phoneme step. See [docs/score-format.md](docs/score-format.md). |
| `choral/piano.py`, `choral/render.py` | Piano, stage (48 singers on risers in front of a stereo pair, section leaders on close mics), hall, mix. |
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

On the first real test piece (an 83-measure TTBB arrangement with piano), the transcription
matched a real baritone's isolated track on every one of 335 notes.

The voice model has been fitted to that singer with `tools/realism.py`. What the scorecard
changed, each from a measured gap:

- upper harmonics were far too noisy (4 dB over the noise against his 23 dB) — jitter and breath cut
- held notes sagged, and consonants took too much of each note — consonants shortened
- held vowels were frozen in tone — the mouth and larynx now keep moving slightly
- pitch now scoops into phrase starts, glides faster with a little overshoot, dips on voiced
  consonants and starts sharp after unvoiced ones
- vowels moved further forward, as he places them; loudness rises with pitch

A speech recognizer makes out about 65-70% of the words in the synthesized voices, against
about 76% for the real singers on the same piece. The scorecard only measures what it measures:
agreement on these numbers does not mean the result would pass for a recording. The piano is
basic, and instruments that are not in the vocal score (percussion, strings) are not rendered.
