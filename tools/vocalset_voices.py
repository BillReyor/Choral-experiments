"""Men's voices for --voice, from a public collection of singers: one short clip per man, named for the part he sings.

    python tools/vocalset_voices.py [VocalSet.zip] [-o FOLDER]        then:  python -m choral PIECE.pdf --voice FOLDER

VocalSet - Wilkins, Seetharaman, Wahl and Pardo, "VocalSet: A Singing Voice Dataset", ISMIR 2018,
https://zenodo.org/records/1193957, Creative Commons Attribution 4.0 - is twenty professional singers recorded alone
for research.  This takes fourteen seconds of one song from each of nine of its men.  Give it the archive if you have
it; without one it fetches just those clips from zenodo.org (about 30 MB of the archive's 2 GB).  The clips are
the singers' work: keep the credit above with anything you publish that was made with them.

Which singing.  Each man sings the song twice: as he normally would, and "straight" - told to hold his vibrato back.
The sections get the normal singing: a line re-voiced from it has 2-5 dB more ring (2.4-3.6 kHz) in six voices of
nine and keeps its words as well or better in eight.  The soloist gets the straight one, for the reason given
below.  Either way the notes sung are the engine's, not his.

Who sings which part.  The men all sing the same songs in the same key, so pitch does not tell a bass from a tenor
here.  The size of the voice does: a larger throat and mouth put every resonance lower by the same ratio.  SHIFT is
that, measured on three songs per man against the average of the others, in semitones (each song within 0.45 of the
man's average; a line re-voiced in these voices keeps their order).  The largest voices sing bass, the smallest
first tenor.  The collection's male9 is a countertenor and male10 was the soloist of an earlier try; neither is
used.  To seat someone elsewhere, rename his file.

The soloist.  A listener heard the same solo in five of these voices and chose male3, a baritone, who also sings in
the baritone section - a chorus member stepping forward.  His solo is re-voiced from his straight singing: from it
the result has a quarter of the catches in the voice (moments without a clear period inside a held note: 1.1 a
second, against 4.6 from his normal singing)."""
import os, io, argparse, wave, zipfile, urllib.request
import numpy as np

URL = 'https://zenodo.org/api/records/1193957/files/VocalSet.zip/content'
SONG = 'caro'                      # the song all of them sing: fourteen seconds of it
#        man  part        SHIFT
SEATS = [(8, 'Bass', -1.49), (4, 'Bass', -1.30), (3, 'Baritone', -.76), (3, 'Solo', -.76), (2, 'Baritone', .03),
         (1, 'Tenor 2', .36), (11, 'Tenor 2', .39), (5, 'Tenor 1', .77), (7, 'Tenor 1', .95), (6, 'Tenor 1', 1.75)]
SR, SECONDS = 44100, 14


class Remote(io.RawIOBase):
    """A file on a web server, read a piece at a time (so that a few clips can be taken out of a large archive)."""
    def __init__(self, url):
        self.url, self.pos, self.got = url, 0, 0
        with urllib.request.urlopen(urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'python-urllib'})) as r:
            self.size = int(r.headers['Content-Length'])

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        q = urllib.request.Request(self.url, headers={'Range': 'bytes=%d-%d' % (self.pos, self.pos + n - 1), 'User-Agent': 'python-urllib'})
        with urllib.request.urlopen(q) as r:
            if r.status != 206:
                raise IOError('the server would not send part of the file; download VocalSet.zip and give it to this tool')
            data = r.read()
        b[:len(data)] = data; self.pos += len(data); self.got += len(data)
        return len(data)


def sung(x, floor=-35., gap=.25):
    """A recording without its silences: what is sung, with at most `gap` seconds left between phrases."""
    hop = SR // 100
    n = len(x) // hop
    e = np.sqrt((x[:n * hop] ** 2).reshape(n, hop).mean(1) + 1e-12)
    keep = np.zeros(n, bool); last = -10 ** 9
    for i in np.flatnonzero(e > e.max() * 10 ** (floor / 20)):
        if i - last <= int(gap * 100):
            keep[max(last, 0):i + 1] = True
        keep[i] = True; last = i
    return x[:n * hop].reshape(n, hop)[keep].ravel()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('archive', nargs='?', help='VocalSet.zip, if you have it')
    ap.add_argument('-o', '--out', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.svc', 'voices'))
    a = ap.parse_args()
    remote = None if a.archive else Remote(URL)
    z = zipfile.ZipFile(a.archive or io.BufferedReader(remote, 1 << 20))
    os.makedirs(a.out, exist_ok=True)
    for man, part, _ in SEATS:
        manner = 'straight' if part == 'Solo' else 'vibrato'           # (a few of the archive's files are misnamed: found by song)
        clip = next(n for n in z.namelist() if n.startswith('FULL/male%d/excerpts/%s/' % (man, manner)) and SONG in n.lower() and n.lower().endswith('.wav'))
        with wave.open(io.BytesIO(z.read(clip))) as w:
            sr, nc, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            x = np.frombuffer(w.readframes(w.getnframes()), {2: '<i2', 4: '<i4'}[sw]).reshape(-1, nc).mean(1) / 2. ** (8 * sw - 1)
        if sr != SR:
            from scipy.signal import resample_poly
            x = resample_poly(x, SR, sr)
        x = sung(x)[:SECONDS * SR].copy()
        k = SR // 20
        x[:k] *= np.linspace(0, 1, k); x[-k:] *= np.linspace(1, 0, k)
        f = os.path.join(a.out, '%s - VocalSet male%d.wav' % (part, man))
        with wave.open(f, 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((x / np.abs(x).max() * .7 * 32767).astype('<i2').tobytes())
        print('%-9s male%-2d -> %s' % (part, man, f), flush=True)
    if remote:
        print('fetched %.0f MB from zenodo.org' % (remote.got / 1e6))
    print('Voices: VocalSet (Wilkins, Seetharaman, Wahl, Pardo; ISMIR 2018), CC BY 4.0 - keep this credit with what you make with them.')


if __name__ == '__main__':
    main()
