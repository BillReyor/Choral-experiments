# Choral-experiments

A workspace for experiments in synthesized choral music, concert simulation, and
making generated singing easier to understand.

## Experiment ideas

- Synthesize a tenor–tenor–baritone–bass (TTBB) men's chorus with variation in
  individual singers' tuning, vibrato, and timing.
- Explore four-part voicing, piano accompaniment, stereo staging, hall reverb,
  and audience applause.
- Improve sung diction through better consonants, vowel shapes, and word timing.
- Check renders for duration, loudness, pitch, and clipping, then listen to judge
  musical quality and intelligibility.

## Example: “Shenandoah”

An initial experiment outside this repository explored a two-minute simulated
concert performance of the traditional, public-domain song “Shenandoah,” with an
original piano arrangement and 48 synthesized singers (12 per part).

The concept moves from a piano introduction and unison melody over a bass hum to
four-part harmony in a higher key, followed by a quiet vowel ending and applause.
The initial vowel-only vocals lacked consonants, making the words difficult to
understand.

This is a generic men's chorus simulation, not a recreation of the Hartford Gay
Men's Chorus or a model trained on its recordings.

## Planned vocal-clarity workflow

1. Set up a local speech recognizer to establish which words are understood in
   the current render.
2. Refine consonants and vowels word by word, aligning them with the sung notes.
3. Tune choir diction and the accompaniment/reverb mix for clarity.
4. Render a new version and compare recognition results with the baseline.
5. Listen to confirm that the words are clearer and the performance still sounds
   musical; recognition results alone do not establish singing quality.

## Current status

This repository currently contains documentation only. The example generator
(`chorus.py`) and audio render are not included, and there are no installation,
rendering, or speech-recognition commands yet.