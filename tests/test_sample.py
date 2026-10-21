import shutil
import sys
from pathlib import Path

import pytest

from common import read_json, write_output
from sample import (baseline_times, extract_thumb, loud_times, merge_times, rescan,
                    sample_project, scene_times)


def test_scene_times_detects_cut(cut_clip):
    times = scene_times(cut_clip, 10.0)
    assert len(times) == 1
    assert times[0] == pytest.approx(1.5, abs=0.1)


def test_loud_times_detects_burst(loud_clip):
    times = loud_times(loud_clip, 3, 8.0)
    assert len(times) == 1
    assert times[0] == pytest.approx(2.15, abs=0.4)


def test_loud_times_silent_empty(silent_clip):
    assert loud_times(silent_clip, 3, 8.0) == []


def test_baseline_times():
    assert baseline_times(35, 10) == [5, 15, 25]
    assert baseline_times(2.8, 10) == [1.4]


def test_merge_prefers_scene():
    assert merge_times([(1.0, 'baseline'), (1.4, 'scene')], 10, 1.5) == [(1.4, 'scene')]


def test_merge_clamps_and_sorts():
    out = merge_times([(9.99, 'baseline'), (-1.0, 'loud'), (4.0, 'scene')], 10, 1.5)
    assert out == [(0.0, 'loud'), (4.0, 'scene'), (9.95, 'baseline')]


def test_candidates_short_clip(tmp_path, short_clip):
    root = tmp_path / 'p'
    root.mkdir()
    shutil.copy(short_clip, root / 'short.MP4')
    data = sample_project(root)
    assert len(data['candidates']) >= 1
    assert all(c['t'] < 0.8 for c in data['candidates'])


def test_thumbs_in_cache_not_project(project):
    data = sample_project(project)
    assert data['candidates']
    for c in data['candidates']:
        thumb = Path(c['thumb'])
        assert thumb.exists()
        assert project.resolve() not in thumb.resolve().parents
    assert [c['id'] for c in data['candidates']] == [f'c{i:04d}' for i in range(1, len(data['candidates']) + 1)]
    assert (project / 'moments.json').exists()
    assert data['scores'] == {} and data['groups'] == [] and data['must_find'] == []


def test_sample_refuses_existing(project):
    sample_project(project)
    with pytest.raises(FileExistsError):
        sample_project(project)
    sample_project(project, overwrite=True)


def test_rescan_appends_ids(project):
    data = sample_project(project)
    before = data['candidates']
    scores = {before[0]['id']: {'desc': 'kept'}}
    stored = read_json(project / 'moments.json')
    stored['scores'] = scores
    write_output(project, 'moments.json', stored, overwrite=True)
    new = rescan(project, ['22.08/square.MP4'], 0.5)
    after = read_json(project / 'moments.json')
    ids = [c['id'] for c in after['candidates']]
    assert new and len(ids) == len(set(ids))
    assert ids[:len(before)] == [c['id'] for c in before]
    assert min(c['id'] for c in new) > max(c['id'] for c in before)
    assert after['scores'] == scores
    assert all(Path(c['thumb']).exists() for c in new)


def test_extract_thumb(cut_clip, tmp_path):
    out = extract_thumb(cut_clip, 1.0, tmp_path / 'x' / 't.jpg', 160)
    assert out.exists() and out.stat().st_size > 0


def test_extract_thumb_rejects_stale_file(cut_clip, tmp_path):
    out = tmp_path / 't.jpg'
    out.write_bytes(b'stale')
    with pytest.raises(RuntimeError):
        extract_thumb(cut_clip, 100.0, out, 160)
    assert not out.exists()


def _fail_once(monkeypatch, fail_at_call=1):
    import sample
    real = sample.extract_thumb
    calls = {'n': 0}

    def flaky(path, t, out, width):
        calls['n'] += 1
        if calls['n'] == fail_at_call:
            raise RuntimeError(f'thumbnail failed at {t:.3f}s in {path}: boom')
        return real(path, t, out, width)

    monkeypatch.setattr(sample, 'extract_thumb', flaky)


def test_sample_skips_failed_thumbnail(project, monkeypatch, capsys):
    baseline = len(sample_project(project)['candidates'])
    _fail_once(monkeypatch)
    skipped = []
    data = sample_project(project, overwrite=True, skipped=skipped)
    assert len(data['candidates']) == baseline - 1
    assert [c['id'] for c in data['candidates']] == [f'c{i:04d}' for i in range(1, baseline)]
    assert len(skipped) == 1 and '22.08/square.MP4 @ ' in skipped[0] and 'boom' in skipped[0]
    assert 'warning: skipped' in capsys.readouterr().err


def test_rescan_skips_failed_thumbnail(project, monkeypatch):
    sample_project(project)
    _fail_once(monkeypatch)
    skipped = []
    new = rescan(project, ['22.08/square.MP4'], 0.5, skipped=skipped)
    assert new and len(skipped) == 1


def test_cli_lists_skipped(project, monkeypatch, capsys):
    import sample
    _fail_once(monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['sample.py', str(project)])
    sample.main()
    out = capsys.readouterr().out
    assert 'skipped 1 timestamp' in out and '22.08/square.MP4 @ ' in out


def test_sample_overwrite_clears_cached_scores(project):
    from common import cache_dir
    sample_project(project)
    scores = cache_dir(project) / 'scores'
    scores.mkdir(parents=True, exist_ok=True)
    (scores / 'batch-c0001.json').write_text('{}')
    sample_project(project, overwrite=True)
    assert not scores.exists() or not any(scores.iterdir())


def _brief(root, force_exclude):
    write_output(root, 'brief.json', {'type': 'trip', 'source': str(root), 'description': '',
                                      'timeline': '', 'tone': '', 'must_find': [],
                                      'keep_memories': [], 'target_min': [5, 10], 'quality': 60,
                                      'music': None, 'force_include': [],
                                      'force_exclude': force_exclude})


def test_sample_skips_force_excluded_files(project, capsys):
    _brief(project, ['wide.MP4', '25.08', 'selfie stick'])
    data = sample_project(project)
    files = {c['file'] for c in data['candidates']}
    assert files == {'22.08/square.MP4'}


def test_cli_lists_force_excluded(project, monkeypatch, capsys):
    import sample
    _brief(project, ['22.08/wide.MP4'])
    monkeypatch.setattr(sys, 'argv', ['sample.py', str(project)])
    sample.main()
    out = capsys.readouterr().out
    assert 'not sampled (force_exclude): 22.08/wide.MP4' in out
