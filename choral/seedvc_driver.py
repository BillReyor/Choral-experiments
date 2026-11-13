"""Re-voice clips with Seed-VC's singing model: each source keeps its notes, words and timing and takes the voice of a reference clip.

    python seedvc_driver.py SEED_VC_DIR JOBS.json
    jobs: [{"source": wav, "reference": wav, "out": wav, "steps": 10, "cfg": 0.7, "seed": 0}, ...]

This script drives https://github.com/Plachtaa/seed-vc (GPL-3.0) and follows that project's own inference.py.  It is
run with the Python of the environment Seed-VC is installed in, as a program of its own - it imports nothing from the
choral package.  choral/setup_voices.py installs the model and writes the command that revoice.py runs.
The models are loaded once, and each reference voice is analysed once, for all jobs.

The model's two heavy stages (the diffusion and the vocoder) run in half precision, as the model's own script does by
default: 0.6 of the time on Apple's graphics chip, and the same sound (over 32 stretches its spectra lie 0.13 dB from
full precision's, 0.23 in the worst stretch; another draw of the same singer lies 1.8 dB away).  CHORAL_FULL_PRECISION=1
turns it off.  A stretch that comes out broken that way - not a number, silent - is done again in full precision.

The model's files are fetched the first time (about 2.3 GB, into the Seed-VC folder); after that it works offline.
HF_HUB_OFFLINE=0 lets it fetch."""
import sys, os, json, time, types
os.environ.setdefault('HF_HUB_OFFLINE', '1'); os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1'); os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')
import numpy as np

repo, jobs_file = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
jobs = json.load(open(jobs_file))
os.chdir(repo); sys.path.insert(0, repo)
import warnings; warnings.simplefilter('ignore')
import torch, torchaudio, librosa, soundfile as sf
import inference as I

t0 = time.time()
model, semantic_fn, f0_fn, vocoder_fn, campplus_model, mel_fn, mel_fn_args = I.load_models(types.SimpleNamespace(f0_condition=True, checkpoint=None, config=None, fp16=False))
device = I.device
HALF = device.type in ('mps', 'cuda') and os.environ.get('CHORAL_FULL_PRECISION') != '1'
print('voice model loaded in %.0f s (%s%s)' % (time.time() - t0, device, ', half precision' if HALF else ''), flush=True)
sr, hop = 44100, 512
max_ctx = sr // hop * 30
ov_frames = 16; ov_wave = ov_frames * hop
voices = {}


def semantic(w16):
    if w16.size(-1) <= 16000 * 30:
        return semantic_fn(w16)
    out, buf, at = [], None, 0
    while at < w16.size(-1):
        chunk = w16[:, at:at + 16000 * 30] if buf is None else torch.cat([buf, w16[:, at:at + 16000 * 25]], dim=-1)
        s = semantic_fn(chunk)
        out.append(s if at == 0 else s[:, 50 * 5:])
        buf = chunk[:, -16000 * 5:]
        at += 30 * 16000 if at == 0 else chunk.size(-1) - 16000 * 5
    return torch.cat(out, dim=1)


_mel = lambda f: 1127. * np.log(1. + f / 700.)
_A = (256 - 2) / (_mel(1100.) - _mel(50.)); _B = _mel(50.) * _A - 1.


def steady_steps(f0, margin=.8):
    """The pitch as the model will be told it, without flicker.  The model rounds pitch to one of 256 steps (15 to 43
    cents wide in a man's range).  A held pitch that lies near the edge of a step falls now on one side, now on the
    other, and the model sings the two steps in turn: jerks of a quarter tone many times a second.  So a step is
    kept until the pitch is `margin` steps from its middle, and the model is given the middle of the step."""
    out = np.array(f0, np.float32); cur = None
    for i, f in enumerate(out):
        if not f > 0:
            cur = None; continue
        x = _mel(float(f)) * _A - _B
        if cur is None or abs(x - cur) > margin:
            cur = round(x)
        out[i] = 700. * (np.exp((cur + _B) / _A / 1127.) - 1.)
    return out


class SoftPitch(torch.nn.Module):
    """The model's table of 256 pitch steps, read between the steps.  Told `at` (the pitch in steps, with its fraction),
    it gives a blend of the two neighbouring entries instead of the nearest one: a slide stays a slide, not a staircase,
    and a held pitch near the edge of a step does not flicker between two."""
    def __init__(self, table):
        super().__init__(); self.table = table; self.at = None

    def forward(self, idx):
        if self.at is None or self.at.shape != idx.shape:
            return self.table(idx)
        lo = self.at.floor().clamp(1, 254); frac = (self.at - lo).clamp(0, 1).unsqueeze(-1)
        soft = (1 - frac) * self.table(lo.long()) + frac * self.table((lo + 1).long())
        return torch.where((self.at > 1).unsqueeze(-1), soft, self.table(idx))


soft_pitch = SoftPitch(model.length_regulator.f0_embedding)
model.length_regulator.f0_embedding = soft_pitch


@torch.no_grad()
def voice_of(path):
    """What the model needs to know about a reference voice: worked out once."""
    if path not in voices:
        ref = torch.tensor(librosa.load(path, sr=sr)[0][:sr * 25]).unsqueeze(0).float().to(device)
        ref16 = torchaudio.functional.resample(ref, sr, 16000)
        mel2 = mel_fn(ref)
        feat2 = torchaudio.compliance.kaldi.fbank(ref16, num_mel_bins=80, dither=0, sample_frequency=16000)
        style2 = campplus_model((feat2 - feat2.mean(dim=0, keepdim=True)).unsqueeze(0))
        F0 = torch.from_numpy(np.asarray(f0_fn(ref16[0], thred=0.03), np.float32)).to(device)[None]
        prompt = model.length_regulator(semantic_fn(ref16), ylens=torch.LongTensor([mel2.size(2)]).to(device), n_quantizers=3, f0=F0)[0]
        voices[path] = (mel2, style2, prompt)
    return voices[path]


@torch.no_grad()
def convert(source, reference, steps=10, cfg=.7, seed=0, steady=False, soft=False, half=False):
    torch.manual_seed(seed)
    mel2, style2, prompt = voice_of(reference)
    wav = librosa.load(source, sr=sr)[0]; true = len(wav)
    whole = int(np.ceil(true / sr)) * sr                  # sources of a few fixed lengths: the graphics chip prepares the model anew for every new length
    if whole / hop <= max_ctx - mel2.size(2) - 2:
        wav = np.pad(wav, (0, whole - true))
    src = torch.tensor(wav).unsqueeze(0).float().to(device)
    src16 = torchaudio.functional.resample(src, sr, 16000)
    mel = mel_fn(src)
    f0 = np.asarray(f0_fn(src16[0], thred=0.03), np.float32)
    if steady:
        f0 = steady_steps(f0)
    if soft:                                              # the pitch in steps, with its fraction (0 where there is no voice)
        soft_pitch.at = torch.from_numpy(np.where(f0 > 0, _mel(np.maximum(f0, 1.)) * _A - _B, 0.).astype(np.float32)).to(device)[None]
    f0 = torch.from_numpy(f0).to(device)[None]
    cond = model.length_regulator(semantic(src16), ylens=torch.LongTensor([mel.size(2)]).to(device), n_quantizers=3, f0=f0)[0]
    soft_pitch.at = None
    window = max_ctx - mel2.size(2)
    done, chunks, prev = 0, [], None
    while done < cond.size(1):
        part = cond[:, done:done + window]
        last = done + window >= cond.size(1)
        cat = torch.cat([prompt, part], dim=1)
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=half):
            y = model.cfm.inference(cat, torch.LongTensor([cat.size(1)]).to(device), mel2, style2, None, steps, inference_cfg_rate=cfg)[:, :, mel2.size(-1):]
            w = vocoder_fn(y.float()).float().squeeze()[None, :]
        if done == 0:
            if last:
                chunks.append(w[0].cpu().numpy()); break
            chunks.append(w[0, :-ov_wave].cpu().numpy()); prev = w[0, -ov_wave:]
        elif last:
            chunks.append(I.crossfade(prev.cpu().numpy(), w[0].cpu().numpy(), ov_wave)); break
        else:
            chunks.append(I.crossfade(prev.cpu().numpy(), w[0, :-ov_wave].cpu().numpy(), ov_wave)); prev = w[0, -ov_wave:]
        done += y.size(2) - ov_frames
    return np.concatenate(chunks)[:true]


def whole(y):
    """Whether a converted stretch is sound at all: numbers, within range, not silence."""
    return bool(np.isfinite(y).all()) and float(np.abs(y).max()) <= 1.01 and float(np.sqrt(np.mean(y ** 2))) > 1e-4


import contextlib, io
total = 0.; t1 = time.time(); again = 0
for k, j in enumerate(jobs, 1):
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):     # (the model prints a progress bar per chunk)
        y = convert(j['source'], j['reference'], j.get('steps', 10), j.get('cfg', .7), j.get('seed', 0), j.get('steady', False), j.get('soft', False), HALF)
        if HALF and not whole(y):
            again += 1
            y = convert(j['source'], j['reference'], j.get('steps', 10), j.get('cfg', .7), j.get('seed', 0), j.get('steady', False), j.get('soft', False), False)
    os.makedirs(os.path.dirname(j['out']), exist_ok=True)
    sf.write(j['out'], y, sr, subtype='PCM_16')
    total += len(y) / sr
    if k % 10 == 0 or k == len(jobs) or os.environ.get('EVERY'):
        print('  re-voiced %d of %d stretches: %.0f s of singing in %.0f s%s' % (k, len(jobs), total, time.time() - t1, ' (%d done again in full precision)' % again if again else ''), flush=True)
