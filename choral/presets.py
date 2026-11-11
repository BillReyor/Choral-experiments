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
def note_shape(sc, part, x, sr, T):
    """How one real singer shapes notes -> (fade, attack, scoop):
    fade: dB per second a held note falls (negative) or swells (positive), median over notes of 0.6 s and more;
    attack: seconds for an entry after silence to rise from 20 dB below its level to 3 dB below;
    scoop: cents below the note at which an entry after silence begins.
    T maps beats to seconds in x.  None where there is too little to measure."""
    from .pitch import yin
    hop, n = 64, 256
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop]
    et = (np.arange(len(fr)) * hop + n / 2) / sr
    edb = 10 * np.log10((fr ** 2).mean(1) + 1e-10)
    pt, pm = yin(x, sr)
    slopes, rises, scoops = [], [], []
    notes = sc.parts[part]
    for i, nt in enumerate(notes):
        a, z = T(nt['beat']), T(nt['beat'] + nt['dur'])
        e = edb[(et >= a + .2) & (et <= z - .1)]
        if z - a >= .6 and len(e) > 20 and e.mean() > edb.max() - 35:
            slopes.append(np.polyfit(np.arange(len(e)) * hop / sr, e, 1)[0])
        after_rest = i == 0 or T(notes[i - 1]['beat'] + notes[i - 1]['dur']) < a - .35
        onset = []
        for tk in (nt.get('phon') or 'A').split():
            if tk[:1].isupper():
                break
            onset.append(tk)
        hummed = any(tk not in ('p', 't', 'k', 'b', 'd', 'g', 'q') for tk in onset)     # a hummed or hissed consonant: the rise measured would be its length
        if after_rest and z - a >= .5 and not hummed:
            w = (et >= a - .25) & (et <= a + .7)
            seg, st = edb[w], et[w]
            level = np.median(edb[(et >= a + .3) & (et <= a + .6)]) if ((et >= a + .3) & (et <= a + .6)).any() else None
            if level is not None and level > edb.max() - 30:
                lo = np.flatnonzero(seg > level - 20); hi = np.flatnonzero(seg > level - 3)
                if len(lo) and len(hi) and hi[0] > lo[0]:
                    rises.append(st[hi[0]] - st[lo[0]])
            mi = nt['midi'][0] if isinstance(nt['midi'], tuple) else nt['midi']
            v0 = pm[(pt >= a - .05) & (pt <= a + .12)]; v0 = v0[~np.isnan(v0)]
            v1 = pm[(pt >= a + .3) & (pt <= z - .05)]; v1 = v1[~np.isnan(v1)]
            if len(v0) >= 3 and len(v1) >= 5 and abs(np.median(v1) - mi) < .7:
                scoops.append(100 * (v0[0] - np.median(v1)))
    med = lambda v, k: float(np.median(v)) if len(v) >= k else None
    return med(slopes, 8), med(rises, 4), med(scoops, 4)


SWELL_SLOPE = 6.7      # dB of swell per dB-per-slice of climb, for the engine's own notes (checked by measuring its renders)


def note_swell(sc, part, x, sr, T):
    """How far one real singer swells into soft, held notes -> dB at piano (the engine's `swell`), or None when
    the piece has too few such notes.  Each note's level is taken in ten equal slices from start to end; the
    swell is read from how steeply slices 3-6 climb (the first two are partly consonant, and shift with any error in the timing), which for the
    engine's own notes is its depth divided by SWELL_SLOPE.  Only notes inside a phrase count: the first one is
    shaped by the entry and the last one tapers."""
    hop, n = 64, 256
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop]
    et = (np.arange(len(fr)) * hop + n / 2) / sr
    edb = 10 * np.log10((fr ** 2).mean(1) + 1e-10)
    notes = sc.parts[part]
    rows, soft = [], []
    for i, nt in enumerate(notes):
        a, z = T(nt['beat']), T(nt['beat'] + nt['dur'])
        w = float(np.clip((.66 - sc.dyn('voice', nt['beat'])) / .14, 0, 1) * np.clip((z - a - .3) / .4, 0, 1))
        first = i == 0 or T(notes[i - 1]['beat'] + notes[i - 1]['dur']) < a - .3
        last = i + 1 == len(notes) or T(notes[i + 1]['beat']) > z + .3
        e = edb[(et >= a) & (et <= z)]
        if w < .5 or z - a < .7 or first or last or len(e) < 30 or np.percentile(e, 80) < edb.max() - 30:   # shorter notes are mostly consonant at the start
            continue
        rows.append(np.maximum([np.mean(e[k * len(e) // 10:(k + 1) * len(e) // 10]) for k in range(10)] - np.percentile(e, 80), -30))
        soft.append(w)
    if len(rows) < 8:
        return None
    c = np.mean(rows, axis=0)
    return float(np.clip(np.polyfit(np.arange(4), c[2:6], 1)[0] * SWELL_SLOPE / np.mean(soft), 0, 12))


def note_decay(sc, part, x, sr, T):
    return note_shape(sc, part, x, sr, T)[0] or 0.


def shape_settings(sc, part, x, sr, clock, log=print):
    """Preset entries for how notes are shaped, from one isolated real voice."""
    T = lambda b: float(np.interp(b, clock[0], clock[1]))
    fade, attack, scoop = note_shape(sc, part, x, sr, T)
    swell = note_swell(sc, part, x, sr, T)
    out = {}
    if swell is not None:       # soft, held notes: how far each one swells in
        out['swell'] = round(swell, 1)
    if fade is not None:        # the engine's own notes fall too (each syllable's vowel fades toward the next): make up the difference
        from . import voice
        beats_, secs_ = clock[0], clock[1]
        full = (beats_, secs_, float(np.interp(sc.beats, beats_, secs_)) + 4)
        mine = voice.render_singer((part, 4, R.engine_notes(sc, part), full, {'TUNE.note_decay': 0.}))[4].astype(float)
        mine = resample_poly(mine, sr, voice.SR)
        if sr == 22050:         # like with like: the recording has a room around the voice, which holds a fading note up
            from . import compare
            room = compare.match_room(compare.dying(x, sc, part, T), mine, sc, part, T) or compare.USUAL_ROOM
            if room[1] > 0:
                mine = compare.reverb(mine, *room)
        own = note_shape(sc, part, mine, sr, T)[0]
        fade_ = float(np.clip(fade - (own if own is not None else -2.), -14, 5))
        out['note_decay'] = round(min(fade_, 0.) if swell is not None else fade_, 1)    # a swell is a shape of its own now, not a slope
    if attack is not None:      # the engine's rule for this piece's first dynamic gives one entry speed; scale it to the measured one
        dyn0 = sc.dyn('voice', sc.parts[part][0]['beat']) if sc.parts[part] else .74
        rule = .39 * float(np.clip(.09 + 1.5 * (.74 - dyn0), .05, .5))
        out['attack'] = round(float(np.clip(attack / rule, .6, 1.25)), 2)    # a small correction only: on one piece this measure said
                                                                             # "slower" where the first notes' own shape said "quicker"
    if scoop is not None:       # the engine begins a phrase about 45 cents under the note unless told otherwise
        out['scoop'] = round(float(np.clip(-scoop / 45, .15, 1.6)), 2)
    log('note shape in the recording: ' + ', '.join(f'{k} {v}' for k, v in (('fade (dB/s)', None if fade is None else round(fade, 1)),
        ('swell into soft notes (dB)', None if swell is None else round(swell, 1)),
        ('entry (ms)', None if attack is None else round(1000 * attack)), ('scoop (cents)', None if scoop is None else round(scoop))) if v is not None)
        + '  -> ' + ', '.join(f'{k} {v}' for k, v in out.items()))
    return out


# ------------------------------------------------------- unaccompanied: no accompaniment track ----
def from_voice_tracks(sc, parts, balanced, tracks, log=print):
    """Practice tracks of unaccompanied music: a balanced mix and, per part, "that voice with the rest quietly".
    Taking the right share of the balanced mix out of a part's track leaves the voice alone (the share is
    the one that leaves the quietest moments quietest).  -> (preset entries, {part: isolated voice})."""
    iso, out = {}, {}
    for part, P in zip(parts, tracks):
        n = min(len(P), len(balanced))
        blocks = lambda x: np.sqrt((x[:n // 4410 * 4410] ** 2).mean(1).reshape(-1, 4410).mean(1))
        c = min((np.percentile(blocks(P[:n] - g * balanced[:n]), 20), g) for g in np.arange(0, .6, .01))[1]
        iso[part] = resample_poly((P[:n] - c * balanced[:n]).mean(1), 1, 2)
        log(f'{R.NAMES.get(part, part)}: the other voices are in its track at {c:.2f} of their balanced level')
    first = parts[0]
    tm = timingmod.measure(sc, first, iso[first], R.SR // 2, None, log)
    on1 = np.array(sorted(n['beat'] for n in sc.parts[first]))
    for p2 in parts[1:]:
        t2 = timingmod.measure(sc, p2, iso[p2], R.SR // 2, None, log)
        if t2['agree'] < .6 or not sc.parts[p2]:
            continue
        on2 = np.array(sorted(n['beat'] for n in sc.parts[p2]))
        b = np.array(tm['beats']); s1, s2 = np.array(tm['secs']), np.interp(b, t2['beats'], t2['secs'])
        d1 = np.abs(b[:, None] - on1[None, :]).min(1); d2 = np.abs(b[:, None] - on2[None, :]).min(1)
        w = np.convolve(np.pad(np.clip((d1 - d2) / 8 + .5, 0, 1), 4, mode='edge'), np.ones(9) / 9, 'valid')
        tm['secs'] = [round(float(v), 3) for v in np.maximum.accumulate(s1 * (1 - w) + s2 * w)]
    out['timing'] = tm
    out.update(shape_settings(sc, first, iso[first], R.SR // 2, R.clock_for(sc, tm, absolute=True), log))
    return out, iso


# ----------------------------------------------------------------------- from recordings ----
def from_recordings(sc, part, balanced, accompaniment, predominant=None, muted=None, log=print, more=None):
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
    # The accompaniment leads.  Every isolated voice and the accompaniment track are followed through the piece
    # together (timing.track): the written piano attacks say exactly where each beat falls, the singers say which
    # beat it is.  (Blending maps fitted to each singer separately, as was done before, let them disagree by a
    # third of a second and made the voices lurch against the accompaniment.)
    singers = {}
    if 'part' in iso:
        singers[part] = (resample_poly(iso['part'].mean(1), 1, 2), R.SR // 2)
    for p2, pred2 in (more or {}).items():
        r2 = reference.isolate(sc, None, p2, balanced, accompaniment, pred2, None, log=lambda *a: None)
        if 'part' in r2 and sc.parts[p2]:
            singers[p2] = (resample_poly(r2['part'].mean(1), 1, 2), R.SR // 2)
    beats = np.arange(0, sc.beats + 1.)
    first = np.interp(beats, clock[0], clock[1])

    def fit(secs):          # how well a map agrees with the recordings: singers on pitch, and voices with the accompaniment
        on = [timingmod.on_pitch(sc, p2, x2, sr2, beats, secs) for p2, (x2, sr2) in singers.items()]
        on = [v for v in on if v == v]
        rows = timingmod.against_accompaniment(sc, {'beats': list(beats), 'secs': list(secs)}, acc[0], acc[1]) if sc.piano else []
        clear = [r for r in rows if r[2]]
        return (float(np.mean(on)) if on else None), (sum(abs(r[1]) <= .06 for r in clear) / len(clear) if clear else None), rows

    secs = timingmod.track(sc, beats, first, acc, singers, log)
    before, after = fit(first), fit(secs)
    worse = lambda b, a, slack: b is not None and a is not None and a < b - slack
    if worse(before[0], after[0], .02) or worse(before[1], after[1], .05):
        log('  following the recordings fitted them worse than the first, steadier timing did: keeping that')
        secs, after = first, before
    tm = dict(tm, beats=[float(b) for b in beats], secs=[round(float(v), 3) for v in secs], led='recordings')
    out['timing'] = tm
    clock = R.clock_for(sc, tm, absolute=True)
    for p2, (x2, sr2) in singers.items():
        log(f'  {R.NAMES.get(p2, p2)}: {100 * timingmod.on_pitch(sc, p2, x2, sr2, beats, secs):.0f}% of its notes are on pitch where the timing puts them')
    if sc.piano:
        log('  ' + timingmod.sync_report(after[2]))
    if 'part' in iso:
        out.update(shape_settings(sc, part, resample_poly(iso['part'].mean(1), 1, 2), R.SR // 2, clock, log))
    return out, iso
