# Journal: what was measured, piece by piece

This is the working record of the project: every test piece, what it showed, what was changed and
what the change was checked against. It is long and in the order things happened. For what the
tool does and how to run it, see the [README](../README.md); for how it works, see
[how-it-works.md](how-it-works.md).

Nobody in this project can listen to the output: every judgement here is a measurement - against
isolated recordings of real singers, against the accompaniment tracks, or by a speech recognizer
standing in for ears. The pieces are copyrighted arrangements with purchased rehearsal tracks, so
they are not named and nothing of them is in the repository.

Eight test pieces so far, for men's voices, each with a real reference recording.

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
differs. All eleven isolated real singers take about 20 seconds.

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

- *Tone above 3.5 kHz.* The model had a peak around 4 kHz that the singers do not (10 dB, 10 of
  11 singers) and too little above 5.6 kHz while a note is held (12-16 dB, 11 of 11). It is the
  voice, not the recordings' noise: that band stands 10-31 dB above its own level in the rests.
  The earlier tone fit could see neither - it compared harmonic peaks only, in wider bands.
  (Fixed: see "The highs" below.)
- *Loudness through a note* within 2 dB of the real singers for the first three quarters of a
  note, in the room as well: the note shaping holds. In the last fifth the model is 3-4 dB louder
  (9 of 11): the singers let go of a note a little sooner.
- Smaller things on some singers only: after a consonant the model's brightness arrives 20-40 ms
  sooner than the singers' (7-8 of 11), and in two pieces the real singers grow much louder on
  their high notes than the model does (8-14 dB against 2-4).

**The highs.** That tone difference is fixed, and finding out what the real highs are made of
decided how. In each band the spectrum of a held note either ripples at the spacing of the sung
pitch (harmonics) or does not (noise). From 1.8 to 3.6 kHz the real voices ripple as strongly as
the model's; above 5.6 kHz they hardly ripple at all: up there a sung note is mostly the breath in
the tone, about 47 dB under the whole voice, and between 3.6 and 5.2 kHz it is a mix. The model
had clean harmonics in both places - 26 dB too little of them at the top, and for tenors 20 dB
too much around 4 kHz. Its breath could not help: passed through the row of resonances that
shapes the vowels, noise arrives up there 70 dB down, however much of it there is. So the bright
part of the breath now has a shape of its own (`AIR` in `choral/voice.py`: nothing below 2.5 kHz,
full by 5 kHz), the upper resonance of the voice sits 200 Hz lower, and the harmonic tone curve
loses its peak at 4 kHz. On the eleven singers every band from 100 Hz to 7.5 kHz is now within
2.1 dB of the median real voice (it was +10 dB at 4 kHz and -17 dB at 7.5 kHz), and between 2 and
5 kHz the model's harmonics stand 25-30 dB over its noise where the singers' stand 23-27 (it was
8-10 dB cleaner). The recognizer is unmoved: eight single voices average 1.5 points lower, three
full choirs 3 points higher, both inside its noise.

**Soft entries.** One difference at the start of phrases was real. In soft music the model's
entries after a rest reached a usable level (12 dB under the note) 100-130 ms after the beat; the
real singers' get there in 13-42 ms, and at mezzo-forte the two agreed. The cause was a slow
start laid on top of the new swell. Starting the whole entry earlier put the timing right but
cost words (80% -> 67-71% on the soft solo), so instead a phrase whose first note swells now
begins quickly and leaves the growing to the swell: 55-63 ms, the first tenth of such a note
within 2-6 dB of the singers' instead of 4-8, and the recognizer unchanged within its noise (soft
solo 80% -> 80%, its baritone 48 -> 45, two voices of the unaccompanied piece 48 -> 48 and
46 -> 43, the full choir 58 -> 60).

**Voices against the accompaniment.** A fault that none of the measurements above could see, and
that was heard, not measured: in the carol the voices ran behind the accompaniment, then rushed to
catch up. Each voice had only ever been checked against its own isolated track. Checked instead
against the accompaniment's own note attacks, the tempo map was 150-400 ms out for most of the
piece. It had been blended from maps fitted to two singers separately, which disagreed by a third
of a second, and it assumed a faster last verse because a tempo mark said so; the recording keeps
its tempo.

Now the accompaniment leads (`timing.track`). The written piano attacks and every isolated voice
are followed through the piece together: the piano says exactly where a beat falls, but an even
pattern fits a beat further on just as well; a melody is only good to a tenth of a second, but
fits in one place. The path through both may drift freely with the tempo, and a sudden move - a
held chord, a breath before a new verse, a section in a tempo the score did not promise - has to
be worth a fixed price. On the carol the soloist's notes are 100% on pitch where the new map puts
them and the baritone's 94% (85% before, with whole passages off), and the voices are within
60 ms of the accompaniment in 85 of 90 stretches. The program now reports both numbers on every
run with practice tracks. It also says where the recordings do not fit the score as read: here the
written introduction is five seconds longer than the played one, and the baritone's last five
measures were misread from the scan - the timing there carries on in the tempo it had.

**The seventh piece** (a quick waltz for four-part men's choir and piano, 15 scanned pages, English
with transliterated Hebrew) is laid out as none before it: every voice part on a staff of its own
above the piano, six staves to a system, and the barlines do not run from one voice's staff to
the next. Three things had to change in the scan reader:

- *Systems read in parts.* Given such a system whole, the recognition engine read two in three of
  them as a pile of piano systems. What is on the page is known beforehand - how many staves, and
  which two are the piano's - so a reading that does not match is now done again in parts: the
  voices' staves alone, the piano alone, and if need be each voice by itself. All 27 six-staff
  systems then came back with the right staves and equal numbers of measures.
- *One system, even across a fold.* Where a crease in the paper broke the line joining voices and
  piano, the piano had been taken for a system of its own (and its measures counted twice).
- *Barlines on a photocopy* are grey, thin and broken: found now staff by staff with a vote, at a
  gentler threshold. A third of the systems still come out one barline wrong.

The three earlier scans grade exactly as before against their hand transcriptions (pitch and
length right 95.8 / 96.6 / 96.9%). On the new piece there is no hand transcription to grade
against, but the real baritone is: sung on the timing found, 95% of his notes are on the pitch
the reader wrote, and the first, steady fit of the timing had already put 100% of them there.

Timing: one tempo throughout, and here the follower rightly did nothing (the map moved by 0 ms;
voices within 60 ms of the accompaniment in 95 of 95 stretches). It first did harm, though, and
that led to two more repairs. The piece's verses repeat, and a verse fits the next verse's place
nearly as well as its own: a sudden move now has to be worth several stretches of clearly better
fit, and a followed map that agrees with the recordings less than the first, steadier one did is
thrown away. And the isolated baritone the follower listened to was poor - 56% of his notes on
pitch where taking the other voices out level for level gives 94%: the "part muted" track had
been scaled by how much of the full choir it explains, which overshoots.

Words: the reader gets most of them, the transliterated ones with gaps. Judged against the text
as read, the recognizer hears 38% of the words in the rendered choir and 33% in the real one, 34%
and 29% for the baritone alone.

Against this baritone the comparison says the model is too bright between 1.7 and 4 kHz (up to
14 dB - one singer; the tone is fitted to the median of eleven) and that the first note of a
phrase begins too softly. The entry speed measured from the recording made that worse, not
better, so that correction is now kept small.

**How notes end.** The one difference the comparison showed on nearly every singer after the highs
were fixed: the model's notes ended 3 dB louder than real ones. Sorted by what follows the note,
the reason is plain. Inside a melisma a real note ends as level as the model's. Where the next
note brings a new syllable, the real voice fades over the last third of the note - by 3-4 dB more
than the model, more on a long note, hardly at all on a short one that already ends in a
consonant. So each syllable's vowel now fades toward the next syllable (`taper`), timed to the end
of the vowel, not of the note, and the consonant that follows is sung at its own level: the vowel
comes down to meet it. On twelve singers, each compared in its own room, the last three tenths of
a note are now within 0.7 / 1.7 / 1.8 dB of the real ones (they were 1.5 / 2.8 / 2.6 dB too loud).

The fade that is measured per piece from a recording had to change with it. It used to assume the
model's own notes fall 2 dB a second; they fall faster now, and how fast depends on the piece. So
the model's own fade is measured too, on the same notes and in the recording's room, and the
piece's setting is the difference.

The recognizer: eight single voices average 63.6% with the taper against 63.9% without, and three
full choirs move by +3, -1 and -7 to +13 points depending on which singers are drawn. One voice is
clearly worse for it, a pianissimo solo (80% -> 73%); easing the taper there did not bring it
back, and it is left as measured on the real singers.

**The eighth piece** (a quick, wordy, chromatic number; a PDF exported from notation software in a
music font the shape reader does not know) first came back as an empty score: the shape reader
found no notes and said nothing. Now the program notices, renders the pages and reads them as a
scan - and takes the words straight from the PDF's own text, which is exact and needs no text
recognition on any system. Voices within 60 ms of the accompaniment in 118 of 120 stretches; the
recognizer hears 55% of the words in the rendered choir against 57% in the real one (59% against
62% for the baritone alone). 87% of the baritone's notes match the real singer by the usual
check; the next entry shows that this is the check's limit on such music, not the reader's.

**Words without macOS.** Reading words off a scan used macOS's text recognition only, so on Linux
or Windows a scan came out with notes and no words. Tesseract is now used where macOS's
recognizer is not available (`SCAN_OCR=tesseract` forces it). On the two English scans with hand
transcriptions it puts 81% and 72% of the syllables on the right note, against 89% and 90%.

**A second reader: Audiveris.** Would the long-established open-source reader
[Audiveris](https://github.com/Audiveris/audiveris) (5.11) do better than the recognition engine
used here? Both were graded the same way - the notes of the tenors' and the basses' staff as a
sequence, against the verified hand transcriptions of three scans:

| | current reader: pitch right / pitch and length right | Audiveris |
|---|---|---|
| piece 1, a phone scan (tenors, basses) | 97.5 / 95.0%, 99.8 / 92.6% | 62.9 / 46.3%, 91.9 / 53.0% |
| piece 3, a scan | 96.8 / 94.1%, 99.6 / 96.1% | 72.7 / 66.8%, 71.0 / 66.3% (one page of nine crashed) |
| piece 4, a scan | 98.5 / 95.5%, 98.5 / 97.1% | 82.4 / 69.9%, 86.4 / 72.8% |

On scans it is clearly worse, and it has to be run a page at a time: in batch mode one page it
cannot read (or crashes on) stops the whole piece from being exported. On the photocopy of the
seventh piece it puts 66% of the baritone's notes where the real baritone sings them, the current
reader 76% by the same strict count.

On the eighth piece, a clean PDF, the two are equal - and that settled something else. Of 471
baritone notes that both place identically and the real singer can judge, the two readers give
the same pitch for all but five. Two independent readers agreeing on 99% of the notes means the
reading is right; the "87% of the notes match the real baritone" reported above is the limit of
that check on quick, wordy singing (short notes, slid pitches), not of the reader. Where both
readers differed from the singer, he was not singing another written note of the chord either.

What Audiveris does better: it understood every layout at once, including the six staves to a
system that the current engine has to be given in parts; it invents fewer notes; and it is
quicker (about 8 seconds a page against 30). It can read words too, but only with Tesseract's
older language data installed, which was not tried. It is an 80 MB Java program with a licence
to click through, against one `pip install`.

So the current reader stays. The use for a second reader is as a second opinion on clean PDFs:
where two independent readings agree, the note can be trusted without a recording to check it
against. That is not built.

**Reading a notation-software PDF exactly.** The eighth piece's PDF is not a picture. Every
notehead, rest, accidental, flag and clef in it is a character of a music font at an exact place,
and every staff line, stem, barline and beam is a line. Its font, like nearly all current ones,
follows one standard (SMuFL) that gives each symbol the same code in every font. So nothing needs
recognizing: `tools/vector2score.py` reads the notes off, and hands them on in the same form a
recognized page takes, so that everything after the notes is shared.

It was built against the page reader's version of the same piece, and wherever the two differed
the picture was looked at. In the voice parts they differ in about twenty measures of 130, and
the symbol reader is right in each one looked at: a double sharp the page reader took for a
natural; an eighth rest and three sung notes it missed entirely; ties it dropped; the last
measure of the piece, which it lost. What had to be got right along the way:

- a barline and a stem can both run exactly from the top line to the bottom line: barlines are
  drawn heavier, and stand on most staves at once;
- accidentals stand in columns left of a whole cluster of noteheads (a chord, a second pushed
  to the other side of the stem, another voice set a little apart), not next to their own note;
- two voices on a staff: notes that sound together stand one above the other, so each measure is
  read column by column with each voice's next moment kept; a chord on one stem at a moment when
  the other voice is due too belongs to both, and one voice may point its stems now up, now down;
- a notehead belongs to the stem that ends at its own height (two voices a second apart share
  one vertical line for their two stems);
- every note of a dotted chord has its own dot: what counts is how many dots stand side by side;
- a triplet's bracket is drawn as thin filled shapes, and cue-size notes are not sung.

On this piece: 130 measures, every one the right length; 471 of 479 staff-measures add up by
themselves (the rest are piano flourishes in fives and sevens); voices within 60 ms of the
accompaniment in 117 of 117 stretches. It reads in two seconds instead of a minute and a half and
needs neither the recognition engine nor text recognition. If a PDF's symbols do not add up as
music, it says so and the pages are recognized instead. Not handled yet: "8va" lines, first and
second endings - and it has met exactly one file.

**The ninth piece** (a quick comic number for four-part men's choir, clarinet and keyboard; an
18-page PDF from notation software, 83 measures; balanced mix, accompaniment, "baritone
predominant" and "baritone muted" tracks) was sent as a second file for the exact reader. It is
not one. It comes from older software, whose music font predates the standard, and the file
stores both its music symbols and its words under codes of its own. So the pages were recognized
like a scan - and a clean, wide-open score with an instrument in it found more weak spots in that
path than any scan had.

*Reading the notes.*

- **Text that is not text.** The PDF does carry its words as text, but as garbage letters. A PDF's
  text is now trusted only if four tokens in five look like words; otherwise the page is read by
  sight.
- **Staves are named, not counted.** Until now, which staff is whose was told from how many there
  are. Here that changes from page to page: four voices and keyboard, the same with a clarinet on
  top, the two low voices under the clarinet, the clarinet with keyboard alone. The names printed at the left of
  the staves are now read: tenor or bass with a number, "Bar.", instrument names and their
  abbreviations, and a keyboard's name standing between the two staves it means. A system without
  names takes those of the last system with the same staves and clefs. A name set in several lines
  beside one staff ("Tenor" with I and II, "Baritone" over "Bass") names a staff that carries two
  parts. An instrument's staff is read and left out; systems that are an instrument alone (its
  part, printed after the score) are dropped.
- **A staff the engine did not find.** Under two long slurs it reported no staff at all, and where
  a slur hid a staff's beginning it split one system in two. Systems are now joined across such a
  break, and five evenly spaced lines standing between two found staves are taken for the staff
  they are. That adds this one staff, and none among some 800 staves of six earlier pieces.
- **A clef misread.** In one system the baritones' bass clef was read as an alto clef and the
  basses' as a treble clef - also when each staff was read again alone - so every note stood a
  seventh or a thirteenth off. A part keeps its clef through a piece: a staff read under another
  clef than its part has in at least three systems of four has its notes moved to where the usual
  clef puts them, key signature respected. Checked against the page: all twelve notes right.
- **A tempo mark** with a triplet's "3" printed between the "=" and the number was missed; marks
  are now matched line by line. The three tempos (120, 68, 120) were then found from the print,
  and the accompaniment agrees: 120.0, 67.7, 120.0.
- **The "muted" track** is not the balanced mix without the baritones here: taking it away leaves
  something louder than the voices. The program notices and isolates the part from the
  "predominant" track instead.

*The words* took the most work, and what was wrong was general.

- **Print size.** Lines of words were told apart, and each read again close up, in a band sized by
  the staff. This score has large print under small staves: one line of text was taken for two,
  and the close-up cut the tails off y, p and j, which then read as v, n or b, and i. The sizes now
  come from the print itself.
- **Where a note stands.** The engine's report of where each note stands on the page can be half a
  note off, and in a staff it read alone it was sometimes nonsense (notes running right to left).
  A measure with exactly as many syllables under it as it has notes to sing them now gets them
  one each, in order, whatever the positions say; notes reported out of order or outside their
  measure are placed by when they sound.
- **A held vowel read as a number.** An italic "oo" under a long note comes back from text
  recognition as two zeros and was thrown away with the measure numbers. The note, left without a
  word, then took half of whatever word another part was singing, and that half was glued to the
  singer's next word. Zeros are now read as the vowel; and a borrowed beginning of a word that is
  followed by a note with a word of its own is held from the note before, or stands alone.
- **Hyphens.** Of two readings of a word with the same letters, the one that kept its hyphens is
  kept. And the second, close-up look for a syllable under a bare note no longer returns a
  syllable the first look had already given to the note beside it.

Words in this piece that are not dictionary words: 62 of some 630 before; 25 after, of which 22
are seven real words the dictionary lacks and 3 are misreadings. Syllables on the right note in the earlier graded scans:
piece 1 from 89% to 93%, piece 3 from 90% to 92%, piece 4 (Latin) from 90% to 89%. Their notes
are unchanged to the last byte; so are the seventh and eighth pieces'. The fifth piece differs in
one note: a tie across a system break that is not on the page, which the earlier reading had put
in.

**Words the dictionary does not have** were sung on "ah" - every name, every word from another
language, every misreading. Now a word is first looked for under a fuller spelling: a letter left
out for the metre ("ev'ry", "o'er", "singin'"), a letter doubled or not. Failing that it is sung
as it is spelled, by a few dozen English spelling rules that keep vowels plain in open syllables
(what is not in an English dictionary is mostly a name or another language). Measured on 3000
words the dictionary does know: 24% of the sounds differ from the dictionary's (11% of the
consonants), and the number of syllables is right in 87%. A near miss, and the run prints each
one so that a `say:` line can correct it. In the eighth piece one slang spelling, sung on "ah" 48
times until now, is sung as written; in the seventh, the Hebrew.

*The result on this piece.* The recognizer hears 69% of the words in the simulated baritone alone
(57% before the word fixes) and 57% in the first tenor (45%); the real "baritone predominant"
track as given scores 76%. The baritone's notes are on pitch against the real baritone in 97% of
cases at the best steady fit - 76% by the strict count where the followed timing puts each note,
on a part isolated from a track that still has the other voices at a fifth of their level.
Following the recordings moved the timing by 0 ms on average; voices within 60 ms of the
accompaniment in 72 of 73 stretches.

Not built: reading this older family of PDFs exactly. The symbols are all in the file, each under
a private code that keeps the order of the font's own table, so the table can probably be
recovered from a handful of symbols that are unmistakable by position (a clef at the start of
every staff, a time signature after it). Until then such files go the slower way, which this
piece has made a good deal sturdier.

**The tenth piece: a PDF and nothing else** (a slow ballad for a soloist, men's choir in two to
four parts and piano; six pages, 46 measures, exported from Finale in its older Maestro font). No
recording was given: whatever a recording used to supply - tempo, where the music waits, how
loud the piano is - had to come from the page.

*The first run* went through, and was wrong in ways a listener would hear at once. The earlier
reader for this font, built around the first pieces, left 127 staff-measures "to fix by hand" and
was rightly rejected; the pages were then recognized like a scan. That found all 46 measures, but
the tempo was a guess of 100 where the print says "Rubato" and then "Moderately slow", the solo
was an octave too high (its clef has an 8 under it, which a recognized page does not tell), and
the fermatas and rallentandos were not there at all.

*Reading the old font exactly.* `tools/vector2score.py` reads symbols by their standard codes;
Maestro predates the standard. A table of some fifty of its characters now translates them. This
file's maker had stored the font as a "symbol" font, so the characters come out as Greek letters
and mathematical signs, each one place too low; the displacement that makes the page's characters
music is found by trying. Four things about how this software draws had to be learned:

- its barlines are no heavier than its stems: they are told by where they stand (from top line
  to bottom line, on most staves at once);
- a whole note beside stemmed notes belongs to the other voice, and so does one beside a rest
  set high or low for a voice;
- a triplet's number is a letter of a text font, not a music symbol;
- a cue-size note in a chord (an optional high octave) is not the sung note.

174 of 175 staff-measures then add up; the last is a piano measure printed a beat short. It reads
in two seconds.

*Is it right?* There is no recording, but there are two independent readings. They agree on 91%
of the voices' notes and differ in 14 measures. Four of those were looked at on the page. Two
faults of the symbol reader's own showed up there and were fixed: the cue-size note, and a lower
voice that jumped to the upper voice's note while it should rest. With those fixed, every
disputed note in the four measures goes the symbol reader's way: two voices' rhythms told apart,
a double-dotted note, the lower tie of two tied notes. The other ten measures were not looked at;
most differ in that same lower tie. The same changes altered two measures of the
eighth piece, both checked against the page and both now right (a whole note under two moving
half notes; two tenor voices that had been merged into one). Because the two voices of a staff
are known for certain when the symbols are read, each now keeps its own line, silent where it
rests; a recognized page still gets "highest sounding, lowest sounding".

*What a PDF alone needs.*

- **Tempo in words.** With no metronome mark, a heading such as "Moderately slow" or "Andante" is
  looked up in a table ("Moderately slow" 72, "Andante" 76, "Rubato" 63): conventions, not a
  measurement.
- **Holding and slowing.** The score format had one tempo per stretch and nothing else. It now
  has `stretch:` - so many beats take so many times as long - and the reader writes it: a fermata
  adds a beat to a beat and a half to the moment all its signs share; from a "rall." the music
  slows step by step to about three quarters until the next "a tempo" (deeper at the very end).
- **The solo's octave** comes from its clef; **the title** from the largest words on the first
  page; **each word's place** from its own letters (several syllables can share one run of text,
  and their hyphens were being lost); a vowel drawn out in print ("Ooo") is the vowel.

*The result*, as far as it can be measured without the real thing: 2 minutes 43; the recognizer
hears 93% of the solo's words by itself (99% of the letters) and 77-79% in the full mix with
choir and piano. The real practice track of the ninth piece scored 76% by the same yardstick.
Whether it is musical is not something these numbers say: the piano plays the printed notes
evenly, and every hold and every slowing has the same depth.

*A fault found on the way.* A score read from a PDF is kept beside it and used again, so that
corrections made by hand survive. But `--fresh` only measures the recordings again; it does not
read the PDF again. The audio of the ninth piece had therefore been rendered from the reading
made before that piece's own fixes - the report described the new reading, the sound was the old
one. Scores the program reads are now signed: one that nobody has edited is read again when the
reader has changed, and `--reread` asks for it outright. The ninth piece was rendered again: its
baritone is on pitch against the real one in 99% of notes at the steady fit (97% before).

Earlier pieces: the three graded scans read as before (pitch and length 95.8 / 96.6 / 96.9%); the
fifth, seventh and ninth pieces' readings are identical to the previous reader's.

*What a listener heard at once, and no number of mine had said.*

- **"There was no music in the accompaniment."** The built-in piano was mixed 12 dB under the
  voices: a default set before any real mix had been measured. The seven real practice mixes
  measured since have their accompaniment at 0.44 to 0.94 of the choir's level, 0.51 in the
  middle; the default is now 0.5, about 5 dB under the voices. The piano's tone was not at
  fault: band by band it lies inside the spread of the eight real accompaniment recordings. The
  sign had been in my own figures, unread - "balanced" and "voices only" measured within 0.2 dB
  of each other. A piece's saved settings now hold only what was measured or chosen for that
  piece, so that a default that improves reaches the pieces that never had a recording.
- **A word with the wrong vowel.** For words spelled alike and said differently the dictionary
  lists both readings without saying which is which, and the engine took the first: the verb's
  vowel on a plural noun. A table of some twenty such words now gives the reading a song usually
  means, with the word before or after deciding a few. It corrects two earlier pieces as well,
  where a verb had been sung as its adjective through a whole refrain, and a noun as its verb.

Not done: a Finale PDF that stores its font under private numbers (the ninth piece) is still
recognized like a scan; three notes on one staff for two parts lose the middle one; two syllables
printed touching, without their hyphen, arrive as one word on one note; "8va" lines and first and
second endings.

**A real voice's sound.** After the tenth piece the listener asked whether anything could
*radically* improve the voice. The honest answer was: not inside this method. One more candidate
was checked first - vibrato, on the thought that a soloist's might simply be missing. It is not:
on held notes the real singers on hand swing by 4 to 8 cents (median), the simulated ones by 5 to
7. (The real ones let a clear vibrato bloom on 5-25% of their held notes, the simulated on 1-3%;
small.) Tone, note shapes, entries, steadiness and now vibrato all match by measurement, and the
voice is still heard as synthetic. What is left is the texture of a rule-built voice, for which
there is no number here.

So the sound was taken from elsewhere, and only the sound. A voice-conversion model (Seed-VC's
singing model; an outside program, installed apart from this repository) takes each simulated
singer's dry track and a short recording of a real voice, and returns the track in that voice.
`choral/revoice.py` cuts every singer's part into its stretches of singing, hands them over, and
puts what comes back in place: lined up with the original (the model was 0-10 ms off) and at the
original's loudness moment by moment, so that the note shapes fitted to real singers survive. It is
an option, `--voice`; without it nothing has changed and the program is still all code.

Measured on the tenth piece, engine voice against re-voiced:

| | engine voice | re-voiced |
|---|---|---|
| a soloist alone: words the recognizer hears | 97% | 89-94% |
| each note against the written pitch (typical) | 6 cents | 7-9 cents |
| four baritones: each off the written pitch (typical) | 6 cents | 8 cents |
| four baritones: apart from each other on a note (typical) | 6 cents | 9 cents |
| four baritones together: words of the section | 72% | 91% |
| the soloist's words in the full mix with piano | 81% | 87% |

Ten refinement steps measured the same as the model's default thirty and convert twice as fast as
real time on an Apple M5: a piece with thirty minutes of singing (seventeen singers) takes a
quarter of an hour. Putting the stretches back had at first taken longer than converting them -
loudness was being smoothed sample by sample over minutes of sound.

The listener's verdict on a like-for-like excerpt (same piano, same hall): "Yes, clearly" more
like a real person. That, not the table, is the result; the table only says that nothing the
engine does well was lost on the way, and that a section came out easier to understand.

What this is not yet: a men's chorus. The only voices tried are the model's own anonymous sample
voices, which are high ones; a section in real men's voices - the user's own, and those of singers
who agree - has not been heard. The singers on the practice tracks are not used as voices: nobody
asked them. And the model has its own share in what is sung now: it moves more inside a note
(15 cents against 9), and what it does to consonants is judged only by the recognizer.

None of these numbers says the result would pass for a recording.

**Men's voices.** Offered the choice between recording their own voice and other voices, the listener chose
other voices. The ones found: VocalSet (Wilkins, Seetharaman, Wahl and Pardo, ISMIR 2018;
Creative Commons Attribution 4.0) - twenty professional singers recorded alone for research,
eleven of them men, each singing the same scales, arpeggios and three songs in many manners. Ten
are used (the eleventh is a countertenor), and of each only fourteen seconds of one song sung
plainly: eight seconds described a voice slightly less well, twenty-two no better, and a longer
recording leaves the model less room for the singing, so it also costs time.

*Who sings what.* The plan had been to seat voices by pitch - the lowest recording to the basses.
These men all sing the same songs in the same key, so pitch says nothing. What tells a bass from
a tenor there is the size of the voice: a longer throat and mouth put every resonance lower by the
same ratio, which on a logarithmic frequency axis is a shift. Measured on three songs, each man
against the average of the others, the ten spread over 3.2 semitones (-1.5 to +1.75), and each of
a man's three songs lies within 0.45 semitone of his average, most within 0.2. The largest two
sing bass, the smallest three first tenor. It carries through: the same line re-voiced in all ten
keeps their order (rank agreement 0.83-0.93 on four lines), at half to two thirds of the spread on
the three lower lines and a seventh of it on the first tenors' high one. Since the program cannot
know any of this from a recording, a recording can now simply be named for its part
(`Bass 2.wav`); those without such a name are still seated by pitch.

*Auditions.* One engine singer per part, re-voiced in each of the ten: every man holds the written
pitch everywhere, down to the basses' lowest note (typically 4-12 cents off, as the engine is).
Words on the three lower lines: 77-90% for every man (the engine's own singer: 87%). On the first
tenors' line one run spread from 50% to 83% and a second run, with a different engine singer,
from 73% to 87%: the recognizer on one voice cannot rank voices. Only two men were at the bottom
both times. What did separate them was how clean a held note comes out. Three of the ten return
breathier than they went in: held notes 0.90-0.92 periodic at the written pitch against 0.95-0.98
for the rest and 0.97 for the engine; the level sags 12-13 dB inside a note against 8-11 (the
engine: 7); the pitch tracker loses the middle of 12-17 held notes of 31 against 5-10, on two
draws alike - a property of the voice, not of chance. They sing in sections. The solos went to a
man of a baritone's size from among the clean ones, whose words were also the best by a little
(89-91%; all ten between 74% and 91%, the engine's soloist 97%).

*Is it him?* A speaker-recognition network (the one the model itself describes voices with) scores
a man's own recordings against each other at 0.73-0.96 and against other men at 0.3-0.83. The
re-voiced solo scores 0.73-0.83 against other recordings of the man it was given, and less
against other men in two cases of three; in the third it scores a little higher against another
man (0.78 against 0.75) - the one the engine's own voice happens to resemble most. The sound is
taken from the recording, but not all of it.

*One man six times.* Six engine baritones - six different simulated singers - given the same
recording score 0.98-0.99 against each other: one man multitracked, whatever the engine did. With
two or three recordings for a section of twelve that is what a section would be. So every further
singer on the same recording now gets it slightly larger or smaller: the recording is played a
little slower or faster before the model hears it. Six sizes of one man over 0.9 semitone either
way score 0.87-0.98 against each other and sing the notes and the words as before (typically 11
cents off; the six together 83% of the words against 80%). The program uses up to 0.6 semitone
(3.5%). They are relatives, not strangers; ten men are still ten men.

*Time.* Three copies of the model side by side convert twelve clips in 163 s; one copy, 152 s. The
graphics chip is the limit (of every 8 s spent: 4.7 the refinement, 2.0 turning the result into
sound, 1.2 finding the pitch).

*What the first re-voiced renderings got wrong.* Putting a re-voiced stretch back "as loud as the
original at every moment" limits how far the loudness may be corrected (-30 to +10 dB), so that
silence is not amplified into noise. That limit was applied against the level the stretch happened
to be stored at for the model, not against its own average - and a section singer's track needed
more than the limit allowed. So every re-voiced section singer came back 3 dB quiet, his loudest
moments held back most, and the soloist stood 2 dB further out of the choir than the engine had
put him. It had been checked on one clip, which was stored at the model's scale and passed.
What found it was the dullest possible comparison, made late: one singer's level before and after
(-1.7 against -4.7 dB). A stretch is now first made as loud as its original on the whole, then
moment by moment: twelve baritones measure -1.9 against -1.7 dB alone and 9.3 against 9.3 together.
Everything re-voiced before this, the earlier excerpts included, has the fault.

*An octave that was not sung.* In that section three of twelve re-voiced singers measured an
octave high on one note - an "o" on B flat, whose second harmonic falls on the vowel's resonance.
The spectrum has the written pitch and its third harmonic in all twelve, 20-50 dB above what lies
between harmonics: the pitch tracker was fooled, not the listener. It does show a real difference:
on that note a re-voiced voice's fundamental lies 10-18 dB under its second harmonic, the engine's
2-6. Real voices ring harder on a vowel's resonance than the model does.

*Kept.* The engine sings a piece the same way every time, so a converted stretch is kept
(`.svc/cache`, up to 4 GB, oldest out first) and a later rendering of the piece - for another
part's rehearsal tracks, another balance - finds it done.

*The piece.* The tenth piece in the ten men's voices, four singers to a part, beside the engine's
own voices at the same size, same piano and hall. Words the recognizer gets in the full mix (and
from the voices without piano):

| | engine voices | ten men |
|---|---|---|
| the solo verse | 97% (97%) | 86% (86%) |
| the solo over the choir | 29% (65%) | 65% (76%) |
| the choir's verse | 91% (94%) | 75% (97%) |
| the last chorus | 78% (69%) | 64% (75%) |

One reading each, of 17 to 36 words, so a few points mean nothing. Without the piano the choir
reads as well as before; with the piano, 14-16 points lower; the soloist alone 11 points lower;
the soloist over the choir higher. The balance is the engine's again - soloist
2.5 dB under the choir's verse (engine 2.3), piano 5.1 dB under the choir (5.2). Sixteen minutes
for the piece at this size; with twelve to a part, forty-nine singers and an hour and a half of
singing, fifty-three.

What none of this says is whether it sounds like a men's chorus: that is for a listener. The ten
are trained soloists singing an Italian song alone in a studio, not choristers; there are ten of
them; and nothing here has been set beside a recording of a real choir.

**"Better, but they sound like bad singers."** The listener's verdict on the ten men: more real
than anything before, and bad singing - notes that waver, a weak or strained tone, sloppy words
and rhythm (the words worst on the solo), a tempo that seems to speed up and slow down. Not out
of tune. Each was measured on the re-voiced tracks against the engine's own and against the men's
own recordings.

*Wavering: the model is told the pitch only roughly.* It takes the pitch in 256 steps from 50 to
1100 Hz - 15 cents wide at a first tenor's top notes, 27 at the G below middle C, 43 at a bass's
low A - and sings somewhere inside the step it is given. Inside a held note the re-voiced pitch
drifts 6-8 cents (the engine's singers, and real choristers: 3-4); each note sits 6 cents from
the note of the engine singer it was made from; twelve baritones are 11 cents apart on a note (the
engine's twelve: 7). The engine's pitch is known exactly, so each re-voiced stretch is now put
back on it: the two are tracked, and the re-voiced one is played that many cents slower or faster
wherever both are sung; when that has run a whole period of the voice ahead or behind, one period
is dropped or repeated. After it: drift 3-4 cents, 0.5 cents from the engine singer (92% of notes
within 10 cents, before 63%), the twelve 7 cents apart, words and timing unchanged.

*A glitch every sixteen seconds.* The model works on a window of sound at a time - half a minute
less the recording of the voice - and makes a longer stretch in windows, crossing them over where
they meet: mid-phrase, two different renderings at once, the level 7-8 dB down for a tenth of a
second. With stretches of 24 s on average that was one such moment per stretch, in every singer.
Singing is now handed over in pieces that fit one window, cut at the last rest or breath the limit
allows (36-99 dB down); only the final held chord, longer than a window, is cut in a held note.

*Tone.* Two guesses did not survive. References made from each tenor's own singing in the first
tenors' range (the song lies an octave lower) bring a re-voiced line no nearer to his own tone up
there (4.0-6.7 dB apart either way) and cost words, having no consonants in them. And the men's
mix is not short of ring against the real choristers on hand. What did measure: every man sings
the song twice, normally and "straight", holding his vibrato back, and the straight one had been
used. From his normal singing a re-voiced line has 2-5 dB more ring in six voices of nine and
keeps its words as well or better in eight, no less steady. The sections use it now. The
soloist keeps the straight one: alone, his words came through better from it.

*Words.* The engine's soloist is understood 97%, the re-voiced one 89-94%, and the recognizer
trips over the same words in every voice: an l lost, a final p, "sat" heard as "set". Thirty and
fifty refinement steps instead of ten, holding the model harder or looser to the voice, references
sung in English, the engine's own hisses and clicks put back in place of the model's (they were
only 3 dB weaker): none of it raised the number. Following the engine's loudness every 60 ms, 150
or 300, or not at all, did not either. This softness is the model's own, in how it forms voiced
sounds, and is still there.

*Timing.* A re-voiced track follows its original within 25 ms in every two-second window, mostly
within 10, so the
tempo a listener hears is the one read from the page: "Rubato" over the introduction, "Moderately
slow" from the third measure, four printed rallentandos with their "a tempo". How deep a
rallentando goes is a guess here (to 1.3 times as slow, in steps, and straight back). Note by
note there is something: one note in seven of the re-voiced solo reaches its pitch 30-60 ms later
than the engine's does, and twelve re-voiced baritones start a note 18 ms apart where the engine's
start 11 ms apart.

*The piece again*, four to a part, with the pitch put back, no joins, and the sections' voices
taken from the men's normal singing. The soloist, taken out exactly as the render makes him:

| the soloist's first verse | engine | re-voiced before | re-voiced now |
|---|---|---|---|
| pitch against the engine's, moment by moment: within 30 cents | - | 64-70% of the time | 84% |
| drift inside a held note | 3.8 cents | 7.3 | 3.9 |
| notes reaching their pitch more than 30 ms late | - | 6-7 of 42 | none |
| words | 97% | 86-91% | 86% |

The balance is unchanged (soloist 2.5 dB under the choir's verse, piano 4.8-6.2 dB under the
voices), and so are the words, in the mix as alone. What is left of the rhythm complaint, by
measurement: in one note in five of the whole solo (20 of 93) the sound builds more than 30 ms
later than the engine's, mostly more than 60, after every kind of consonant. Letting the loudness
match raise a quiet moment further (16 or 24 dB instead of 10) changes nothing - the limit is not
what holds it back; the vowel itself arrives late, and moving it would mean shifting sound in
time, which is not built. The price of pieces that fit one window: they are shorter than a window,
so the recording of the voice is worked through more often, and the piece took 39 minutes instead
of 16.

*Speed, and chance.* Pieces of every length cost more than their length: the graphics chip
prepares the model anew for each new length, about two seconds a piece (eight pieces of one
length: 50 s; eight of different lengths: 61 s). The driver now pads each piece to a whole second,
every recording of a voice is cut to the same 13 seconds whatever size it is played at, and pieces
run up to 14 seconds: the soloist's minute of singing converts in 44 s again. None of this touches
the words: over the whole solo (72 words) seven runs with different piece lengths, 13 or 14
seconds of the voice, and different draws read 83-88%, in no order; the engine's own soloist reads
92%. Keeping the clearest of three takes of each phrase would give 89%: the takes stumble over the
same words. So the recognizer's gap is small and what a listener calls bad enunciation is mostly
not in it - it is in how the model moves from one voiced sound to the next, which nothing tried
here changes.

*Where the timing was off.* Asked whether the trouble was at the four marked slow-downs, the
listener said no; asked where, then: "Intro feels fast, but it feels like it resolves itself
around 0:52", and the voices "drift from piano slightly". At 0:50 the choir takes over from the
soloist. What was checked on the way, and was not it: the solo's rhythm as read matches the page
note for note in the measures looked at; the built-in piano's attacks sit within 10 ms of the
clock in every section; the re-voiced soloist follows the engine's soloist within 10 ms; the
soloist is timed no differently from a choir singer.

A false lead cost an hour. One syllable in five of the re-voiced solo looked late by 60 ms or
more, judged by when the loudness comes up, and again judged by the spectrum's changes. A step was
built to move such syllables onto the engine's (reading further on, a period of the voice at a
time). Moving by the first measure made the second measure worse; moving by the second fixed five
starts of sixteen. The lateness was not there: the "late" starts cluster at 105-150 ms, the length
of a consonant, and the pitch of every note begins on time. What the measures were matching was
the engine's strong consonant against the model's weak one, and finding the vowel instead. The
step was thrown away. (A lateness that comes in one size is a mismatch, not a delay.)

What it was: nothing drifting, a placement. The engine starts each vowel on the beat - measured,
about 20 ms before it - with the consonant ahead of that, and the piano plays on the beat. Many
voices blur that into a choir's entry. One voice over a chord a beat is heard ahead of the piano.
No measurement here says where a soloist should sit, so the listener was given the opening four
times - the soloist 35 ms earlier, as sung, 35 ms and 70 ms later - and chose 70 ms later. A part
sung by one person is now placed that far back (`solo_late`), in pieces whose beat comes from the
page; where it was measured from a recording, the singers stay where the recording puts them.

*Consonants, at last.* Everything tried on the model's side had left the soloist's words where
they were. What moved them was on the engine's side: the model blurs the consonants it is given,
so it is given longer ones. Over the whole solo (72 words), four draws each:

| | words understood |
|---|---|
| the engine's own soloist | 66-67 |
| re-voiced, the engine's usual consonants | 60, 61, 61, 63 |
| re-voiced, consonants a third longer | 67, 65, 67, 63 |

A sixth longer gives 64 and 64; a half longer 65 and 62; two thirds longer 67 and 64: the gain is
there from a third on and does not grow. As a twelve-to-a-part render draws him: 59 and 60 of 70
with the usual consonants, 63 and 65 with the longer. A re-voiced section of twelve is understood
the same either way (baritones 87% of their words and 87%, first tenors 83% and 87%: one word), so
only parts sung by one person get them. The
loudness, pitch and timing the result is held to are those of the same longer-consonant singing.

One warning about the yardstick: the same recognizer, on the soloist's four measures over the
humming choir in the full mix, has read 18% to 76% across versions whose soloist alone reads
16 of 17 words. A mix-level reading of a short passage decides nothing by itself.

**"The chorus sounds decent, the solo sounds bad."** On key, in time, "just not an attractive
voice": not what a chorus member should be given to emulate. Attractiveness has no number here,
so the listener was given auditions - the same opening with five soloists - and chose the third, a
baritone, adding that it "still has that slight spasmodic dysphonia sound". Two things were found
on the way, both measurable, both in every re-voiced singer.

*Fizz.* Against the same men's own recordings, a re-voiced voice has too much at the very top. On
sung notes: 11-12 dB too much above 12 kHz straight from the model, and after the putting-back
4-6 dB too much at 5-8 kHz, 5-10 at 8-12 kHz, 12-19 above 12 kHz. Its consonants: 7-10 dB too
bright at 8-12 kHz, 15-18 above. Each re-voiced singer's top end (above 3.6 kHz) is now lowered by
what his sung notes have too much of against the recording of his voice, never raised. For two
soloists that took 7 and 11 dB off the sung notes above 12 kHz and 7 and 11 dB off the consonants
there, with the words where they were (64 and 62 of 70). In the full mix the choir's verse above
12 kHz went from 30 dB under the whole to 40, where the engine's own choir sits.

*Catches.* The description was exact. Count the moments, inside notes the engine sings with a
clear period, where the re-voiced voice has none: the engine itself has none, and the re-voiced
soloists the listener heard had about 7 a second - 12% of their sung time, most of them 15-40 ms
long and as loud as the note around them. Not gaps: the voice catching. (Measured over all their
sounding time, these men's own recordings are without a clear period 2-6% of the time, the
re-voiced soloists 12-14%.) Where they come from:

| | catches a second, straight from the model |
|---|---|
| ten, thirty or fifty refinement steps | 3.5-4.2 (no difference) |
| held to the voice loosely / as usual / hard | 3.3 / 3.8 / 4.8 |
| five men, each from his straight singing | 1.9, 1.9, 3.8, 3.9, 6.5 |
| one of them from his normal singing instead | 6.2 (from 3.9) |
| the chosen soloist, whole solo: straight / normal singing | 1.1 / 4.6 |

So the recording matters most: a man's normal singing, vibrato and all, gives a re-voiced line
several times the catches of his held-back "straight" singing - and the normal singing had just
been adopted for the sections, and used for all five auditions. On the choir's lines the same
holds more mildly (the three lower parts: 2.6 a second from straight singing, 3.4 from normal; the
two voices noted earlier as breathy are the worst at 3-6; the first tenors have almost none).

The rest was this program's doing. Putting the pitch back raised the chosen soloist's catches
from 1.1 to 1.8 a second (from 4.6 to 6.8 from his normal singing), and smoothing the correction
more did not help: what added them was the dropping or repeating of one period of the voice, most
of a second apart, to keep the corrected sound in time. That is now done only where the engine
itself has a rest or a consonant without voice, a few times a second anyway, and inside a note
only if 30 ms have built up. With that, and the correction smoothed over 17 ms instead of 7: 1.2
catches a second, as the model gave him, his pitch typically 5 cents from the engine's (14 as the
model gave him). As the piece renders him now: 1.2 a second, 1.3% of his sung time - against 6.6
and 12% in the audition the listener chose, and 7.4 and 12% for the soloist before him.

One guess that failed: that the model's coarse pitch steps flicker when a held pitch lies on the
edge of one (a held G with 4 cents of flutter crosses a step edge 110 times in 3 s). Holding the
step until the pitch has clearly left it changed nothing that could be measured, and is off.

The sections still sing from normal-voice recordings: the listener calls the chorus decent, and
changing its voices again is a decision for the listener's ears, not for this count.

**The roughness of a held note.** With the catches counted down from 7 a second to 1.2, the
listener's answer was "Still there". So the count had been measuring something else. Four clips
of the same opening settled where to look: the soloist as rendered, the model's sound with none
of this program's putting-back, the same from a legato engine, and the engine's own voice. "#2
sounds the best. I hear the artifacts in 1, 2, and 3. I dont hear it at all in #4" - and then:
"its most apparent when the voice model holds a note for an extended period." It is in the
model's own output, and the putting-back made a soloist slightly worse, not better.

*Counts that were wrong.* Everything counted with the pitch tracker had to go. On these voices a
strong first resonance sits on the second harmonic (the fundamental 15 dB under it on some
notes), the tracker reads an octave high, and "no clear period", "gross breaks" and "pitch jerks"
were mostly that. The spectra have no doubled or halved pitch anywhere.

*The measure that fits.* A voice clinic measures a rough voice cycle by cycle: jitter, how much
successive cycles differ in length, and shimmer, how much in strength. Found by matching each
cycle's waveform with the next, on held notes:

| | jitter | shimmer |
|---|---|---|
| the engine's soloist | 0.22% | 2.1% |
| six men's own recordings | 0.18-0.34% | 1.7-3.0% |
| the same solo from the model | 0.69% (its worst quarter of notes 1.2-1.35%) | 4.0% (5.5-6.1%) |

Ten, thirty or fifty refinement steps, the model held loosely or hard to the voice, five voices,
both kinds of recording, a pitch told between the model's steps or held to one step, an engine
source without any jitter of its own: the same every time. It is how this model makes a voice.

*Two corrections that did not work*, both measured and thrown away. Making the cycles' lengths
even (reading the sound a little faster or slower through each) raised the jitter from 0.65% to
0.95%: the cycles were not arriving unevenly, their shapes were changing, and moving them added
real unevenness to the apparent one. Blending each cycle with the two before and after left it
at 0.70%: the change from cycle to cycle is not random about a steady shape, it drifts.

*What worked: taking the sound apart.* The WORLD analysis (pyworld, installed with the listener's
leave) divides a voice into its colour every 5 ms, its breath, and its pitch, and builds it again
from the three. The model's pitch is thrown away and the engine's used. Each step below was sent
to the listener as the same 37 seconds:

| what was changed | measured on held notes | the listener |
|---|---|---|
| tone rebuilt at the engine's pitch; colour steadied over 20 ms | shimmer 4.1% -> 1.9% | "B is best, but theres still too much flutter in the held notes" |
| colour and loudness steadied over 120 ms inside held notes | loudness flutter 0.52 -> 0.30 dB (his own recording: 0.33) | "Flutter still there" |
| the engine's pitch read cycle by cycle, not by the tracker | pitch flutter 16.7 -> 6.8 cents (the engine: 7.5) | "Better, not gone" |
| the engine's loudness followed moment by moment | slow wander of loudness 0.8 -> 0.4 dB | "better but not gone and theres a new side effect I hear some weird fading"; and where: "just after the attack" |
| each held vowel steadied as a whole from 15 ms after it begins; the loudness-following taken out again | loudness movement in the quarter second after the attack 0.95 -> 0.42 dB (real singers 0.33-0.80) | "Good now" |

The third row was this program's own fault: the pitch given to the rebuild came from the tracker,
whose reading of a note the engine holds within 7 cents wobbles by 17, and the rebuilt voice sang
the wobble. The engine's pitch is now read from the lengths of its own cycles. The fourth row
was a correct measurement and the wrong cure: the loudness did wander, but tying it to the
engine's contour brought the engine's note shapes onto a voice with other syllable timing.

As the piece renders the soloist now: jitter 0.26% (worst quarter 0.73%), shimmer 1.5% (3.4%) -
a healthy voice by the clinic's measure, where he was rough. His words read 53 of 70 against 58
before the rebuild, and he sits 1.9 dB lower against the choir than the engine intends (6.6 dB
under the choir's verse, not 4.7); neither was changed after the listener said "Good now". Only
parts sung by one person are rebuilt: in a section the roughness of twelve voices averages out,
and the listener calls the chorus decent as it is.

Four times on the way the numbers said a real voice's steadiness had been reached while the
listener still heard the fault, and each time the listener's next words - held notes; flutter;
just after the attack; weird fading - named the measurement that was missing. The numbers decided
nothing here except which of two things the ear had asked for was actually different.

*And the chorus.* Offered the same rebuilding for the section singers, the listener heard the
choir's verse and the last chorus both ways and preferred them rebuilt; every singer's tone is
now built again, not only a soloist's. It has a price, and the listener was told it before
choosing: a section of twelve is understood less well - baritones 77% of their words before, 57%
after; first tenors 87% and 73% - while the singers agree in pitch as before (9 cents apart
against 8) and the choir sits 1 dB lower against the piano. Of the baritones' twenty points, ten
are the rebuilding itself and the rest the steadying of held vowels (rebuilt with no steadying:
67%; with any of it: 57-60%). Bringing the consonants back to the engine's strength, which the
old putting-back did as a side effect, gives the soloist six more words in seventy and the
sections nothing.

*The soloist's consonants.* So the listener heard it: the solo with its consonants raised to the
engine's strength by up to 5 dB and by up to 10 (56 and 59 of the 70 words to a recognizer,
against 53 with none), and chose 10 - "but the D", at the start of one phrase, "seems to be
dropped from all clips". It was, in every version since the voices arrived. Where the engine
closes a d for a moment 30-40 dB under the vowel and lets it go with a click 24 dB under, the
model sings through the closure (a murmur 14 dB under) and softens the click to 44 dB under; the
rebuilding, which takes a hummed closure for sung tone, smooths away what is left. No setting of
level brings back a click that is not there. So a rebuilt soloist's stops are put right against
the engine's own sound: where the engine is closed just before a rise, the voice is brought down
to it (never up), and where the engine's sound above 2 kHz leaps 15 dB in 15 ms and the voice's
does not, the engine's click is laid in. "D is there, good." He now reads 57 of 70 - the rebuild
had left him 53, and before it he had 58.

Neither change is made for section singers. With both, twelve baritones read 50% and the first
tenors 67%, against 57% and 73% without: a click from each of twelve men a few milliseconds apart
is a smear, not a consonant. And the chorus the listener chose was the one without them. The
piece as it now renders was laid against the two renders the listener approved: its solo verse is
the approved soloist's and its choir verse and last chorus the approved chorus's (correlation
1.0000 each; level within 0.1 dB).

**Why a render takes an hour.** Asked by the listener while nine pieces were rendering one after
another, each from its PDF alone. Measured on a four-minute piece: 48 singers, each converted
alone, are 167 minutes of singing, and the voice model took 77 of the render's 85 minutes; the
fitting afterwards took 6, and reading the PDF and singing the notes under one. Inside the model,
on 32 stretches timed stage by stage: the diffusion 55%, the vocoder 29%, the pitch tracker 14%.
The graphics chip was the limit, as measured before: four copies of the model side by side
converted the 32 stretches in the time one copy takes.

*What helped.* Half precision in the diffusion and the vocoder: 0.60 of the time. It is how the
model's own script runs by default; the driver written here had left it off. The sound is the
same by every measure on hand: over the 32 stretches the spectra lie 0.13 dB from full
precision's (0.23 in the worst stretch; 0.15 on two phrases of 47 seconds, which the driver
converts in overlapping pieces), the level 0.07 dB lower, and a recognizer hears 609 of the
piece's words where it heard 622 - the same count in 24 stretches, more in 3, fewer in 5. For
scale, a second draw of the same singer lies 1.8 dB away. A stretch that comes out as
not-a-number or silence is done again in full precision; none has been. The next whole piece
converted at 4.0 times real time against 2.3.

*What did not.* Four stretches in one batch: 0.90 of the time, and in half precision the batch
stalled the chip until it was stopped. Sixteen workers instead of eight for the fitting: the same
files to the byte, no sooner. Six refinement steps instead of ten: 0.68, but 1.7 dB from the
ten-step sound, which is as far as another draw - a different voice, not a rounding of the same
one. Ten stays until the listener has heard six.

*A caution about the recognizer.* The same piece rendered twice scored 59% and then 48% for
twelve baritones alone. Passage by passage the loss was two windows where the recognizer gave up
(one returned a note that the singing was in a foreign language) on sound whose level and
duration were unchanged; the whole choir's score rose from 47% to 55% between the same two
renders. A section's word score moves ten points on nothing. Single singers, or many windows,
are needed to see a real difference.

**"A random long slow stretch in the middle."** The listener's one complaint about the ninth
piece rendered from its PDF alone - "great" otherwise. The stretch is printed: six measures
marked slow and stately, 68 to the quarter, between music at 120. What was missing was the reason
for it. The tune there is the clarinet's, the choir is silent, and the reader left every
instrument's staff out, on the reasoning that an instrument is in the accompaniment track; from
a PDF alone there is no track. So the render held the keyboard's chords for eighteen seconds.

An instrument's staff now goes to the accompaniment (`IN:` lines; the piano plays them). In this
piece that is 237 notes in 53 measures, and the slow passage has 27 note onsets in the mix where
it had 11. Seven of the passage's nine clarinet measures read correctly at once. One was three
quarters in a two-beat measure: a triplet whose bracket the engine had not read. The other was
dropped for not fitting a measure the reader took to be three beats long - the keyboard's two
whole-bar rests, to which the recognition engine had given three beats, outvoting the clarinet's
four. A lone rest now says nothing about a measure's length. That measure had been a beat short
in every reading of the piece so far, unnoticed because it is silent but for the clarinet. Two
measures elsewhere are a tremolo, written as two whole notes beamed together, now played as the
two in turn. Drums are named and left out; so is a part in another key than the choir's. The
other eight pieces read exactly as before.

Not measured, because it cannot be here: how a clarinet's tune sits on a piano among chords that
lie around it. It is set forward by as much as the top note of a chord. And the fix cost a
conversion: moving the later music by one beat changed 255 of the piece's 463 stretches, which
had to be converted again, where a change to the accompaniment alone reuses them all.

**A render of nobody.** The sixth piece, last of the nine rendered from their PDFs alone, came
back in 84 seconds: four files of the right length and a log that said, in passing, that 0
singers had been re-voiced. One syllable did it. Under pencil marks the reader had taken a
syllable of the choir's text for "t-", which has no vowel; the engine looks for the vowel of
every syllable and, finding none, raised the error Python uses to say that a sequence has ended.
Raised inside a worker, that error does not arrive as an error: the list of singers simply ends
there, at its first member. So the render went on with no singers and wrote its files.

Three changes, the third the one that matters. A syllable with no vowel now keeps the vowel
before it, and the reader of the score says which syllable in which measure (fifteen notes in
this piece: one printed syllable, five parts, three times through). The engine does the same for
any such note that reaches it another way. And a singer that cannot be sung now stops the render
with its name, as does any count of singers short of the full choir: before this, the same error
in the plain render - without re-voicing - would have dropped every singer after the one that
failed and mixed the rest. None of the other eight pieces has such a syllable; their renders
stand.

**Words that were not words.** The sixth piece's real render (72 minutes for 52 singers; no
stretch needed doing again in full precision) was checked like the others and scored low: a
recognizer made out 31% of the words from the voices together and 24% from the baritones alone,
where the other Latin piece gives 48%. Passage by passage, it was writing down real words of
the prayer in places where the score said it should hear something else. The text of this piece
is fixed and old, so the reading can be checked with no answer key: count how many of the words
read from the page belong to the prayer at all. Three faults showed, none of them a misread
letter.

- *A footnote, sung.* At the foot of the first page of music, under the lowest staff, the
  publisher's note on how many singers may take the upper group and in what voicings the piece
  is sold. The reader took its lines for the words of the baritones and basses: nine words of
  English in the middle of the Latin, each of the three times through.
- *A staff's name, sung.* The name of the soloist's staff in the next system, with a rehearsal
  letter beside it, stands under the bass staff. Two of its words went to the basses, and from
  them, by borrowing, to the other three parts of the choir.
- *The trio's third voice sang a patchwork.* It has no words under its own staff. A voice
  without words sang what "the others" sing at the same moment, and the others were looked
  through in a fixed order that begins with the choir's first tenors. So the trio's baritone
  took the choir's syllable wherever the choir began one and the trio's otherwise: 12 of its 89
  words were words of the prayer, against 49 of 95 and 52 of 91 for the two voices it sings
  with.

*Telling print from lyrics.* Language would have caught the footnote here and nowhere else. What
holds in any language is how the line is set. In a sentence the words stand a space apart and
every gap is alike; words to sing are spread under their notes. Measured on the 387 lines of
print under the staves of the five scanned pieces, with the gap between neighbouring words
counted in letter-widths: in every line of running text the widest gap is under half a letter
and at most 1.4 times the middle one; in a line of lyrics the widest gap is 2.7 letters or more,
usually 5 to 15. One line of lyrics comes near - five words of quick text in piece 1, widest gap
0.79 - and its gaps are anything but alike (six times the middle one). The rule: three or more
words, widest gap under 0.6 of a letter and no more than twice the middle gap. It finds the
footnote. It also finds, in piece 1, a direction about a slide that the baritones in one place
and the second tenors in another had been singing as three words since that piece was first
read; in piece 5 two lines of smudged small print, without which the second tenors have their
own words in three places where they had fragments or none; and five lines in pieces 7 and 9 (a
misread "poco a poco", notes for the drummer) that other rules were already keeping out.

The first version of the rule was wrong twice, and both were caught only by reading all nine
pieces again and comparing every line with the reading before. It held that whatever is printed
beneath a line of running text is more of it: true of a footnote, but a direction stands
*between* the staff and its words, and the line of real words beneath it went too. Now only a
line set as tight is taken with it. And with a line removed, two later looks at the same strip
of the page - each line read again close up, and a second search for a note left without a
word - took their height from the lines that remained, grew into the place of the one removed,
and brought pieces of it back as syllables. They now stop at every line of print, sung or not.

*A staff's name* is a line made of nothing but part names, numerals and single letters. Besides
the one in the sixth piece, three stray names in piece 1 went the same way, and with them out
of the way the tenors got back a pickup word they had been missing.

*Borrowing.* A voice without words now takes them from its own ensemble first - a trio's voice
from the trio, a choir part from the choir. If none of them begins a syllable at that moment but
one is in the middle of one, it holds its vowel (or takes the syllable up, if it is only now
entering); another ensemble's words are borrowed only while its own is silent. Compared note by
note on every score in the project, 12,709 notes: the trio's third voice changes on 85 notes and
is now as right as its neighbours (52 of 91 words), and 21 notes change elsewhere. Seventeen are
of one kind: a voice moving under a vowel its own ensemble is holding had sung another
ensemble's word of that moment, which spoiled the word after it as well. Six of those are in the
tenth piece, in the render the listener approved: in two measures three parts on "oo" each sang
a word of the solo. The other four, in piece 7, are voices entering on a syllable the rest are
holding, who now sing that syllable instead of nothing. No other note in any score sings
differently.

*After.* Five of the nine sing differently for these changes and were rendered again. What a
recognizer makes out of each, from the voices together and from the baritones alone:

| Piece | Before | After |
|---|---|---|
| 6 | 31% and 24% | 43% and 48% |
| 1 | 54% and 66% | 67% and 66% |
| 5 | 48% and 28% | 47% and 37% |
| 7 | 28% and 19% | 28% and 23% |
| 10 | 63% and 53% | 71% and 49% |

Only the sixth piece's change is beyond doubt; counted by letters instead of whole words it
went from 58% and 57% to 69% and 73%. The first piece's thirteen points for the voices together
are at the edge of what two renders of the same thing differ by, and the rest are inside it: in
those pieces a handful of notes changed, and the counts say only that nothing was broken. In
none of the five is there a half-second where someone should be singing and the mix is silent,
and no stretch had to be converted again in full precision.

**Nine pieces from the page alone.** The test the work above was heading for. The listener gave
nine PDFs - the first, second and fourth to tenth pieces of this record - and asked for each to
be rendered "based only on the music". So: no practice tracks to take the timing, the room or
the shape of the notes from, no recorded accompaniment, and none of the transcriptions made or
corrected by hand earlier. Each piece was one command, `python -m choral PIECE.pdf --part
baritone --voice .svc/voices`: twelve singers to a part with the men's voices, over the built-in
piano.

| Piece | How it was read | Lasts | Singers | Singing converted | First render | Words a recognizer gets, all voices | baritones alone |
|---|---|---|---|---|---|---|---|
| 1 | recognized (a phone scan) | 3:24 | 48 | 135 min | 43 min | 67% | 66% |
| 2 | exactly | 2:44 | 48 | 113 min | 65 min | 53% | 47% |
| 4 | recognized | 2:40 | 48 | 110 min | 33 min | 48% | 48% (the basses: it is in three parts) |
| 5 | recognized | 6:04 | 49 | 174 min | 61 min | 47% | 37% |
| 6 | recognized | 5:35 | 52 | 245 min | 72 min | 43% | 48% |
| 7 | recognized | 3:09 | 48 | 123 min | 39 min | 28% | 23% |
| 8 | exactly | 4:09 | 48 | 167 min | 85 min | 62% | 58% |
| 9 | recognized (its fonts are stored under private numbers) | 2:54 | 48 | 86 min | 54 min | 55% | 48% |
| 10 | exactly | 2:47 | 49 | 88 min | 4 min (converted the day before) | 71% | 49% |

The second, eighth and ninth were converted before half precision, at about twice real time;
the others at three to four times. The word counts are of the renders as they now stand, after
the corrections described here.

*Reading.* Eight of the nine read at the first attempt as they had read before. Three are
notation-software exports, read exactly from their own symbols: 1,054 of their 1,066
staff-measures add up. The sixth - unaccompanied, in Latin, a trio over the choir, lines of chant
between the refrains - asked for most of what the reader could not yet do, and each of these is
now a rule in it:

- the language is told from the words on the page;
- a treble and a bass staff in a brace, with a line of words between them, are the choir and not
  a keyboard;
- staves are one system only if the line joining them stands where they begin (a clef's tail, a
  measure number and the next clef's top in one column look much like a line);
- a staff with no barlines, for which the recognition engine returns nothing, is shown to it
  again with a barline drawn at its end;
- numbered endings: the bracket is found by its shape and the passes it is for are read under
  its corner;
- under a lowest staff with no keyboard beneath it, the words are looked for further down;
- a "p" between two hairpins is not a metronome mark;
- with no tempo printed, the guess is said in capitals (120 for a notation-software export, 100
  for a printed page).

Against the transcriptions checked by hand earlier - not used for these renders - the notes read
from the first piece are 99-100% in the same place at the same pitch, part by part; the
second's 97-100%; the fourth's 96-99%.

*What the renders showed.* Four faults, each with its entry above: an interlude without its tune
(the ninth: an instrument's staff had been left out), a render with nobody in it (the sixth: a
syllable with no vowel), words that were not words (the sixth, first and fifth: a footnote, a
direction, staves' names), and the hour a render took. The listener's ear found the first; they
have reported on one piece so far, the ninth, "great" but for that stretch. The second was found
in a log, the third by a word count that was too low, the fourth by a question.

*Reading the word counts.* The two right-hand columns say less than they seem to. A section of
twelve moves ten points between two renders of the same thing. The seventh piece is in two
languages, and a recognizer listening for English writes nothing for the other, whatever is
sung. The Latin pieces score what the recognizer knows of Latin. What the counts were good for
is what they did here: one piece far below its like - 31% where the other Latin piece gave 48% -
turned out to be three faults of reading.

*What a correction costs.* Each singer draws his small differences - when he comes in, how he
tunes, how he shapes a note - from one run of random numbers that lasts the whole piece. Change
one word near the beginning and every phrase after it comes out as another take by the same
man: the same notes, different to the byte. The store of converted singing knows a stretch by
its bytes. So the corrected reading of the sixth piece, 18 changed lines of score, sent 1,385 of
its 1,465 stretches to be converted again (70 minutes), and the first piece's, six changed
lines, all 940 (44 minutes); six notes in the tenth cost 360 of 485, four in the seventh 553 of
767; before that, one beat's difference in the ninth had cost 255 of 463. The five renders made
again for the word faults took three hours and twenty-four minutes between them. Giving each
phrase its own run of numbers would hold a correction to the phrase it is in.
It would also make every piece a new take, once - the tenth, which the listener approved by
ear, among them - so it waits for their word.

*Known to be wrong still.*

- The second piece prints no tempo. It is sung at 120; its practice track runs near 130.
- The sixth: the first note of the chant is read as a rest, the chant's speed is a guess, and
  some of the choir's syllables are misread under pencil marks.
- The seventh: the words that are not English are sung by English spelling rules.
- The piano plays every instrument's line, and how far forward a clarinet's tune should stand
  among its chords has not been measured or heard.

**A corrected word no longer costs the piece.** The entry above leaves a choice with the
listener: make a correction cheap to render again, at the price of every piece becoming a new
take once. Asked, they said "make it".

*A measure first.* A copy of the program was run up to the point where the singers go to the
voice model, and what would be handed over was written down instead: every stretch, with a
digest of the same bytes the store of converted singing is keyed on. Run with the engine as it
was, on the five pieces as they stood before and after the word fixes, it gave the counts in
the night's logs to the stretch - 1,385 of 1,465, 940 of 940, 695 of 987, 360 of 485 and 553 of
767 to convert again. So what it says of a changed engine can be believed, in half a minute a
piece, without an hour of conversion per trial.

*What was changed.*

- Each breath of each singer has its own run of random numbers, named by the singer and the
  beat the phrase starts on, where there was one run for the whole piece. The singers
  themselves - their voices, their skill, where they stand - are drawn as before.
- That alone left the low parts of the sixth piece almost wholly to convert again, and one tenor
  of its twenty-four. The cause was in the cutting, not the singing. Where a part is cut into
  stretches was measured against the loudest moment anywhere in the part: 48 dB under it counts
  as silence, 35 dB under it as quiet enough to cut in. A new take of the loudest phrase moved
  that level a little, and with it every edge and every cut in the part by a few milliseconds -
  the same singing, handed over as other bytes. The loudest moment is now taken to the nearest
  6 dB. On the same singing the cuts come out as before in kind: the same number of stretches to
  within two in a thousand, and as many cuts in a held note (533 for 532 in the sixth piece, 48
  for 48 in the tenth).
- Conversions go into the store as they finish, ten at a time, where they used to go in when
  the whole piece was done; and a render that is stopped stops the model.

*What a correction costs now.* The night's five corrections again, and one more: a single word
changed in one staff in the middle of the first piece.

| Piece | What changed | To convert again, before | Now |
|---|---|---|---|
| 6 | the words of 27 notes in each low part, 83 in one trio voice, 3 in each of three other parts | 1,385 of 1,465 stretches (232 min of singing) | 808 of 1,464 (137 min) |
| 1 | six lines of score | 940 of 940 (135 min) | 97 of 938 (18 min) |
| 5 | six lines, and six notes | 695 of 987 (122 min) | 210 of 992 (37 min) |
| 10 | six notes | 360 of 485 (66 min) | 60 of 485 (13 min) |
| 7 | four notes | 553 of 767 (88 min) | 84 of 769 (16 min) |
| 1 | one word | 412 of 940 (54 min) | 48 of 938 (8 min) |

The same score read twice hands over the same bytes: no stretch of 938, none of 1,464.

*What is left.* The unit is the phrase, from one rest to the next, because the engine sings a
phrase as one thing: a changed consonant shifts every draw after it, and the voice runs through
without a break. The sixth piece is the hard case. Its choir sings eighteen seconds at a time
without a rest, and once forty-nine; its correction touched most of those phrases in the low
parts; so more than half of it would still be converted again. Three of its twenty-four low
singers go again entirely: their loudest moment lay in a corrected phrase and its new take
crossed from one 6 dB step into the next. A change that moves the music in time converts
everything after it, as before. And the fitting that follows the model, a few minutes a piece,
is still done in full each time.

*The same in kind.* The first piece sung by the engine as it was and as it is, without the
voice model: a recognizer gets 75% of the words from all the voices and 78% from the baritones
alone before, 77% and 77% after. The level differs by 0.02 dB, and the spectrum, by third
octaves, by a quarter of a decibel on average and 1.3 dB at the most - what one take differs
from another by.

*With the real voices.* The public demo score written out four times over - twenty measures,
sixteen singers, 128 stretches. The first time all 128 were converted, in six minutes. Rendered
again unchanged: none, in 42 seconds. With one word corrected in the third verse: 38, in two
minutes twenty. Then another word was corrected and the render stopped from outside when ten of
its 32 stretches were done. The model stopped with it, nothing was left in the temporary
folder, and the next run found 106 of the 128 converted and did the other 22. A run now says at
its start how many minutes of singing are left to convert.

*The price, as agreed.* Every piece is a new take the next time it is rendered: the same
singers on the same notes, with other small differences. The nine renders in hand are the old
takes, and stay so until rendered again; the 11 GB of conversions in the store belong to them
and will not be found again.

*Heard.* The tenth piece was rendered again as a new take - all 485 stretches, 27 minutes - and
given to the listener beside the take they had approved. By measurement the two agree: the
level within 0.1 dB, the spectrum by third octaves a quarter of a decibel apart on average and
1.2 dB at the most, the bands that carry the soloist within 1.5 dB through the solo verse, and
a recognizer gets 70% and 48% of the words where the night's render gave 71% and 49%. The
listener's answer to whether it sounds as good: "As good".

**For anyone.** Asked what it would take to run all this without an assistant at the keyboard,
and then by other people on their own machines, the listener said: "I want to make it easy for
anyone to run this." Two questions were theirs to answer. Who is it for - people who type
commands, or singers who never open a terminal? Singers. And how do other people get the driver
that runs the voice model, which follows GPL code and so could not sit in an MIT repository? Make
the whole project GPL. So the licence is now the GPL, version 3, and the driver is in the
repository (`choral/seedvc_driver.py`).

*What "easy" came to.*

- *One line, once.* A Mac will not open an unsigned app that a browser downloaded; it will run a
  line pasted into Terminal, and it will open with a double-click whatever that line builds on
  the spot. So the install is one pasted line, and after it an app in the Applications folder. A
  signed app that needs no line takes a paid Apple developer account, which is the listener's
  to decide on.
- *Nothing assumed.* The installer brings its own Python (through uv) and installs every package
  at the version this was tested with. One package, the one that steadies held notes, has no
  ready-built form for a Mac and must be compiled, and the text reader for scans is compiled
  too; so Apple's developer tools are asked for where they are missing.
- *A page instead of commands* (`choral/app.py`). Drop a PDF on it; it is read; choose a part,
  the voices, the size of the choir; the tracks appear with players. It says in plain words what
  the reader was unsure of, and where no tempo was printed it says what it guessed and takes a
  better one. One piece at a time. Stopping keeps what was finished. The Mac is kept awake while
  it works. Tracks are compressed, and those made with real voices get a file with the credit.
- *Real voices behind a button* (`choral/setup_voices.py`): the model's packages, the model, the
  ten voices, and a three-second trial, with a progress bar.

*From nothing.* The installer was run in an empty home folder, with a search path holding only
the system's own programs, from a copy of the source. The program, its Python (3.12, where the
work so far was done on 3.15) and the scan reader with its models came to 1.1 GB, 0.7 GB once the
copies of what had been downloaded were cleared away, and it sang the demo. The pasted line
itself, fetching from GitHub, took 35 seconds on this connection. Then the page of that copy:

- A scanned piece (the fifth) and a notation-software export (the tenth) were read by it into
  scores identical, line for line, to the ones rendered the night before.
- Real voices were added by the button: 166 seconds on this connection, 4.7 GB in all, and the
  ten voices fetched are byte for byte the ten used here.
- The demo, made there with real voices and four to a part, against the same made in the working
  copy: correlation 0.9996 to 0.9999, level within 0.01 dB.
- Opened the way a double-click opens it. The first launcher stayed running as the app, and a
  Mac does not start a running app again: a second double-click, after the page had been closed,
  did nothing. The launcher now leaves the program running behind the page and ends at once.

*What it left behind, and what it reported.* Every file the test left outside the app's own
three folders was listed. There were a receipt from uv, pip's copies of the packages, the caches
of two of the voice model's libraries - and, under a folder named for Microsoft, a device
identifier and a small database. The library the scan reader computes with (onnxruntime 1.31)
reports its use to its maker unless a variable tells it not to. The same folder is on the
listener's own Mac, dated from the day the scan reader was first installed there. Every program
started from here is now told not to report (the model downloader likewise), the caches go
inside the app's own folder, and the list is empty. The switch was checked both ways: one scan
image read with it set leaves nothing in an empty home folder, and without it leaves the
identifier and the database.

*Not tested.* A Mac that lacks Apple's developer tools - this one has them, so the step where
they are asked for has never run. Any Mac but this one: an older chip will be slower, by how much
is unknown. Intel Macs, Windows and Linux, which get instructions and no installer. And nobody
who is not a programmer has tried it yet.
