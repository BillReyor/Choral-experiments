# Palare-Piano

Give it the sheet music of a piece for men's chorus and it sings it: a simulated choir (tenor 1,
tenor 2, baritone, bass) with the piano. Name your part and it also makes the rehearsal tracks:
your part brought forward, your part left out, your part alone. The singing is done entirely in
code - no samples, no recordings - and can then be given the sound of real men's voices.

## Install (Mac)

1. Open Terminal: press ⌘-Space, type `Terminal`, press Return.
2. Paste this line and press Return:

   ```
   curl -fsSL https://raw.githubusercontent.com/BillReyor/Palare-Piano/main/install.sh | sh
   ```

3. A few minutes later it says it is installed, and Palare Piano opens in your browser.

After that you never need Terminal again: open **Palare Piano** from the Applications folder in your
home folder, or find it with Spotlight.

It needs a Mac with an Apple chip (M1 or later), macOS 14 or later, about 1.5 GB of disk, and the
internet while it installs. No password is asked for. If Apple's own developer tools are missing it
asks Apple to install them first - a window opens; click Install. To bring it up to date, paste the
same line again. To remove it: the same line with ` -s -- --uninstall` added after `sh`.

On other computers, or to run it from the command line, see
[docs/install-by-hand.md](docs/install-by-hand.md).

## Using it

- **Add a piece.** Drop the sheet music on the page as a PDF - exported from notation software, or
  a scan. It is read into a score: seconds for an export, about half a minute a page for a scan.
- **Make your tracks.** Choose your part, and you get the full rendering (*balanced*), *voices
  only*, your part *predominant*, your part *muted* (everyone else, to sing against) and your part
  *alone*. They play on the page and are kept in `Music/Palare Piano` in your home folder.
- **Real voices.** Out of the box the choir is the program's own simulated voices: clear, quick
  (a minute or two a piece), and plainly a machine. The page offers to add real men's voices - a
  4 GB download, once. With them a piece takes far longer, roughly ten minutes for every minute of
  music with twelve singers to a part, and sounds like a choir.
- **When something is wrong.** The page says where the reader was unsure, and when no tempo was
  printed and it had to guess. *Correct the score* opens what was read as text
  ([docs/score-format.md](docs/score-format.md)); fix the note or the word, save, and make the
  tracks again - only the corrected phrases are sung again.
- **Nothing of yours leaves the computer.** The music and the tracks stay on it. The internet is
  used to fetch the program's own parts, when it is installed and when real voices are added.
  Two of those parts would report their use to their makers; they are told not to.

## Known limitations

- **It has never been listened to by its author.** Every judgement behind it is a measurement:
  against isolated recordings of real singers, against accompaniment tracks, and by a speech
  recognizer. Trust your ears over its reports.
- **Men's chorus only** (TTBB, TTB, soloist or trio over the choir), with piano or unaccompanied.
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

## More

- [docs/install-by-hand.md](docs/install-by-hand.md) - other computers, and the command line: an
  accompaniment recording instead of the built-in piano, learning from practice tracks, your own
  voice for the singers.
- [docs/how-it-works.md](docs/how-it-works.md) - what each file does, how PDFs are read, what is
  estimated for each piece and from what.
- [docs/score-format.md](docs/score-format.md) - the plain-text score format.
- [docs/journal.md](docs/journal.md) - the record of every test piece: what was measured, what was
  changed, and what did not work.
- `experiments/` - the stand-alone experiments that led here.

Audio, sheet music and transcriptions of copyrighted arrangements are never committed
(`.gitignore` blocks them, along with per-piece settings).

## Licence

Copyright (C) 2026 Bill Reyor. Palare Piano is free software: you may redistribute and change it
under the terms of the [GNU General Public License](LICENSE), version 3 or (at your option) any
later version. It comes with no warranty.
