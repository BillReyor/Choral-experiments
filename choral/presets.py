"""The settings that differ from piece to piece, estimated instead of set by hand.

Three sources, best first:
  * recordings of the piece (practice tracks): tempo and every bend in it, how much hall is on the
    voices, how loud the accompaniment sits under them, whether notes are sustained or fade like bells;
  * a speech recognizer listening to the render: how close the microphones must be for the words
    to survive this piece's tempo and text;
  * the score alone: a rule from how fast the text goes by.
A preset is a small JSON file kept beside the score, so a piece is estimated once.
"""
import numpy as np
from scipy.signal import resample_poly
from . import render as R, hear, timing as timingmod, reference

# From dry-and-close to wet-and-blended.  Fast text needs the first; slow music can afford the last.
LADDER = [dict(hall=.05, spot=2.6), dict(hall=.09, spot=2.1), dict(hall=.14, spot=1.8),
          dict(hall=.20, spot=1.4), dict(hall=.28, spot=1.0), dict(hall=.40, spot=.7)]


def quick_syllable(sc):
    """How short the quick syllables are, in seconds (the 15th percentile of all sung syllables).
    The average says little - long notes swamp it; it is the quick ones that a hall smears."""
    beats, secs = R.clock_for(sc)
    d = [float(np.interp(n['beat'] + n['dur'], beats, secs) - np.interp(n['beat'], beats, secs))
         for notes in sc.parts.values() for n in notes if n['phon'] != '-']
    return float(np.percentile(d, 15)) if d else 1.


# quick-syllable length (s) -> rung.  A rule of thumb resting on two pieces checked with the recognizer:
# eighth notes at 130 a minute (0.23 s) needed the dry end; at 100 a minute (0.30 s) a wetter mix cost nothing.
QUICK_TO_RUNG = ([.24, .30, .45], [2, 3, 4])


def from_score(sc):
    """With nothing to listen to: choose the rung of the ladder from the speed of the text."""
    q = quick_syllable(sc)
    rung = int(round(float(np.interp(q, *QUICK_TO_RUNG))))
    return dict(LADDER[rung], quick_syllable=round(q, 3))


# ---------------------------------------------------------------- hall, from a recording ----
def release_curve(x, sr=R.SR):
    """How the sound dies away after the choir stops: the median level (dB, relative to just before
    the release) over the following 1.2 s, across every clean release in the recording."""
    hop = int(.01 * sr)
    m = x.mean(1) if x.ndim == 2 else x
    p = (m[:len(m) // hop * hop] ** 2).reshape(-1, hop).mean(1)
    e = 10 * np.log10(np.convolve(p, np.ones(2) / 2, 'same') + 1e-12)
    top = np.percentile(e, 90)
    curves = []
    i = 40
    while i < len(e) - 130:
        if e[i - 30:i].min() > top - 14 and e[i + 1:i + 130].max() < e[i] and e[i + 100:i + 130].max() < e[i - 10:i].mean() - 22:
            if e[i] - e[i + 6] > 3:                          # it really is falling from here
                curves.append(np.maximum(e[i:i + 120] - e[i - 10:i].mean(), -32))
                i += 130; continue
        i += 1
    return (np.median(curves, axis=0), len(curves)) if len(curves) >= 3 else (None, len(curves))


def match_hall(stems, P, ref_voices, log=print):
    """Choose hall amount and length so the choir dies away the way the recorded voices do."""
    target, n = release_curve(ref_voices)
    if target is None:
        log(f'only {n} clean releases in the recording - keeping the hall as it is')
        return {}
    tot = sum(stems.values()); N = tot.shape[1]
    Ld, Ls, Lsp = R.loud(tot[0]), R.loud(tot[1]), R.loud(tot[2])
    sp = P['spot'] * tot[2] / Lsp
    base = .7 * tot[0] / Ld + sp
    best = None
    for rt in (.9, 1.3, 1.8, 2.4):
        h = R.hall_of(dict(P, hall_rt=rt), N)
        wet_send, wet_spot = h(tot[1] / Ls), h(.2 * sp)
        for hall in (.03, .06, .1, .14, .2, .28, .4, .55):
            c, k = release_curve(base + hall * wet_send + wet_spot)
            if c is None:
                continue
            err = float(np.abs(c - target).mean())
            if best is None or err < best[0]:
                best = (err, hall, rt)
    if best is None:
        return {}
    log(f'hall matched to the recording over {n} releases: amount {best[1]}, length {best[2]}s (curve differs by {best[0]:.1f} dB)')
    return dict(hall=best[1], hall_rt=best[2])


# -------------------------------------------------------- microphones, from the recognizer ----
def tune_for_words(stems, sc, clock, P, keep_hall=False, log=print):
    """Walk the ladder and keep the most blended setting whose words still come through
    (within 3 points of the clearest).  keep_hall: the hall is already known; only move the mics."""
    if not hear.model_path(getattr(sc, 'language', 'english')):
        log('no speech recognizer here (whisper-cli + WHISPER_MODEL) - keeping the rule-of-thumb setting')
        return {}
    T = lambda b: float(np.interp(b, clock[0], clock[1]))
    tot = {'all': sum(stems.values())}
    res = []
    for rung in LADDER:
        Q = dict(P, spot=rung['spot']) if keep_hall else dict(P, **rung)
        v = R.mix_voices(tot, Q)['all'].mean(1)
        u = hear.understood(sc, resample_poly(v, 1, 2), R.SR // 2, T)
        res.append((u, rung))
        log(f"  leaders' mics {Q['spot']:.1f}, hall {Q['hall']:.2f}: {100 * u:.0f}% of the words recognized")
    top = max(u for u, _ in res)
    if top - min(u for u, _ in res) < .06:                   # the recognizer's own noise is about this large
        log('  the recognizer hears no real difference between them - keeping the rule-of-thumb setting')
        return {'words': round(float(np.mean([u for u, _ in res])), 3)}
    u, rung = [r for r in res if r[0] >= top - .03][-1]
    out = {'spot': rung['spot']} if keep_hall else dict(rung)
    return dict(out, words=round(u, 3))


# ------------------------------------------------------------ note shape, from a recording ----
def note_decay(sc, part, x, sr, T):
    """How fast one real singer's held notes fade, in dB per second (median over notes of 0.6 s and more,
    measured from 0.2 s after the start to 0.1 s before the end).  T maps beats to seconds in x."""
    hop, n = 64, 256
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop]
    et = (np.arange(len(fr)) * hop + n / 2) / sr
    edb = 10 * np.log10((fr ** 2).mean(1) + 1e-10)
    slopes = []
    for nt in sc.parts[part]:
        a, z = T(nt['beat']), T(nt['beat'] + nt['dur'])
        e = edb[(et >= a + .2) & (et <= z - .1)]
        if z - a >= .6 and len(e) > 20 and e.mean() > edb.max() - 35:
            slopes.append(np.polyfit(np.arange(len(e)) * hop / sr, e, 1)[0])
    return float(np.median(slopes)) if len(slopes) >= 8 else 0.


# ----------------------------------------------------------------------- from recordings ----
def from_recordings(sc, part, balanced, accompaniment, predominant=None, muted=None, log=print):
    """Timing, accompaniment level and the isolated tracks, from a set of practice tracks.
    Returns (preset entries, isolated tracks)."""
    rough = reference.isolate(sc, None, part, balanced, accompaniment, predominant, muted, log=lambda *a: None)
    out = {}
    if rough['clean'] < 15:
        log(f"the practice tracks are not one recording at different levels (subtracting the accompaniment only removes "
            f"{rough['clean']:.0f} dB), so the voices cannot be separated; using the accompaniment for timing only")
        if sc.piano:
            out['timing'] = timingmod.from_accompaniment(sc, accompaniment.mean(1), R.SR, log)
        return out, rough
    acc = (accompaniment.mean(1), R.SR)
    if 'part' in rough:
        tm = timingmod.measure(sc, part, resample_poly(rough['part'].mean(1), 1, 2), R.SR // 2, acc, log)
    else:
        tm = timingmod.from_accompaniment(sc, acc[0], R.SR, log)
    out['timing'] = tm
    clock = R.clock_for(sc, tm, absolute=True)
    iso = reference.isolate(sc, clock, part, balanced, accompaniment, predominant, muted, log)
    if iso['clean'] < 15:
        log('  ! not clean enough to trust the separated voices: keeping only the timing')
        return out, iso
    out['backing'] = round(R.loud(iso['accompaniment']) / R.loud(iso['voices']), 3)
    if 'part' in iso:      # the engine's own notes fade about 2 dB a second; make up the difference
        d = note_decay(sc, part, resample_poly(iso['part'].mean(1), 1, 2), R.SR // 2, lambda b: float(np.interp(b, clock[0], clock[1])))
        out['note_decay'] = round(float(np.clip(d + 2, -14, 0)), 1)
        log(f"held notes fade at {d:.1f} dB a second in the recording -> note decay {out['note_decay']}")
    log(f"accompaniment sits at {out['backing']:.2f} of the voices' level in the balanced mix")
    return out, iso
