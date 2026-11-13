"""choral/check.py: from a machine's figures and two timings to a plain answer for each thing the program does.
The hardware and the timings are made up here; nothing is rendered."""
import json
import wave

import pytest

from choral import check as C

REF = dict(chip='Apple M5 Max', apple=True, memory=128, cores=18, disk=500, system='26.0')


def rows_of(mc, slow=1., rate=None, voices=False):
    rows, w = C.verdicts(mc, slow, rate, voices)
    return {r['key']: r for r in rows}, w


# ------------------------------------------------------------------ at once ----
@pytest.mark.parametrize('memory, cores, n', [(4, 8, 2), (8, 8, 2), (12, 8, 4), (16, 8, 6), (18, 18, 6), (32, 18, 10),
                                              (128, 18, 10), (128, 4, 4), (64, 1, 1), (0, 8, 2)])
def test_at_once(memory, cores, n):
    assert C.at_once(memory, cores) == n


@pytest.mark.parametrize('secs, said', [(30, 'about a minute'), (89, 'about a minute'), (95, 'about 2 minutes'), (600, 'about 10 minutes'),
                                        (5340, 'about 89 minutes'), (5400, 'about 1.5 hours'), (7200, 'about 2 hours')])
def test_minutes(secs, said):
    assert C.minutes(secs) == said


# ------------------------------------------------------------------ verdicts ----
def test_reference_machine_matches_its_own_measurements():
    """On the machine everything was measured on, twelve to a part, ten at once: 61 s for 204 s of music."""
    rows, w = rows_of(REF, slow=1.)
    assert w == 10
    quick = rows['quick']['secs']
    assert quick == pytest.approx(61 * 180 / C.REF_PIECE, abs=1)          # the measured 61 s, for a piece of three minutes
    assert rows['quick']['level'] == 'yes' and rows['quick']['time'] == 'about a minute'
    assert rows['read']['level'] == 'yes'
    assert [r for r in rows] == ['read', 'quick', 'small', 'full']


def test_slower_processor_takes_proportionally_longer():
    fast, _ = rows_of(REF, slow=1.)
    slow, _ = rows_of(REF, slow=3.)
    assert slow['quick']['secs'] == pytest.approx(3 * fast['quick']['secs'], abs=1)


def test_fewer_at_once_takes_longer():
    big, _ = rows_of(REF)
    small, w = rows_of(dict(REF, memory=8, cores=8))
    assert w == 2 and small['quick']['secs'] > big['quick']['secs']
    # 2 at once on the reference processor: (127/2 + 48) s for 204 s of music
    assert small['quick']['secs'] == pytest.approx((C.SUNG / 2 + C.ALONE) * 180 / C.REF_PIECE, abs=1)


def test_little_memory_makes_quick_listen_slow():
    rows, _ = rows_of(dict(REF, memory=4, cores=4))
    assert rows['quick']['level'] == 'slow' and 'little memory' in rows['quick']['why']


def test_very_slow_machine_quick_listen_slow():
    rows, _ = rows_of(REF, slow=20.)
    assert rows['quick']['secs'] > 900 and rows['quick']['level'] == 'slow'


def test_real_voices_need_an_apple_chip():
    rows, _ = rows_of(dict(REF, apple=False), rate=4.)
    for k in ('small', 'full'):
        assert rows[k]['level'] == 'no' and rows[k]['secs'] is None and rows[k]['time'] == '' and 'Apple chip' in rows[k]['why']


def test_real_voices_need_memory():
    rows, _ = rows_of(dict(REF, memory=8), rate=4.)
    assert rows['full']['level'] == 'no' and '8 GB' in rows['full']['why'] and rows['full']['secs'] is None


def test_real_voices_need_disk_unless_installed():
    rows, _ = rows_of(dict(REF, disk=2), voices=False)
    assert rows['small']['level'] == 'no' and 'disk' in rows['small']['why']
    rows, _ = rows_of(dict(REF, disk=2), voices=True)
    assert rows['small']['level'] == 'yes'


def test_real_voices_without_speed_test():
    rows, _ = rows_of(REF, rate=None, voices=False)
    assert rows['full']['level'] == 'yes' and rows['full']['secs'] is None and 'measured once' in rows['full']['why']
    rows, _ = rows_of(REF, rate=None, voices=True)
    assert 'did not finish' in rows['full']['why']


def test_real_voices_timed_from_model_rate():
    rows, _ = rows_of(REF, slow=1., rate=4.)
    quick = {k: rows[k]['secs'] for k in ('small', 'full')}
    # twelve to a part: 180 s * .8 sung * 4 parts * 12 singers converted at 4x, plus .04 s of work a second, plus the quick render
    singing = 180 * .8 * 4 * 12
    expect = singing / 4 + singing * .04 + rows['quick']['secs']
    assert quick['full'] == pytest.approx(expect, abs=2)
    assert quick['small'] < quick['full']
    assert rows['full']['level'] == rows['small']['level'] == 'yes' and rows['full']['why'] == ''      # about 34 minutes
    slow, _ = rows_of(REF, slow=1., rate=1.)
    assert slow['full']['secs'] > 3600 and slow['full']['level'] == 'slow' and 'long wait' in slow['full']['why']
    faster, _ = rows_of(REF, slow=1., rate=8.)
    assert faster['full']['secs'] < quick['full']


def test_real_voices_tight_memory_is_slow():
    rows, _ = rows_of(dict(REF, memory=12), rate=40.)
    assert rows['small']['level'] == 'slow' and 'close other apps' in rows['small']['why']


# ------------------------------------------------------------- the measurements ----
def test_machine_reports_plain_figures():
    mc = C.machine()
    assert set(mc) == {'chip', 'apple', 'memory', 'cores', 'disk', 'system'}
    assert mc['cores'] >= 1 and mc['memory'] >= 0 and mc['disk'] >= 0 and isinstance(mc['apple'], bool)


def test_model_rate_none_without_model(monkeypatch, tmp_path):
    from choral import revoice
    monkeypatch.setattr(revoice, 'command', lambda: None)
    assert C.model_rate() is None
    monkeypatch.setattr(revoice, 'command', lambda: ['python', 'driver.py'])
    monkeypatch.setattr(C, 'ROOT', str(tmp_path))                  # no voices added
    assert C.model_rate() is None


def _voices(tmp_path, n=2):
    d = tmp_path / '.svc' / 'voices'
    d.mkdir(parents=True)
    for i in range(n):
        with wave.open(str(d / f'v{i}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b'\0\0' * 8000)


class _Done:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode = stdout, returncode


def test_model_rate_from_what_the_model_says(monkeypatch, tmp_path):
    from choral import revoice
    _voices(tmp_path)
    monkeypatch.setattr(revoice, 'command', lambda: ['model'])
    monkeypatch.setattr(C, 'ROOT', str(tmp_path))
    seen = {}

    def run(cmd, **kw):
        seen['cmd'] = cmd
        seen['jobs'] = json.load(open(cmd[-1]))
        return _Done('model loaded\n' + ''.join(f're-voiced {i} of 4 stretches: {6 * i:.1f} s of singing in {t:.1f} s\n'
                                                 for i, t in zip(range(1, 5), (5.0, 6.5, 8.0, 9.5))))
    monkeypatch.setattr(C.subprocess, 'run', run)
    # the first stretch (which pays for getting ready) is left out: 18 s of singing in 4.5 s
    assert C.model_rate() == pytest.approx(18 / 4.5)
    assert seen['cmd'][0] == 'model' and len(seen['jobs']) == 4
    assert all(j['reference'].endswith('v1.wav') for j in seen['jobs'])


def test_model_rate_none_when_the_model_fails(monkeypatch, tmp_path):
    from choral import revoice
    _voices(tmp_path)
    monkeypatch.setattr(revoice, 'command', lambda: ['model'])
    monkeypatch.setattr(C, 'ROOT', str(tmp_path))
    monkeypatch.setattr(C.subprocess, 'run', lambda cmd, **kw: _Done('Traceback ...', 1))
    assert C.model_rate() is None
    monkeypatch.setattr(C.subprocess, 'run', lambda cmd, **kw: _Done('re-voiced 1 of 4 stretches: 6.0 s of singing in 5.0 s\n'))
    assert C.model_rate() is None


def test_main_prints_one_line_of_json(monkeypatch, capsys):
    from choral import revoice
    monkeypatch.setattr(C, 'machine', lambda: dict(REF))
    monkeypatch.setattr(C, 'sing_once', lambda: 2 * C.REF_SING)
    monkeypatch.setattr(revoice, 'command', lambda: None)
    monkeypatch.setattr(C.sys, 'argv', ['check'])
    C.main()
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith('result: ')
    r = json.loads(out[0][len('result: '):])
    assert r['slow'] == 2.0 and r['rate'] is None and r['voices'] is False and r['at_once'] == 10
    assert [row['key'] for row in r['rows']] == ['read', 'quick', 'small', 'full']
    assert r['machine'] == REF
