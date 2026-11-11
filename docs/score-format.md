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
| `RH:` `LH:` | piano right and left hand; `RH2:` `LH2:` for a second voice on the same staff |

Every line must add up to the length of the measure — the reader refuses the file otherwise,
which catches most misread rhythms. A line that is absent is a bar of rest.

## Notes

`pitch/duration`, with optional marks and a syllable: `c4/e=God`

- **Pitch**: letter and octave as printed (`c4` is middle C). Write accidentals only where the
  page prints them: `f#4`, `bb3`, `an4` (natural). Chords join with `+`: `c4+eb4+g4`. Rest: `r`.
- **Duration**: `w h q e s t` (whole … thirty-second), dots as dots (`q.`), `e3` for a triplet eighth.
- **Marks** after the duration: `~` tie, `>` accent, `'` staccato, `%gl` slide into the next note
  over the last beat.
- **Syllable** after `=`: as printed, hyphen included (`mer-`, `ry`). `=_` continues the previous
  syllable on a new pitch (a slur). A voice with no syllables sings what the other voices sing at
  the same moment.
- **Dynamics** go between notes: `!pp !p !mp !mf !f !ff`, `!cresc`, `!dim`.

## Words

Syllables are joined into words and looked up in the CMU pronouncing dictionary. For words it
does not know, or pronounces differently from how the piece sets them, add a line near the top:

```
say: heav'nly = HH EH1 V . N L IY0      // CMU phonemes, a dot between sung syllables
```

`//` starts a comment.
