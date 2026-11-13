# About Palare Piano

The [README](../README.md) says how to install it and use it. This page is the rest: what it
cannot do, where the name comes from, and whose work it stands on.

## What it cannot do (the full list)

- **It has never been listened to by its author.** Every judgement behind it is a measurement:
  against isolated recordings of real singers, against accompaniment tracks, and by a speech
  recognizer. Trust your ears over its reports.
- **Tenor and bass choirs only** (TTBB, TTB, soloist or trio over the choir), with piano or unaccompanied.
- **Reading scans is imperfect.** Typically 96-99% of the notes are right. About one syllable in
  ten is wrong or missing, more with Tesseract. (A PDF exported from notation software is read
  exactly instead, from its own symbols - in a current music font or Finale's older Maestro;
  "8va" lines are not followed yet. A PDF that stores its music font under private numbers is
  recognized like a scan.) Repeats, D.S., codas and numbered endings are followed - numbered
  endings have been met in one piece so far. Always look through the `.score` file it writes.
- **Words:** English (by dictionary) and church Latin (by rule); which of the two a scan is in
  is told from its words (`--language` overrides). A word the dictionary does not
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
  about three quarters until the next "a tempo". With no tempo on the page at all the program
  guesses, and says so in capitals: 120 for a notation-software export (the speed such software
  plays an unmarked score at), 100 for a printed page. The accompaniment is the built-in piano playing
  the piano staves, with no pianist's judgement. An instrument's staff in the score (a clarinet, a
  flute) is played by the same piano, so its tune is there when the choir is silent; drums are
  left out, and so is a part written for a transposing instrument.
- **Slow.** Half a minute a page to read a scan; about a minute to sing a three-minute piece with
  the built-in voices, and half an hour or more with real ones.
- **The one-step installer is for Apple-chip Macs**, and has been run from nothing on one of them.
  Real voices have been tried on no other kind of computer.

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

The name is also a play on **player piano**: the piano that plays itself from a roll of punched
paper. This program is one for a choir - it reads the page and performs it with nobody there.
Kurt Vonnegut's first novel, [*Player Piano*](https://en.wikipedia.org/wiki/Player_Piano_(novel))
(1952), makes that instrument the emblem of a world where machines do the work, and it plays in
the bar where the people they replaced go to drink. The name keeps the book in view: what this
makes is a practice track, something to learn a part from. The singing stays with the singers.

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
- **Real voices** are made by [Seed-VC](https://github.com/Plachtaa/seed-vc) (GPL-3.0), fetched when
  you add them and run as its own program. The small driver that runs it (`choral/seedvc_driver.py`)
  follows Seed-VC's own code, which is why this whole project is under the GPL.
- **Each re-voiced singer's tone** is rebuilt with [WORLD](https://github.com/mmorise/World) (Masanori Morise;
  modified BSD) through [pyworld](https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder)
  (MIT).
- **Reading scans** is done by [homr](https://github.com/liebharc/homr) (AGPL-3.0), likewise
  installed and run separately.
- **Listening checks** use [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (MIT) with
  OpenAI's Whisper models; **pronunciation** uses the CMU Pronouncing Dictionary.

## Licence

Copyright (C) 2026 Bill Reyor. Palare Piano is free software: you may redistribute and change it
under the terms of the [GNU General Public License](../LICENSE), version 3 or (at your option) any
later version. It comes with no warranty.

## How it was made

[journal.md](journal.md) is the record of every test piece: what was measured, what was changed,
and what did not work. [how-it-works.md](how-it-works.md) says what each file does.
