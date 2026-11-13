"""Where does the generated voice differ from a real one?

One real singer alone (a part isolated from practice tracks) is set beside the same part sung by a few simulated
singers on the recording's own timing.  Both are measured the same way, note by note, from their spectra:

  tone        the spectrum of held notes in 16 bands, each voice relative to its own overall level
  shape       loudness through a held note, in ten slices from start to end
  colour      how each of six broad bands rises and falls through a note, relative to that band mid-note
  entries     the 120 ms before and the 200 ms after a syllable begins, band by band, against the level of
              the note that follows (consonants, attacks)
  releases    the last 200 ms of a phrase and the 150 ms after it, likewise
  contrasts   loud notes against soft ones and high against low: how much louder, how much brighter
  steadiness  how far level and brightness wander while a note is held

Everything is model minus real, in dB, and the largest differences are listed first - so that what is wrong shows
on the first piece that has it, without anyone having to think of the right question.  Because every table is
relative to the voice's own level, neither recording level nor microphone distance enters.

Like with like.  A real "isolated" voice still has its room around it and a little of the other parts, some 10-25 dB
under the singer; a simulated singer is dry.  Compared as they are, every consonant looks like a hole in the model
that the real singers do not have - the room fills theirs.  (That mistake was made here once: a "17 dB gap before
every stop" turned out to be the missing room, and the real singers' breaks are as long as the model's.)  So the
simulated voices are first put in a plain room chosen to make them die away after phrase ends as the recording
does, and only then measured.  Nothing looks further down than FLOOR dB under a note's own level, entries and
releases are found at 12 dB under it, and what follows a release is never listed as a difference: it was matched.
"""
import numpy as np
from scipy.signal import resample_poly
from . import helper, voice, render as R

SR, NFFT, HOP = 22050, 1024, 128
CENTRES = [float(hz) for hz, _ in voice.FIT['eq']]          # the bands of the voice's own tone curve
GROUPS = [(80, 300, 'under 300 Hz'), (300, 800, '300-800 Hz'), (800, 1800, '0.8-1.8 kHz'),
          (1800, 3600, '1.8-3.6 kHz'), (3600, 6000, '3.6-6 kHz'), (6000, 9500, 'over 6 kHz')]
SLICES = 10
ON = np.round(np.arange(-.12, .2001, .02), 3)               # seconds around the start of a syllable
OFF = np.round(np.arange(-.2, .1501, .025), 3)              # seconds around the end of a phrase
JOINS = (('on_rest', 'entries after a rest'), ('on_sung', 'inside a phrase, syllables that begin with a sung consonant (m n l r w y v z)'),
         ('on_stop', 'inside a phrase, syllables that begin with a stop or a hiss (p t k b d g s f h)'), ('on_vowel', 'inside a phrase, syllables that begin with a vowel'))
FLOOR = -22.                                                # dB under a note's level: below this a real recording shows its leftovers
SINGERS = (4, 2, 9)


def _bands():
    f = np.fft.rfftfreq(NFFT, 1 / SR)
    e = [80.] + [float(np.sqrt(a * b)) for a, b in zip(CENTRES, CENTRES[1:])] + [9500.]
    m16 = np.array([(f >= lo) & (f < hi) for lo, hi in zip(e, e[1:])], float)
    m6 = np.array([(f >= lo) & (f < hi) for lo, hi, _ in GROUPS], float)
    return m16, m6


M16, M6 = _bands()


def spectra(x):
    """-> frame times, and per frame the level (dB) in the 16 tone bands, the six broad bands, and overall."""
    fr = np.lib.stride_tricks.sliding_window_view(np.asarray(x, float), NFFT)[::HOP]
    win = np.hanning(NFFT)
    p16 = np.empty((len(fr), len(M16))); p6 = np.empty((len(fr), len(M6)))
    for i in range(0, len(fr), 4096):
        p = np.abs(np.fft.rfft(fr[i:i + 4096] * win, axis=1)) ** 2
        p16[i:i + 4096] = p @ M16.T; p6[i:i + 4096] = p @ M6.T
    db = lambda v: 10 * np.log10(v + 1e-12)
    return (np.arange(len(fr)) * HOP + NFFT / 2) / SR, db(p16), db(p6), db(p6.sum(1))


def measure(x, sc, part, T):
    """One voice, note by note.  x: mono audio at 22050 Hz; T: beats -> seconds in it.  -> a list of dicts."""
    t, d16, d6, dbb = spectra(x)
    top = np.percentile(dbb, 99)
    notes = sc.parts[part]
    at = lambda secs: np.clip(np.searchsorted(t, secs), 0, len(t) - 1)
    rows = []
    for i, n in enumerate(notes):
        a, z = T(n['beat']), T(n['beat'] + n['dur'])
        first = i == 0 or T(notes[i - 1]['beat'] + notes[i - 1]['dur']) < a - .3
        last = i + 1 == len(notes) or T(notes[i + 1]['beat']) > z + .3
        w = np.flatnonzero((t >= a) & (t <= z))
        if z - a < .25 or len(w) < 8:
            continue
        u = (t[w] - a) / (z - a)
        mid = w[(u >= .3) & (u <= .8)]
        if len(mid) < 4 or np.median(dbb[mid]) < top - 35:          # not sung here, or lost in the separation
            continue
        midi = n['midi'][0] if isinstance(n['midi'], tuple) else n['midi']
        r = dict(i=i, m=n['m'], dur=z - a, dyn=sc.dyn('voice', n['beat']), midi=midi, first=first, last=last,
                 level=float(np.median(dbb[mid])), s16=np.median(d16[mid], axis=0), s6=np.median(d6[mid], axis=0))
        if z - a >= .45:
            sl = [w[(u >= k / SLICES) & (u < (k + 1) / SLICES)] for k in range(SLICES)]
            if all(len(s) for s in sl):
                r['shape'] = np.maximum([dbb[s].mean() - np.percentile(dbb[w], 80) for s in sl], FLOOR)
                r['colour'] = np.maximum([d6[s].mean(axis=0) - r['s6'] for s in sl], FLOOR)
            hold = w[(u >= .3) & (u <= .7)]
            if z - a >= .6 and len(hold) > 12:
                k = np.arange(len(hold))
                wander = lambda v: float(np.std(v - np.polyval(np.polyfit(k, v, 2), k)))
                r['wander'] = wander(dbb[hold]); r['shimmer'] = wander(d6[hold, 3] - d6[hold, 1])
        if n.get('lyric') not in (None, '', '_'):                   # a syllable begins here
            t_on = a
            if first:                                               # line the entry up on the sound itself
                k = np.flatnonzero((t >= a - .2) & (t <= a + .25))
                up = dbb[k] > r['level'] - 12
                run = np.flatnonzero(np.convolve(up, np.ones(7), 'valid') == 7)
                if len(run):
                    t_on = t[k[run[0]]]
                    r['lag'] = float(t_on - a)
            r['on'] = np.maximum(d6[at(t_on + ON)] - r['level'], 2 * FLOOR)
            c = (n.get('phon') or 'A').split()[0]                   # what the syllable begins with
            r['start'] = 'vowel' if c[0].isupper() else 'sung' if 'av' in voice.CONS.get(c, {}) else 'stop'
        if last:
            k = np.flatnonzero((t >= z - .5) & (t <= z + .3) & (dbb > r['level'] - 12))
            if len(k):
                t_off = t[k[-1]]
                r['early'] = float(z - t_off)
                j = at(t_off + OFF)
                r['off'] = np.maximum(np.c_[np.maximum(dbb[j] - r['level'], FLOOR), d6[j] - r['level']], 2 * FLOOR)
        rows.append(r)
    return rows


def tables(rows):
    """Average one voice's notes into the tables that are compared."""
    held = [r for r in rows if 'shape' in r]
    T = {'notes': len(rows), 'held': len(held)}
    if len(held) < 6:
        return T
    mean = lambda rs, key: np.mean([r[key] for r in rs], axis=0)
    T['tone'] = np.mean([r['s16'] - r['level'] for r in held], axis=0)
    for kind, rs in (('first', [r for r in held if r['first'] and not r['last']]), ('last', [r for r in held if r['last'] and not r['first']]),
                     ('middle', [r for r in held if not r['first'] and not r['last']])):
        if len(rs) >= 3:
            T['shape_' + kind] = mean(rs, 'shape')
    T['colour'] = mean(held, 'colour')
    T['bands'] = np.mean([r['s6'] - r['level'] for r in held], axis=0)       # the six broad bands mid-note, against the whole
    join = lambda kind: [r for r in rows if 'on' in r and not r['first'] and r['start'] == kind]
    for key, rs in (('on_rest', [r for r in rows if 'on' in r and r['first']]), ('on_sung', join('sung')), ('on_stop', join('stop')),
                    ('on_vowel', join('vowel')), ('off', [r for r in rows if 'off' in r])):
        if len(rs) >= 4:
            T[key] = mean(rs, 'on' if key != 'off' else 'off')
    for key in ('lag', 'early', 'wander', 'shimmer'):
        v = [r[key] for r in rows if key in r]
        if len(v) >= 4:
            T[key] = float(np.median(v))
    tilt = lambda r: r['s6'][3] - r['s6'][1]                         # the ring of the voice against its first resonance
    for key, lo, hi in (('loud_soft', [r for r in held if r['dyn'] < .58], [r for r in held if r['dyn'] >= .7]),
                        ('high_low', [r for r in held if r['midi'] < np.median([q['midi'] for q in held]) - 1],
                         [r for r in held if r['midi'] > np.median([q['midi'] for q in held]) + 1])):
        if len(lo) >= 5 and len(hi) >= 5:
            T[key] = np.array([np.mean([r['level'] for r in hi]) - np.mean([r['level'] for r in lo]),
                               np.mean([tilt(r) for r in hi]) - np.mean([tilt(r) for r in lo])])
    return T


def reverb(x, rt, wet):
    """A plain room: x plus `wet` times x through a noise burst that dies away in rt seconds."""
    from scipy.signal import fftconvolve
    n = int(1.2 * rt * SR); t = np.arange(n) / SR
    ir = np.random.default_rng(5).standard_normal(n) * np.exp(-6.91 * t / rt) * np.clip(t / .008, 0, 1)
    return x + wet * fftconvolve(x, ir / np.sqrt((ir ** 2).sum()))[:len(x)]


AFTER = np.array([.03, .06, .1, .15, .22, .3])      # seconds after a release at which the dying sound is read
USUAL_ROOM = (2.2, .35)                             # the room most of the practice tracks seen so far turned out to have


def dying(x, sc, part, T):
    """How the sound dies after the ends of phrases: its level against the last note's, at AFTER -> array or None."""
    win = int(.04 * SR)
    c = np.cumsum(np.r_[0., np.asarray(x, float) ** 2])
    lev = lambda t: 10 * np.log10((c[min(int(t * SR) + win, len(x))] - c[max(min(int(t * SR), len(x)) - win, 0)]) / (2 * win) + 1e-12)
    notes = sc.parts[part]; rows = []
    for i, n in enumerate(notes):
        a, z = T(n['beat']), T(n['beat'] + n['dur'])
        if z - a < .3 or not (i + 1 == len(notes) or T(notes[i + 1]['beat']) > z + .45):
            continue
        ref = np.median([lev(a + u * (z - a)) for u in np.linspace(.3, .8, 9)])
        ts = np.arange(z - .5, z + .3, .01)
        up = [t for t in ts if lev(t) > ref - 12]
        if up:
            rows.append(np.maximum([lev(up[-1] + d) - ref for d in AFTER], -30))
    return np.mean(rows, axis=0) if len(rows) >= 3 else None


def match_room(target, sim, sc, part, T):
    """The plain room in which a dry simulated voice dies away after phrase ends as the recording does -> (rt, wet) or None."""
    if target is None:
        return None
    from scipy.signal import fftconvolve
    best = None
    for rt in (.3, .6, 1., 1.5, 2.2, 3.2):
        n = int(1.2 * rt * SR); t = np.arange(n) / SR
        ir = np.random.default_rng(5).standard_normal(n) * np.exp(-6.91 * t / rt) * np.clip(t / .008, 0, 1)
        tail = fftconvolve(sim, ir / np.sqrt((ir ** 2).sum()))[:len(sim)]
        for wet in (0., .03, .06, .12, .2, .35, .6, 1., 1.7):
            got = dying(sim + wet * tail, sc, part, T)
            if got is not None:
                err = float(np.mean((got - target) ** 2))
                if best is None or err < best[0]:
                    best = (err, rt, wet)
    return best[1:] if best else None


def simulate(sc, part, timing=None, singers=SINGERS, settings=None, pool=True):
    """The part by a few simulated singers, on the recording's clock.  -> ([audio at 22050 Hz], beats -> seconds)."""
    beats, secs = R.clock_for(sc, timing, absolute=bool(timing))
    clock = (beats, secs, float(np.interp(sc.beats, beats, secs)) + 4)
    jobs = [(part, int(i), R.engine_notes(sc, part), clock, dict(settings or {})) for i in singers]
    if pool:
        from multiprocessing import Pool
        with Pool(len(jobs), initializer=helper) as p:
            outs = p.map(voice.render_singer, jobs)
    else:
        outs = [voice.render_singer(j) for j in jobs]
    return [resample_poly(o[4].astype(float), SR, voice.SR) for o in outs], (lambda b: float(np.interp(b, beats, secs)))


def compare(real_rows, model_rows):
    """-> {'real': tables, 'model': tables averaged over the simulated singers, 'diff': model minus real, 'worst': measures}."""
    Tr = tables(real_rows); Tm = [tables(m) for m in model_rows]
    keys = [k for k in Tr if k not in ('notes', 'held') and all(k in t for t in Tm)]
    model = {k: np.mean([t[k] for t in Tm], axis=0) for k in keys}
    diff = {k: model[k] - Tr[k] for k in keys}
    # where in the piece: per note, how far the model's shape is from the singer's (the usual difference taken out)
    worst = []
    if 'shape_middle' in diff:
        real = {r['i']: r for r in real_rows if 'shape' in r}
        per = {}
        for i, r in real.items():
            ms = [q['shape'] for m in model_rows for q in m if q['i'] == i and 'shape' in q]
            if ms:
                kind = 'first' if r['first'] and not r['last'] else 'last' if r['last'] and not r['first'] else 'middle'
                usual = diff.get('shape_' + kind, 0)
                per.setdefault(r['m'], []).append(float(np.sqrt(np.mean((np.mean(ms, axis=0) - r['shape'] - usual) ** 2))))
        worst = sorted(((float(np.mean(v)), m) for m, v in per.items()), reverse=True)[:6]
    return {'real': Tr, 'model': model, 'diff': diff, 'worst': worst}


# ------------------------------------------------------------------------------- words ----
def _runs(v, thr):
    """Stretches of one sign where |v| >= thr -> [(first index, last index, the largest value)]."""
    out, i = [], 0
    while i < len(v):
        if abs(v[i]) >= thr:
            j = i
            while j + 1 < len(v) and abs(v[j + 1]) >= thr and np.sign(v[j + 1]) == np.sign(v[i]):
                j += 1
            out.append((i, j, float(v[i + int(np.argmax(np.abs(v[i:j + 1])))])))
            i = j + 1
        else:
            i += 1
    return out


def findings(diff, real=None, model=None, agree=None, of=0):
    """The differences worth a look, largest first -> [(size against its threshold, sentence)].
    agree: per table, how many of `of` singers show each cell's difference (for a median over several singers)."""
    F = []
    more = lambda d: 'stronger' if d > 0 else 'weaker'

    def add(key, v, thr, text, cell=None):
        n = ''
        if agree is not None and key in agree and cell is not None:
            n = f'  [{int(np.asarray(agree[key])[cell])} of {of} singers]'
        F.append((abs(v) / thr, text + n))

    if 'tone' in diff:
        for i, j, v in _runs(diff['tone'], 3.):
            k = i + int(np.argmax(np.abs(diff['tone'][i:j + 1])))
            where = f'around {CENTRES[i]:.0f} Hz' if i == j else f'from {CENTRES[i]:.0f} to {CENTRES[j]:.0f} Hz'
            add('tone', v, 3., f'tone: {where} the model is up to {abs(v):.0f} dB {more(v)} than the singer', k)
    pct = lambda k: f'{100 * k // SLICES}%'
    for kind, name in (('middle', 'notes inside a phrase'), ('first', 'the first note of a phrase'), ('last', 'the last note of a phrase')):
        d = diff.get('shape_' + kind)
        if d is not None:
            for i, j, v in _runs(d, 3.):
                k = i + int(np.argmax(np.abs(d[i:j + 1])))
                add('shape_' + kind, v, 3., f'shape, {name}: from {pct(i)} to {pct(j + 1)} of the note the model is up to {abs(v):.0f} dB {"louder" if v > 0 else "softer"} than the singer', k)
    heard = lambda b: real is None or 'bands' not in real or min(real['bands'][b], model['bands'][b]) > -40    # a band neither voice really has says nothing
    if 'colour' in diff:
        for b, (_, _, band) in enumerate(GROUPS):
            for i, j, v in _runs(diff['colour'][:, b], 4.) if heard(b) else []:
                k = i + int(np.argmax(np.abs(diff['colour'][i:j + 1, b])))
                add('colour', v, 4., f'colour through the note, {band}: from {pct(i)} to {pct(j + 1)} the model has up to {abs(v):.0f} dB {"more" if v > 0 else "less"} than the singer (against the same band mid-note)', (k, b))
    for key, name in JOINS:
        d = diff.get(key)
        if d is not None:
            for b, (_, _, band) in enumerate(GROUPS):
                near = (ON <= .04) & ((ON >= -.04) | (key != 'on_rest'))      # before an entry there is only the room and the other parts
                early = (d[:, b] - (d[-4:, b].mean() if heard(b) else 0)) * near     # around the start, with the band's own tone difference taken out
                for i, j, v in _runs(early, 5.):
                    k = i + int(np.argmax(np.abs(early[i:j + 1])))
                    add(key, v, 5., f'{name}, {band}: from {1000 * ON[i]:+.0f} to {1000 * ON[j]:+.0f} ms around the start the model has up to {abs(v):.0f} dB {"more" if v > 0 else "less"} (against the note that follows)', (k, b))
    if 'off' in diff:
        for b, band in enumerate(['overall'] + [g[2] for g in GROUPS]):
            col = (diff['off'][:, b] - diff['off'][:3, b].mean()) * (OFF <= 0)                       # up to the release; what follows is the hall
            for i, j, v in _runs(col, 5.):
                k = i + int(np.argmax(np.abs(col[i:j + 1])))
                add('off', v, 5., f'phrase ends, {band}: from {1000 * OFF[i]:+.0f} to {1000 * OFF[j]:+.0f} ms around the release the model has up to {abs(v):.0f} dB {"more" if v > 0 else "less"}', (k, b))
    if real is not None and model is not None:
        for key, name in (('loud_soft', 'loud notes against soft ones'), ('high_low', 'high notes against low ones')):
            if key in diff:
                if abs(diff[key][0]) >= 2.5:
                    add(key, diff[key][0], 2.5, f"{name}: the singer's are {real[key][0]:+.1f} dB in level, the model's {model[key][0]:+.1f}", 0)
                if abs(diff[key][1]) >= 2.5:
                    add(key, diff[key][1], 2.5, f"{name}: the singer's are {real[key][1]:+.1f} dB brighter (1.8-3.6 kHz against 300-800 Hz), the model's {model[key][1]:+.1f}", 1)
        for key, name, unit in (('wander', 'level while a note is held wanders by', 'dB'), ('shimmer', 'brightness while a note is held wanders by', 'dB')):
            if key in diff and real[key] > 0 and not .67 < model[key] / real[key] < 1.5:
                add(key, 3 * np.log2(model[key] / real[key]), 1.75, f"{name} {real[key]:.2f} {unit} on the singer, {model[key]:.2f} on the model")
        if 'lag' in diff and abs(diff['lag']) >= .03:
            add('lag', diff['lag'], .03, f"entries after a rest come {1000 * real['lag']:+.0f} ms from the beat on the singer, {1000 * model['lag']:+.0f} ms on the model")
    return sorted(F, reverse=True)


def report(c, name='the singer', top=10):
    """The comparison as text."""
    d, real, model = c['diff'], c['real'], c['model']
    L = [f"{name}: {real.get('held', 0)} held notes of {real.get('notes', 0)} measured.  Everything below is model minus real, in dB."]
    room = c.get('room')
    if room and c.get('room_guessed'):
        L.append(f'This part has too few rests to hear how the recording dies away, so the simulated voices stand in the usual room of such tracks ({room[0]} s, level {room[1]}): read the entries with care.')
    elif room and room[1] > 0:
        L.append(f'The simulated voices stand in a room matched to how the recording dies away after phrase ends ({room[0]} s, level {room[1]}).')
    else:
        L.append('The simulated voices are dry' + (': the recording dies away as fast as they do.' if room else '.'))
    if 'tone' not in d:
        return L[0] + '\n  too few held notes to compare.'
    L.append('\nLargest differences')
    fs = findings(d, real, model)
    L += [f'  {i + 1:2d}. {text}' for i, (_, text) in enumerate(fs[:top])] or ['  none above the thresholds (3 dB of tone or shape, 4-5 dB in time)']
    L.append('\nTone of held notes (Hz)\n  ' + ' '.join('%5.0f' % hz for hz in CENTRES) + '\n  ' + ' '.join('%+5.1f' % v for v in d['tone']))
    L.append('\nLoudness through a held note (tenths of the note; real, model, difference)')
    for kind in ('first', 'middle', 'last'):
        if 'shape_' + kind in d:
            for label, v in (('real ', real['shape_' + kind]), ('model', model['shape_' + kind]), ('diff ', d['shape_' + kind])):
                L.append(f'  {kind:6s} {label} ' + ' '.join('%+5.0f' % x for x in v))
    L.append('\nThe six broad bands mid-note, against the whole voice (real, model)\n  ' + '   '.join(f'{g[2]} {a:+.0f} {b:+.0f}' for g, a, b in zip(GROUPS, real['bands'], model['bands'])))
    L.append('\nColour through a held note (rows: tenths of the note; columns: ' + ', '.join(g[2] for g in GROUPS) + ')')
    L += ['  %3d%%  ' % (100 * k // SLICES) + ' '.join('%+6.1f' % v for v in row) for k, row in enumerate(d['colour'])]
    for key, title in JOINS:
        if key in d:
            L.append(f'\n{title[0].upper() + title[1:]}, against the level of the note that follows (rows: ms from the start; columns as above)')
            L += ['  %+5.0f  ' % (1000 * ON[k]) + ' '.join('%+6.1f' % v for v in row) for k, row in enumerate(d[key])]
    if 'off' in d:
        L.append('\nPhrase ends, against the level of the note (rows: ms from the release; columns: overall, then as above)')
        L += ['  %+5.0f  ' % (1000 * OFF[k]) + ' '.join('%+6.1f' % v for v in row) for k, row in enumerate(d['off'])]
    L.append('\nOther measures (real, model)')
    for key, title, f in (('wander', 'level wanders while held, dB', '%.2f'), ('shimmer', 'brightness wanders while held, dB', '%.2f'),
                          ('early', 'phrases end before the written end, s', '%.2f'), ('lag', 'entries after a rest, s from the beat', '%+.3f')):
        if key in d:
            L.append(f'  {title:44s} {f % real[key]:>7s} {f % model[key]:>7s}')
    for key, title in (('loud_soft', 'loud against soft notes'), ('high_low', 'high against low notes')):
        if key in d:
            L.append(f'  {title + ": louder by, dB":44s} {real[key][0]:+7.1f} {model[key][0]:+7.1f}')
            L.append(f'  {title + ": brighter by, dB":44s} {real[key][1]:+7.1f} {model[key][1]:+7.1f}')
    if c['worst']:
        L.append("\nMeasures where the notes' shapes are furthest from the singer's, beyond the usual difference: "
                 + ', '.join(f'{m} ({v:.1f} dB)' for v, m in c['worst']))
    return '\n'.join(L)


def run(sc, part, x, sr, timing, singers=SINGERS, settings=None, pool=True):
    """Compare a real voice (mono audio x at sr, on the clock `timing` describes) with the model, the model standing in
    a room matched to the recording.  -> see compare(), plus 'room': (seconds, level) or None."""
    x = np.asarray(x, float)
    if sr != SR:
        x = resample_poly(x, SR, sr)
    sims, T = simulate(sc, part, timing, singers, settings, pool)
    room = match_room(dying(x, sc, part, T), sims[0], sc, part, T)          # like with like: the model in the recording's room
    guessed = room is None                                                  # a part with no rests has no phrase ends to listen to
    if guessed:
        room = USUAL_ROOM
    if room[1] > 0:
        sims = [reverb(y, *room) for y in sims]
    c = compare(measure(x, sc, part, T), [measure(y, sc, part, T) for y in sims])
    c['room'], c['room_guessed'] = room, guessed
    return c


def across(results, names):
    """Several singers at once: the median of their differences and, cell by cell, how many of them share it.
    -> (median diff, agree, text)"""
    keys = [k for k in results[0]['diff'] if all(k in r['diff'] for r in results)]
    thr = {'tone': 1.5, 'colour': 2., 'on_rest': 2.5, 'on_sung': 2.5, 'on_stop': 2.5, 'on_vowel': 2.5, 'off': 2.5, 'loud_soft': 1.25, 'high_low': 1.25}
    med, agree = {}, {}
    for k in keys:
        stack = np.array([r['diff'][k] for r in results])
        med[k] = np.median(stack, axis=0)
        t = thr.get(k, 1.5)
        agree[k] = ((np.sign(stack) == np.sign(med[k])) & (np.abs(stack) >= t)).sum(axis=0)
    scal = lambda side, k: float(np.median([r[side][k] for r in results]))
    real = {k: (scal('real', k) if np.ndim(results[0]['real'][k]) == 0 else np.median([r['real'][k] for r in results], axis=0)) for k in keys}
    model = {k: (scal('model', k) if np.ndim(results[0]['model'][k]) == 0 else np.median([r['model'][k] for r in results], axis=0)) for k in keys}
    fs = findings(med, real, model, agree, len(results))
    L = [f'Across {len(results)} singers ({", ".join(names)}): the median difference, and how many singers show it']
    L += [f'  {i + 1:2d}. {text}' for i, (_, text) in enumerate(fs[:14])]
    return med, agree, '\n'.join(L)
