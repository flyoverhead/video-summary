import probe
from common import read_json


def _clip(w, h, fps=25.0):
    return {'file': 'a.mp4', 'width': w, 'height': h, 'fps': fps}


def test_find_clips_recursive_ignores_lrf(project):
    found = probe.find_clips(project)
    assert len(found) == 3
    assert not any(str(p).endswith('.LRF') for p in found)


def test_probe_clip_reads_fps_and_audio(square_clip, wide_clip, vertical_clip, silent_clip):
    root = square_clip.parent
    sq = probe.probe_clip(root, square_clip)
    assert sq['fps'] == 25.0 and sq['audio_channels'] == 1
    wd = probe.probe_clip(root, wide_clip)
    assert wd['fps'] == 50.0 and wd['audio_channels'] == 2
    assert abs(probe.probe_clip(root, vertical_clip)['fps'] - 29.97) < 0.01
    assert probe.probe_clip(root, silent_clip)['audio_channels'] == 0


def test_probe_clip_relative_path(project):
    entry = probe.probe_clip(project, project / '22.08' / 'square.MP4')
    assert entry['file'] == '22.08/square.MP4'


def test_choose_frame_majority_square():
    frame = probe.choose_frame([_clip(320, 320), _clip(320, 320), _clip(480, 270)])
    assert frame['shape'] == 'square'
    assert (frame['width'], frame['height']) == (2560, 2560)


def test_choose_frame_wide():
    frame = probe.choose_frame([_clip(480, 270), _clip(480, 270), _clip(320, 320)])
    assert frame['shape'] == 'wide'
    assert (frame['width'], frame['height']) == (2560, 1440)


def test_choose_frame_vertical():
    frame = probe.choose_frame([_clip(270, 480), _clip(270, 480)])
    assert frame['shape'] == 'vertical'
    assert (frame['width'], frame['height']) == (1440, 2560)


def test_choose_frame_even_dimensions():
    frame = probe.choose_frame([_clip(1000, 667)])
    assert frame['width'] % 2 == 0 and frame['height'] % 2 == 0


def test_choose_frame_majority_fps():
    assert probe.choose_frame([_clip(320, 320, 25), _clip(320, 320, 25), _clip(320, 320, 50)])['fps'] == 25
    assert probe.choose_frame([_clip(320, 320, 25), _clip(320, 320, 50)])['fps'] == 50


def test_probe_project_sorted_and_writes(project):
    data = probe.probe_project(project)
    assert (project / 'probe.json').exists()
    assert read_json(project / 'probe.json') == data
    keys = [(c['created'], c['file']) for c in data['clips']]
    assert keys == sorted(keys)
    assert data['frame']['shape'] in ('square', 'wide', 'vertical')


def test_find_clips_skips_dotfiles_and_rendered_output(project):
    (project / '22.08' / '._square.MP4').write_bytes(b'junk')
    (project / 'SUMMARY_VIDEO.mp4').write_bytes(b'x')
    (project / 'SUMMARY_VIDEO.draft.mp4').write_bytes(b'x')
    names = sorted(p.name for p in probe.find_clips(project))
    assert names == ['square.MP4', 'vertical.MP4', 'wide.MP4']


def test_probe_project_skips_unprobeable(project, capsys):
    (project / '22.08' / 'audio.mp4').write_bytes(b'not a video')
    data = probe.probe_project(project)
    assert len(data['clips']) == 3
    assert 'audio.mp4' in capsys.readouterr().err


def test_probe_project_skips_audio_only(project, capsys):
    from common import run
    run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=d=1', '-c:a', 'aac',
         str(project / '22.08' / 'audio_only.mp4')])
    assert len(probe.probe_project(project)['clips']) == 3
    assert 'audio_only.mp4' in capsys.readouterr().err


def test_choose_frame_ignores_zero_fps():
    assert probe.choose_frame([_clip(320, 320, 0.0), _clip(320, 320, 25)])['fps'] == 25


def test_choose_frame_no_valid_fps():
    import pytest
    with pytest.raises(ValueError):
        probe.choose_frame([_clip(320, 320, 0.0)])


def test_fps_falls_back_to_avg_frame_rate(square_clip, monkeypatch):
    real = probe._ffprobe

    def fake(path, stream):
        data = real(path, stream)
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                s['r_frame_rate'] = '0/0'
        return data

    monkeypatch.setattr(probe, '_ffprobe', fake)
    assert probe.probe_clip(square_clip.parent, square_clip)['fps'] == 25.0


def test_created_filename_fallback(square_clip, tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(probe, '_mdls_created', lambda p: None)
    dst = tmp_path / 'DJI_20260825131640_0186_D.MP4'
    shutil.copy(square_clip, dst)
    assert probe.probe_clip(tmp_path, dst)['created'] == '2026-08-25T13:16:40Z'


def test_created_order_differs_from_filename_order(project, monkeypatch):
    import shutil
    monkeypatch.setattr(probe, '_mdls_created', lambda p: None)
    shutil.copy(project / '22.08' / 'square.MP4', project / 'DJI_20260101000000_0001_D.MP4')
    shutil.copy(project / '22.08' / 'square.MP4', project / 'DJI_20250101000000_0002_D.MP4')
    files = [c['file'] for c in probe.probe_project(project)['clips'] if c['file'].startswith('DJI_')]
    assert files == ['DJI_20250101000000_0002_D.MP4', 'DJI_20260101000000_0001_D.MP4']


def test_created_uses_mdls_before_filename(square_clip, tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(probe, '_mdls_created', lambda p: '2020-01-02T03:04:05Z')
    dst = tmp_path / 'DJI_20260825131640_0186_D.MP4'
    shutil.copy(square_clip, dst)
    assert probe.probe_clip(tmp_path, dst)['created'] == '2020-01-02T03:04:05Z'


def test_rotated_clip_is_vertical(tmp_path):
    from common import run
    src = tmp_path / 'src.mp4'
    run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=480x270:r=25:d=1',
         '-c:v', 'mpeg4', str(src)])
    dst = tmp_path / 'rot.mp4'
    run(['ffmpeg', '-v', 'error', '-display_rotation', '90', '-i', str(src), '-c', 'copy', str(dst)])
    entry = probe.probe_clip(tmp_path, dst)
    assert (entry['width'], entry['height']) == (270, 480)
    assert probe.choose_frame([entry])['shape'] == 'vertical'
