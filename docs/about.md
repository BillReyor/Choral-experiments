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
- **Swing is the long-short eighth notes and nothing more.** Where the music is marked "swing" the
  eighths go two to one, and a bracket marked "straight" is sung evenly. The accents and the
  laying-back that make swing swing are not attempted.
- **Spoken notes are a first attempt.** Notes with an x for a head are said in rhythm, each singer
  at a speaking pitch of his own, falling through the syllable. A recognizer understands them at
  least as well as the same words sung; whether they sound like men speaking has been judged by
  no ear yet. They are read from a PDF exported by notation software; on a scan, mark them in
  "Fix a note or a word".
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
- **Windows and Linux are newer than the Mac, and less tried.** The one-step installers have been
  run from nothing on an Apple-chip Mac, on Ubuntu 24.04 (in a container on an ARM chip, and on
  GitHub's Intel-kind machines) and on GitHub's Windows machines, where a test then opens the
  installed program and does what a singer does with the demo piece. No person has yet used it on
  a Windows PC, and no sheet music has been read on Windows: only on the Mac and on Linux, where
  three pieces were read the same as on the Mac (the two notation-software PDFs line for line; the
  scan with the same notes but for two lines, and the words as well as each system's version of
  Tesseract reads them).
- **Real voices are for Apple-chip Macs only.** They have been tried on no other kind of computer.
- **On Windows and Linux the words of a scan need Tesseract**, which the installer does not add
  (it wants an administrator). Without it a scan is read with its notes and no words.

## The name

It means three things at once.

- **Palare** is one spelling of [Polari](https://wp.lancs.ac.uk/fabulosa/whats-polari/): the slang
  gay men in Britain spoke among themselves, in the years when being found out could mean prison,
  so that nobody nearby could follow. The word is the Italian *parlare*, "to talk".
- **Piano** is the instrument under the voices here, and the Italian for "softly". *Parlare
  piano*, to speak quietly, is what Polari was for.
- Said aloud, it is a **player piano**: the piano that plays itself from a roll of punched paper.
  This program is one for a choir. It reads the page and sings it with nobody there. Kurt
  Vonnegut's novel [*Player Piano*](https://en.wikipedia.org/wiki/Player_Piano_(novel)) (1952)
  made that instrument the emblem of machines doing people's work, and the name keeps the warning
  in view: what this makes is a practice track. The singing stays with the singers.

Gay choruses are the other half of that history: the same people, no longer keeping their voices
down. The first to put the word "gay" in its name, the
[San Francisco Gay Men's Chorus](https://www.sfgmc.org/our-story), sang in public for the first
time on 27 November 1978, at the vigil on the night Harvey Milk and George Moscone were killed.
[GALA Choruses](https://en.wikipedia.org/wiki/GALA_Choruses) now counts more than two hundred.
This program was written to help one of them learn its notes.

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
- **Tracks on Windows and Linux** are saved as MP3 by [LAME](https://lame.sourceforge.io/) (LGPL)
  through [lameenc](https://github.com/chrisstaite/lameenc); a Mac uses its own converter.
- **Installing** is done by [uv](https://docs.astral.sh/uv/) (Apache-2.0 or MIT), which fetches the
  program's own Python.
- **Listening checks** use [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (MIT) with
  OpenAI's Whisper models; **pronunciation** uses the CMU Pronouncing Dictionary.

## Licence

Copyright (C) 2026 Bill Reyor. Palare Piano is free software: you may redistribute and change it
under the terms of the [GNU General Public License](../LICENSE), version 3 or (at your option) any
later version. It comes with no warranty.

## How it was made

[journal.md](journal.md) is the record of every test piece: what was measured, what was changed,
and what did not work. [how-it-works.md](how-it-works.md) says what each file does.
