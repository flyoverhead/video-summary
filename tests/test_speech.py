import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import common
import speech

SCRIPT = Path(speech.__file__)


def test_check_ok_with_fake_whisper(fake_whisper):
    assert speech.check() == []


def test_check_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setenv('VIDEO_SUMMARY_WHISPER_BIN', str(tmp_path / 'nope'))
    problems = speech.check()
    assert any('whisper-cli not found' in p for p in problems)


def test_check_missing_model(fake_whisper, monkeypatch, tmp_path):
    missing = tmp_path / 'missing.bin'
    monkeypatch.setenv('VIDEO_SUMMARY_WHISPER_MODEL', str(missing))
    problems = speech.check()
    assert len(problems) == 1
    assert 'model not found' in problems[0] and str(missing) in problems[0]


def test_check_binary_not_runnable(fake_whisper, monkeypatch, tmp_path):
    broken = tmp_path / 'broken'
    broken.write_text('#!/nonexistent/interpreter\n')
    broken.chmod(0o755)
    monkeypatch.setenv('VIDEO_SUMMARY_WHISPER_BIN', str(broken))
    assert any('not runnable' in p for p in speech.check())


def test_cli_check_ok(fake_whisper):
    res = subprocess.run([sys.executable, str(SCRIPT), 'check'], capture_output=True, text=True)
    assert res.returncode == 0
    assert f'whisper-cli: {fake_whisper}' in res.stdout
    assert 'model: ' in res.stdout


def test_cli_check_prints_install_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('VIDEO_SUMMARY_WHISPER_BIN', str(tmp_path / 'nope'))
    res = subprocess.run([sys.executable, str(SCRIPT), 'check'], capture_output=True, text=True)
    assert res.returncode == 1
    assert 'brew install whisper-cpp' in res.stdout


def test_parse_whisper_json():
    data = {'result': {'language': 'en'},
            'transcription': [{'offsets': {'from': 500, 'to': 1500}, 'text': ' one '},
                              {'offsets': {'from': 2000, 'to': 3200}, 'text': ' two'}]}
    lang, segs = speech.parse_whisper_json(data)
    assert lang == 'en'
    assert segs == [{'start': 0.5, 'end': 1.5, 'text': 'one'}, {'start': 2.0, 'end': 3.2, 'text': 'two'}]


def test_filter_segments_drops_fillers_and_repeats():
    texts = ['Thank you.', 'look', 'look', '...', 'Продолжение следует...', 'wow']
    segs = [{'start': i, 'end': i + 1, 'text': t} for i, t in enumerate(texts)]
    assert [s['text'] for s in speech.filter_segments(segs)] == ['look', 'wow']


def _snapshot(root):
    return sorted(root.rglob('*'))


def _probe(root):
    import probe
    data = probe.collect_probe(root)
    (root / 'probe.json').write_text(json.dumps(data))
    return data


def test_transcribe_project_writes_cache(project, fake_whisper):
    _probe(project)
    before = _snapshot(project)
    summary = speech.transcribe_project(project, progress=lambda *_: None)
    assert summary['clips'] == 3 and summary['with_speech'] == 3 and summary['failed'] == []
    assert summary['segments'] == 3
    for clip in ('22.08/square.MP4', '22.08/wide.MP4', '25.08/vertical.MP4'):
        tr = speech.load_transcript(project, clip)
        assert tr['file'] == clip and len(tr['segments']) == 1 and isinstance(tr['silences'], list)
        assert tr['error'] is None
    assert _snapshot(project) == before
    assert not list((common.cache_dir(project) / 'speech' / 'tmp').iterdir())


def test_transcribe_resumes(project, fake_whisper, monkeypatch, tmp_path):
    _probe(project)
    speech.transcribe_project(project, progress=lambda *_: None)
    payload = tmp_path / 'p.json'
    payload.write_text(json.dumps({'transcription': [{'offsets': {'from': 0, 'to': 1000}, 'text': 'changed'}]}))
    monkeypatch.setenv('FAKE_WHISPER_PAYLOAD', str(payload))
    summary = speech.transcribe_project(project, progress=lambda *_: None)
    assert speech.load_transcript(project, '22.08/square.MP4')['segments'][0]['text'] == 'look at this'
    assert summary['clips'] == 0
    speech.transcribe_project(project, overwrite=True, progress=lambda *_: None)
    assert speech.load_transcript(project, '22.08/square.MP4')['segments'][0]['text'] == 'changed'


def test_transcribe_skips_silent_and_excluded(project, fake_whisper, silent_clip):
    shutil.copy(silent_clip, project / '22.08' / 'silent.MP4')
    (project / 'brief.json').write_text(json.dumps({'force_exclude': ['25.08']}))
    _probe(project)
    assert sorted(speech.needs_transcript(project)) == ['22.08/square.MP4', '22.08/wide.MP4']
    speech.transcribe_project(project, progress=lambda *_: None)
    assert speech.load_transcript(project, '22.08/silent.MP4') is None
    assert speech.load_transcript(project, '25.08/vertical.MP4') is None
    assert speech.needs_transcript(project) == []


def test_transcribe_whisper_failure_recorded(project, fake_whisper, monkeypatch):
    _probe(project)
    monkeypatch.setenv('FAKE_WHISPER_EXIT', '1')
    summary = speech.transcribe_project(project, progress=lambda *_: None)
    assert sorted(summary['failed']) == ['22.08/square.MP4', '22.08/wide.MP4', '25.08/vertical.MP4']
    for clip in summary['failed']:
        tr = speech.load_transcript(project, clip)
        assert tr['error'] and tr['segments'] == []
    assert speech.needs_transcript(project) == []


def test_transcript_path_unicode_and_spaces(project, fake_whisper, square_clip):
    name = "день 1/it's DJI.MP4"
    path = speech.transcript_path(project, name)
    assert path.parent == common.cache_dir(project) / 'speech'
    assert re.fullmatch(r'[0-9a-f]{16}\.json', path.name)
    (project / 'день 1').mkdir()
    shutil.copy(square_clip, project / name)
    _probe(project)
    summary = speech.transcribe_project(project, progress=lambda *_: None)
    assert summary['failed'] == []
    assert speech.load_transcript(project, name)['segments']


def test_silences_detects_gap(loud_clip):
    found = speech.silences(loud_clip)
    assert any(a <= 0.5 and b >= 0.5 and 1.9 <= b <= 2.1 for a, b in found)


def test_said_at_window_and_limit():
    segs = [{'start': 1.0, 'end': 2.0, 'text': 'first words'}, {'start': 10.0, 'end': 11.0, 'text': 'second'}]
    assert speech.said_at(segs, 3, 2, 6, 200) == 'first words'
    assert speech.said_at(segs, 20, 2, 6, 200) is None
    assert speech.said_at(segs, 3, 2, 6, 5) == 'firs…'


def test_cli_transcribe_and_show(project, fake_whisper):
    _probe(project)
    res = subprocess.run([sys.executable, str(SCRIPT), 'transcribe', str(project)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert '3 clips, 3 with speech, 3 segments' in res.stdout
    res = subprocess.run([sys.executable, str(SCRIPT), 'show', str(project), '22.08/square.MP4'],
                         capture_output=True, text=True)
    assert '0.5–1.5 look at this' in res.stdout


def test_cli_transcribe_refuses_without_whisper(project, monkeypatch, tmp_path):
    _probe(project)
    monkeypatch.setenv('VIDEO_SUMMARY_WHISPER_BIN', str(tmp_path / 'nope'))
    res = subprocess.run([sys.executable, str(SCRIPT), 'transcribe', str(project)], capture_output=True, text=True)
    assert res.returncode == 1
    assert 'whisper-cli not found' in res.stdout and 'brew install whisper-cpp' in res.stdout
    assert not speech.transcript_path(project, '22.08/square.MP4').exists()


def _status(project, capsys):
    code = speech.main(['status', str(project)])
    return code, capsys.readouterr().out


CLIPS = ('22.08/square.MP4', '22.08/wide.MP4', '25.08/vertical.MP4')


def _moments(project, sources, files=('22.08/square.MP4',), t=1.0):
    common.write_output(project, 'moments.json', {'candidates': [
        {'id': f'c{i}{j}', 'file': f, 't': t, 'source': src, 'thumb': 'x'}
        for j, f in enumerate(files) for i, src in enumerate(sources, 1)], 'scores': {}}, overwrite=True)


def test_status_not_analysed_without_transcripts(project, capsys):
    _probe(project)
    _moments(project, ['scene'])
    code, out = _status(project, capsys)
    assert code == 1
    assert 'transcripts missing: 3' in out and '22.08/square.MP4' in out
    assert 'speech candidates: 0' in out and out.endswith('speech: not analysed\n')


def test_status_not_analysed_without_speech_candidates(project, fake_whisper, capsys):
    _probe(project)
    speech.transcribe_project(project, progress=lambda *_: None)
    _moments(project, ['scene'])
    code, out = _status(project, capsys)
    assert code == 1 and 'transcripts missing: 0' in out


def test_status_ok_after_add_speech(project, fake_whisper, capsys):
    _probe(project)
    speech.transcribe_project(project, progress=lambda *_: None)
    _moments(project, ['scene', 'speech'], CLIPS)
    code, out = _status(project, capsys)
    assert code == 0, out
    assert 'transcripts missing: 0' in out and 'speech candidates: 3' in out
    assert out.endswith('speech: ok\n')


def test_status_unreadable_transcript(project, fake_whisper, capsys):
    _probe(project)
    speech.transcribe_project(project, progress=lambda *_: None)
    speech.transcript_path(project, '22.08/square.MP4').write_text('{bad')
    _moments(project, ['scene', 'speech'], CLIPS)
    code, out = _status(project, capsys)
    assert code == 1
    assert 'transcript unreadable: 1 (first: 22.08/square.MP4)' in out
    assert out.endswith('speech: not analysed\n')


def test_status_no_moments(project, fake_whisper, capsys):
    _probe(project)
    speech.transcribe_project(project, progress=lambda *_: None)
    code, out = _status(project, capsys)
    assert code == 0 and 'speech candidates: no moments.json' in out


def test_status_ok_with_empty_transcripts_and_no_speech_candidates(project, capsys):
    from conftest import write_stub_transcripts
    _probe(project)
    write_stub_transcripts(project)
    _moments(project, ['scene'])
    code, out = _status(project, capsys)
    assert code == 0, out
    assert 'speech candidates: 0' in out and out.endswith('speech: ok\n')


def test_status_ok_when_speech_start_merged_into_scene(project, fake_whisper, capsys):
    _probe(project)
    speech.transcribe_project(project, progress=lambda *_: None)
    _moments(project, ['scene'], CLIPS, t=1.9)
    code, out = _status(project, capsys)
    assert code == 0, out


def test_status_not_analysed_when_speech_start_has_no_candidate(project, fake_whisper, capsys):
    _probe(project)
    speech.transcribe_project(project, progress=lambda *_: None)
    _moments(project, ['scene'], CLIPS, t=2.1)
    code, out = _status(project, capsys)
    assert code == 1 and out.endswith('speech: not analysed\n')


def test_status_reports_failed_transcription(project, fake_whisper, monkeypatch, capsys):
    _probe(project)
    monkeypatch.setenv('FAKE_WHISPER_EXIT', '1')
    speech.transcribe_project(project, progress=lambda *_: None)
    _moments(project, ['scene'], CLIPS)
    code, out = _status(project, capsys)
    assert code == 0, out
    assert re.search(r'^transcription failed: 3 \(first: \S+\.MP4\)$', out, re.M)


def test_status_without_probe_does_not_probe(project, monkeypatch, capsys):
    import sample
    monkeypatch.setattr(sample, 'collect_probe', lambda *_: (_ for _ in ()).throw(AssertionError('probed')))
    code, out = _status(project, capsys)
    assert code == 1 and 'no probe.json' in out
    assert not (project / 'probe.json').exists()
