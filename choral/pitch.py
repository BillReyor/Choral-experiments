"""Monophonic pitch tracking (YIN) and score-vs-recording comparison helpers."""
import numpy as np


def yin(x, sr, fmin=65., fmax=520., win=1024, hop=256, thresh=.18):
    """Return (times, midi) with NaN where unvoiced."""
    tmax = int(sr / fmin); tmin = int(sr / fmax)
    n = (len(x) - win - tmax) // hop
    idx = np.arange(n)[:, None] * hop + np.arange(win + tmax)[None, :]
    out_t = (np.arange(n) * hop + win / 2) / sr
    midi = np.full(n, np.nan)
    for a in range(0, n, 2000):
        fr = x[idx[a:a + 2000]]
        A = np.fft.rfft(fr[:, :win], 2 * (win + tmax), axis=1)
        B = np.fft.rfft(fr, 2 * (win + tmax), axis=1)
        c = np.fft.irfft(np.conj(A) * B, axis=1)[:, :tmax + 1]            # sum x_j x_{j+tau}
        cs = np.cumsum(fr ** 2, axis=1)
        e = cs[:, win - 1:win + tmax] - np.concatenate([np.zeros((len(fr), 1)), cs[:, :tmax]], axis=1)
        d = e[:, :1] + e - 2 * c
        cm = d[:, 1:] * np.arange(1, tmax + 1) / np.maximum(np.cumsum(d[:, 1:], axis=1), 1e-12)
        cm = np.concatenate([np.ones((len(fr), 1)), cm], axis=1)
        for i in range(len(fr)):
            row = cm[i]
            seg = row[tmin:tmax - 1]
            g = seg.min()
            if g > thresh or e[i, 0] < 1e-5 * win:
                continue
            # the shortest period that is a true local dip nearly as deep as the deepest one
            loc = np.where((seg <= g + .12) & (seg <= np.roll(seg, 1)) & (seg <= np.roll(seg, -1)))[0]
            t = (loc[0] if len(loc) else int(seg.argmin())) + tmin
            y0, y1, y2 = row[t - 1], row[t], row[t + 1]
            t = t + .5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)
            midi[a + i] = 69 + 12 * np.log2(sr / t / 440)
    return out_t, midi
