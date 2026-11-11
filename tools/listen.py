"""Use a speech recognizer as a stand-in for ears.

    python tools/listen.py SCORE AUDIO.wav [--offset 1.0] [--bpm 100] [--every 8] [--timing absolute]

Cuts the recording into stretches of a few measures, transcribes each with whisper.cpp, and
reports how many of the score's own words came through.  Run it on a real recording of the same
piece as well: that number is the yardstick, because even real choirs are not 100% intelligible.

Needs `whisper-cli` (brew install whisper-cpp) and a model file; set WHISPER_MODEL to its path
(WHISPER_MODEL_MULTI, the multilingual model, for a score that is not in English).
"""
import argparse, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from choral import score as S, hear, render as R
from choral.timing import read_wav


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score'); ap.add_argument('audio')
    ap.add_argument('--offset', type=float, help='seconds before beat 1 (default: where choral.render puts it)')
    ap.add_argument('--bpm', type=float); ap.add_argument('--every', type=int, default=8)
    ap.add_argument('--timing', choices=['render', 'absolute'], default='render',
                    help="'absolute': the audio is a real recording on the score's measured timing")
    ap.add_argument('--part', help='count only this part\'s words')
    ap.add_argument('--model', help='model file (default: WHISPER_MODEL, or WHISPER_MODEL_MULTI for a score not in English)')
    a = ap.parse_args()
    sc = S.load(a.score)
    x, sr = read_wav(a.audio)
    if a.offset is not None or a.bpm:
        off, spb = (1.0 if a.offset is None else a.offset), 60 / (a.bpm or sc.tempo[0][1])
        T = lambda b: off + b * spb
    else:
        beats, secs = R.clock_for(sc, absolute=a.timing == 'absolute')
        T = lambda b: float(np.interp(b, beats, secs))
    u = hear.understood(sc, x, sr, T, a.model, a.every, [a.part] if a.part else None, log=print)
    print(f'words understood: {100 * u:.0f}%')


if __name__ == '__main__':
    main()
