# Score format

A score is a plain-text file that mirrors the printed page. It is written by reading the sheet
music one system at a time; the renderer then applies the same rules a musician would (key
signature, accidentals lasting to the end of the bar, ties, tenor clef sounding an octave down).

```
title: Shenandoah (traditional) - format demo
tempo: 66            // quarter notes per minute; may be repeated between measures
time: 4/4
key: -1              // flats negative, sharps positive; may be repeated between measures
transpose: TEN -12   // tenor staves are printed an octave above where they sound

== 2                                            // measure number as printed
TEN: f4/e=Shen- f4/e=an- f4/q.=doah g4/e=I a4/e=long b4/e=to
LOW: f3+a3/e f3+a3/e f3+a3/q. e3+b3/e f3+c4/e g3+d4/e
RH: !p f4+a4+c5/h. e4+g4+b4/q
LH: f2+f3/w
```

## Lines

| Line | Meaning |
|---|---|
| `TEN:` | the shared tenor staff. One note = both tenor parts; two notes = first tenor on top; three = first tenors split the top two |
| `LOW:` | the shared baritone/bass staff, same rule |
| `T1:` `T2:` `BR:` `BS:` | one part on its own staff, or one voice of a shared staff when the rhythms differ |
| `SOLO:` | a soloist: one singer on a close microphone, as loud as a section |
| `TRIO:` `TR1:` `TR2:` `TR3:` | a trio of soloists: `TRIO:` is the staff its two tenors share (`transpose: TRIO -12` when printed an octave up), `TR3:` its baritone |
| `RH:` `LH:` | piano right and left hand; `RH2:` `LH2:` for a second voice on the same staff |
| `IN:` | an instrument's line printed in the score (a clarinet over the choir), at the pitch it sounds: the piano plays it, a little forward of the chords. `IN2:` to `IN4:` for more. Delete the lines to leave the instrument out |

Every line must add up to the length of the measure — the reader refuses the file otherwise,
which catches most misread rhythms. A line that is absent is a bar of rest.

## Notes

`pitch/duration`, with optional marks and a syllable: `c4/e=God`

- **Pitch**: letter and octave as printed (`c4` is middle C). Write accidentals only where the
  page prints them: `f#4`, `bb3`, `an4` (natural), `f##4`, `bbb3` (double sharp, double flat). Chords join with `+`: `c4+eb4+g4`. Rest: `r`.
- **Duration**: `w h q e s t` (whole … thirty-second), dots as dots (`q.`), `e3` for a triplet eighth.
- **Marks** after the duration: `~` tie (or after one pitch of a chord, `c4~+e4/q`, to tie only that note), `>` accent, `'` staccato, `%gl` slide into the next note
  over the last beat, `x` spoken instead of sung (`eb4/ex=Hey`: the x-shaped notehead of printed
  music). A spoken note is said in rhythm at each singer's own speaking pitch; where it is written
  on the staff only nudges it a little higher or lower.
- **Syllable** after `=`: as printed, hyphen included (`mer-`, `ry`). `=_` continues the previous
  syllable on a new pitch (a slur). A voice with no syllables sings what the other voices sing at
  the same moment - those of its own ensemble first: a trio's voice takes the trio's words, a
  choir part the choir's. If none of them begins a syllable just then but one is in the middle
  of one, the voice holds its vowel, or takes that syllable up if it is only now coming in. The
  words of another ensemble (a soloist's, for the choir) are borrowed only while its own is
  silent.
- **Dynamics** go between notes: `!pp !p !mp !mf !f !ff`, `!cresc`, `!dim`.

`tempo:` and `time:` may change between measures; `10/8` and `6/8` are counted in eighths, with the
tempo still given in quarter notes per minute.

## Repeats, D.S. and codas

Write every measure once, numbered as printed, and say near the top in what order they are
performed:

```
play: 1-15 14-15 16-62 24-33 63-75     // repeat 14-15; D.S. back to 24; to the coda after 33
```

The reader unrolls it: the measures are renumbered 1, 2, 3 ... as performed, and the time
signature, key, tempo and dynamic level are put right wherever the music jumps. A tie cannot reach
across a jump. (Different words on the repeat are not supported yet: the second time through
sings the same words.)

## Words

Syllables are joined into words and looked up in the CMU pronouncing dictionary. A word it does
not have is looked for under a fuller spelling ("ev'ry", "o'er", "singin'") and otherwise sung as
it is spelled, by rough English rules - the run prints what it chose. For words it gets wrong, or
pronounces differently from how the piece sets them, add a line near the top:

```
say: heav'nly = HH EH1 V . N L IY0      // CMU phonemes, a dot between sung syllables
```

### Latin

```
language: latin
```

near the top of the file switches from the English dictionary to church-Latin rules, applied to
each printed syllable (`Sanc-` `tus`, `ex-` `cel-` `sis`): c and g soften before e and i, `ti`
before a vowel is "tsee", `gn` is "ny", `ae` and `oe` are "eh", h is silent, and the five vowels
are the engine's own Latin vowels, fitted to real singers. `say:` lines still override single
words.

### Drum and bell syllables

Drum and bell syllables - *pum, rum, tum, bum, dum, pom, bom, dom, bim, bam, ding, dong, bong* -
are sung the way choirs sing them: a short vowel, then the rest of the note hummed on the *m* or
*ng*. Any syllable can be given that treatment with a `+` before the consonant to hold:

```
say: zum = Z AH1 + M                   // "zummm"
```

## Lyrics read from the page by text recognition

For a scan, the words can come from text recognition instead of being typed. Put them in a JSON
file - `{"p03_s1": {"TEN": ["Shen-", "an-", "doah"], "LOW": [...]}, ...}`, one list of
syllables per staff per system - and let each note take the next one with `=*`:

```
lyricsfile: piece.lyrics.json
system: p03_s1                         // the measures that follow are on this system
== 9
TEN: f4/e=* f4/e=* f4/q.=* g4/e a4/e b4/e
```

`T1:`/`T2:` lines draw from the `TEN` list and `BR:`/`BS:` from `LOW` unless the file has a list
under their own name. The reader reports any syllables left over at the end of a system, which is
how a miscounted melisma shows up.

## Holding and slowing

```
stretch: 3 2 1.8          // from beat 3 of the next measure, two beats take 1.8 times as long
```

A fermata is one such line; a rallentando is a row of them, each a little slower than the last.
The reader writes them from the fermatas and the "rall." ... "a tempo" it finds in a PDF. They
are ignored when the timing comes from a recording.

## Swing

```
swing: on                 // from the next measure, the two eighth notes of a beat are long and short (2 to 1)
swing: 60                 // the same, lighter: the first eighth takes 60 hundredths of the beat
swing: off                // even eighths again
straight: 3 2             // from beat 3 of the next measure, two beats are even in the middle of the swing
```

Voices and accompaniment swing together. Triplets stay even. The reader writes `swing: on` where a
heading says so ("Swing", "Uptempo swing", "Shuffle"), `swing: off` at "Straight 8ths" or "Even
eighths", and a `straight:` line for the notes under a bracket marked "straight" (from a PDF
exported by notation software; on a scan the bracket is not looked for).

## Timing measured from a recording

`tempo:` gives one tempo. A piece that slows down, pauses or holds its last chord can instead
point at a beat-by-beat map made by `python -m choral.timing` from a recording of one part:

```
timing: piece.timing.json              // {"offset": 1.045, "bpm": 144.0, "beats": [...], "secs": [...]}
```

`python -m choral` measures this by itself when it is given practice tracks, and keeps it in the
piece's preset file.

`//` starts a comment.
