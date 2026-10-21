import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import filters
import render_summary
from common import LUT_PATH, read_json, run

SCRIPT = Path(render_summary.__file__)
FONT = Path(render_summary.find_font())
SQUARE = {'shape': 'square', 'width': 320, 'height': 320, 'fps': 25.0}


def _streams(path):
    out = run(['ffprobe', '-v', 'error', '-show_entries',
               'stream=codec_type,width,height,channels,duration,pix_fmt:format=duration',
               '-of', 'json', str(path)]).stdout
    return json.loads(out)


def _stream(info, kind):
    return next(s for s in info['streams'] if s['codec_type'] == kind)


def _rms(path, start=0.0, length=1.0):
    proc = run(['ffmpeg', '-hide_banner', '-nostats', '-ss', str(start), '-t', str(length), '-i', str(path),
                '-vn', '-af', 'pan=mono|c0=c0,astats=measure_overall=RMS_level:measure_perchannel=none',
                '-f', 'null', '-'])
    return float(re.findall(r'RMS level dB: (-?[0-9.]+|-inf)', proc.stderr)[-1])


def _src(w, h, fps=25.0, ch=1):
    return {'file': 'x.mp4', 'duration': 3.0, 'fps': fps, 'width': w, 'height': h, 'audio_channels': ch}


def _clip(lut=False, label='Here'):
    return {'file': 'x.mp4', 'start': 0.0, 'duration': 1.0, 'label': label, 'lut': lut}


def test_drawtext_escaping():
    assert filters.escape_drawtext("Bob's café: 100%\\") == "Bob\\'s café\\: 100\\%\\\\"


def test_drawtext_renders_literally(square_clip, tmp_path):
    label = "Bob's café: 100%\\ [a,b];"
    textfile = tmp_path / 'label.txt'
    textfile.write_text(label)
    ours = filters.drawtext(label, SQUARE, FONT)
    ref = re.sub(r':text=.*?:x=', f':expansion=none:textfile={filters.escape_filter_path(textfile)}:x=',
                 ours)
    assert ref != ours

    def frame_md5(vf):
        return run(['ffmpeg', '-v', 'error', '-i', str(square_clip), '-frames:v', '1', '-vf', vf,
                    '-f', 'md5', '-']).stdout

    assert frame_md5(ours) == frame_md5(ref)


def test_video_filter_lut_first():
    vf = filters.video_filter(_clip(lut=True), _src(320, 320), SQUARE, LUT_PATH, FONT)
    assert vf.startswith('lut3d=')
    no_lut = filters.video_filter(_clip(lut=False), _src(320, 320), SQUARE, LUT_PATH, FONT)
    assert 'lut3d' not in no_lut and no_lut.startswith('fps=')


def test_video_filter_fit_when_aspect_differs():
    vertical = filters.video_filter(_clip(), _src(270, 480), SQUARE, None, FONT)
    assert 'boxblur' in vertical and 'overlay' in vertical
    square = filters.video_filter(_clip(), _src(320, 320), SQUARE, None, FONT)
    assert 'boxblur' not in square and 'overlay' not in square
    assert square.endswith('format=yuv420p10le')


def test_audio_filter_mono_left():
    assert filters.audio_filter(_src(320, 320, ch=2)).startswith('pan=mono|c0=c0')
    assert filters.audio_filter(_src(320, 320, ch=0)) is None


def test_render_mixed_shapes_square_out(render_project, tmp_path, square_clip, vertical_clip, wide_clip):
    sources = [(square_clip, 'square.MP4', 'A', False), (vertical_clip, 'vertical.MP4', 'B', False),
               (wide_clip, 'wide.MP4', 'C', False)]
    config, clips, probe_data = render_project(tmp_path / 'p', sources, tmp_path / 'tmp')
    out = render_summary.render(config, clips, probe_data)
    info = _streams(out)
    video = _stream(info, 'video')
    assert (video['width'], video['height']) == (320, 320)
    assert video['pix_fmt'] == 'yuv420p10le'
    assert abs(float(info['format']['duration']) - sum(c['duration'] for c in clips)) <= 0.3
    assert _stream(info, 'audio')['channels'] == 2


def test_render_silent_clip_keeps_audio(render_project, tmp_path, square_clip, silent_clip):
    sources = [(square_clip, 'square.MP4', 'A', False), (silent_clip, 'silent.MP4', 'B', False),
               (square_clip, 'square2.MP4', 'C', False)]
    config, clips, probe_data = render_project(tmp_path / 'p', sources, tmp_path / 'tmp')
    out = render_summary.render(config, clips, probe_data)
    info = _streams(out)
    assert abs(float(_stream(info, 'audio')['duration']) - float(_stream(info, 'video')['duration'])) <= 0.3
    assert _rms(out, 3.3, 0.8) > -40


def test_render_handles_spaces_and_quotes(render_project, tmp_path, square_clip):
    sources = [(square_clip, 'a b.mp4', "It's: 100%", True)]
    config, clips, probe_data = render_project(tmp_path / "trip 'x' dir", sources, tmp_path / "tmp 'q' x")
    out = render_summary.render(config, clips, probe_data)
    assert out == Path(config['out']) and out.stat().st_size > 0


def test_render_refuses_existing_out(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)],
                                               tmp_path / 'tmp')
    Path(config['out']).write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        render_summary.render(config, clips, probe_data)
    assert Path(config['out']).read_bytes() == b'keep'


def test_render_draft_path(render_project, tmp_path, square_clip, vertical_clip):
    sources = [(square_clip, 'square.MP4', 'A', False), (vertical_clip, 'vertical.MP4', 'B', True)]
    config, clips, probe_data = render_project(tmp_path / 'p', sources, tmp_path / 'tmp', draft_long_side=160)
    out = Path(config['out'])
    out.write_bytes(b'final')
    draft = render_summary.render(config, clips, probe_data, draft=True)
    assert draft == out.parent / 'SUMMARY_VIDEO.draft.mp4'
    assert out.read_bytes() == b'final'
    video = _stream(_streams(draft), 'video')
    assert (video['width'], video['height']) == (160, 160)
    assert read_json(Path(config['tmp']) / 'render-manifest.json')['draft'] is True


def test_render_manifest_records_lut(rendered_project):
    manifest = read_json(rendered_project['manifest'])
    clips = rendered_project['clips']
    assert [c['lut'] for c in manifest['clips']] == [c['lut'] for c in clips]
    assert [c['file'] for c in manifest['clips']] == [c['file'] for c in clips]
    assert [c['index'] for c in manifest['clips']] == list(range(len(clips)))
    assert manifest['draft'] is False
    assert manifest['out'] == str(rendered_project['out'])


def test_cli_prints_progress_and_done(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p q', [(square_clip, 'a.mp4', 'Pier', False)],
                                               tmp_path / 'tmp')
    root = Path(config['src'])
    for name, data in (('config.json', config), ('clips.json', clips), ('probe.json', probe_data)):
        (root / name).write_text(json.dumps(data))
    proc = subprocess.run([sys.executable, str(SCRIPT), str(root), '--draft'], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert '[1/1] a.mp4 [0.5→2.0] "Pier"' in proc.stdout
    assert f'Done!  {root / "SUMMARY_VIDEO.draft.mp4"}' in proc.stdout.splitlines()


def test_music_replace_and_duck(render_project, tmp_path, square_clip):
    music = tmp_path / 'music.m4a'
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
         "aevalsrc='0.8*sin(2*PI*1000*t)':s=48000:d=1.2,aformat=channel_layouts=stereo", '-c:a', 'aac', str(music)])
    sources = [(square_clip, 'a.mp4', 'A', False), (square_clip, 'b.mp4', 'B', False)]
    cam_cfg, clips, probe_data = render_project(tmp_path / 'cam', sources, tmp_path / 'tcam')
    camera_rms = _rms(render_summary.render(cam_cfg, clips, probe_data))
    music_rms = _rms(music)
    for mode in ('replace', 'duck'):
        config, clips, probe_data = render_project(
            tmp_path / mode, sources, tmp_path / f't{mode}',
            music={'file': str(music), 'mode': mode, 'duck_db': -18})
        out = render_summary.render(config, clips, probe_data)
        info = _streams(out)
        assert _stream(info, 'audio')['channels'] == 2
        assert abs(float(info['format']['duration']) - 3.0) <= 0.3
        if mode == 'replace':
            out_rms = _rms(out)
            assert abs(out_rms - music_rms) < 2 < abs(out_rms - camera_rms)


def test_music_args_shapes():
    replace = filters.music_args({'file': '/m.mp3', 'mode': 'replace'}, 10.0)
    assert replace[:4] == ['-stream_loop', '-1', '-i', '/m.mp3']
    assert '0:v' in replace and '1:a' in replace
    assert any('afade=t=out:st=8.000:d=2' in a for a in replace)
    duck = filters.music_args({'file': '/m.mp3', 'mode': 'duck', 'duck_db': -18}, 10.0)
    graph = duck[duck.index('-filter_complex') + 1]
    assert 'volume=-18dB' in graph and 'sidechaincompress' in graph and 'amix' in graph


def test_quality_presets_ordered():
    from common import defaults
    render_cfg = defaults()['render']
    assert render_cfg['quality'] == {'draft': 40, 'standard': 60, 'high': 75}
    assert render_cfg['draft_quality'] == 35


def test_higher_quality_value_gives_bigger_file(render_project, tmp_path, square_clip):
    sizes = {}
    for q in (35, 75):
        config, clips, probe_data = render_project(tmp_path / f'q{q}', [(square_clip, 'a.mp4', 'A', False)],
                                                   tmp_path / f'tq{q}', quality=q)
        sizes[q] = render_summary.render(config, clips, probe_data).stat().st_size
    assert sizes[75] > sizes[35]


def _assert_refused(config, clips, probe_data, needle):
    with pytest.raises(ValueError) as exc:
        render_summary.render(config, clips, probe_data)
    assert needle in str(exc.value)


def test_render_refuses_out_on_a_source_clip(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)], tmp_path / 'tmp')
    source = Path(config['src']) / 'a.mp4'
    before = source.read_bytes()
    config['out'] = str(source)
    _assert_refused(config, clips, probe_data, 'SUMMARY_VIDEO.mp4')
    assert source.read_bytes() == before


def test_render_refuses_out_outside_root(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)], tmp_path / 'tmp')
    config['out'] = str(tmp_path / 'SUMMARY_VIDEO.mp4')
    _assert_refused(config, clips, probe_data, 'project root')
    assert not (tmp_path / 'SUMMARY_VIDEO.mp4').exists()


def test_render_refuses_out_listed_in_probe(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)], tmp_path / 'tmp')
    probe_data['clips'].append({**probe_data['clips'][0], 'file': 'SUMMARY_VIDEO.mp4'})
    _assert_refused(config, clips, probe_data, 'source clip')


def test_render_refuses_trim_past_source_end(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)], tmp_path / 'tmp')
    clips[0]['start'] = 2.0
    _assert_refused(config, clips, probe_data, 'exceeds source')


def test_render_refuses_tmp_in_source(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)], tmp_path / 'tmp')
    config['tmp'] = str(Path(config['src']) / 'work')
    _assert_refused(config, clips, probe_data, 'tmp')
    assert not (Path(config['src']) / 'work').exists()


def test_render_refuses_malformed_clip(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)], tmp_path / 'tmp')
    del clips[0]['label']
    _assert_refused(config, clips, probe_data, 'label')


def test_cli_refuses_src_not_project(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'other', [(square_clip, 'a.mp4', 'A', False)],
                                               tmp_path / 'tmp')
    here = tmp_path / 'here'
    here.mkdir()
    for name, data in (('config.json', config), ('clips.json', clips), ('probe.json', probe_data)):
        (here / name).write_text(json.dumps(data))
    proc = subprocess.run([sys.executable, str(SCRIPT), str(here), '--draft'], capture_output=True, text=True)
    assert proc.returncode == 1
    assert 'config.src' in proc.stderr and str(here) in proc.stderr
    assert not (tmp_path / 'other' / 'SUMMARY_VIDEO.draft.mp4').exists()
    assert not (tmp_path / 'tmp').exists()


def test_render_expands_home_in_config_paths(render_project, tmp_path, square_clip, monkeypatch):
    home = tmp_path / 'home'
    config, clips, probe_data = render_project(home / 'trip', [(square_clip, 'a.mp4', 'A', False)],
                                               home / 'cache' / 'render')
    monkeypatch.setenv('HOME', str(home))
    work = tmp_path / 'cwd'
    work.mkdir()
    monkeypatch.chdir(work)
    config.update(src='~/trip', out='~/trip/SUMMARY_VIDEO.mp4', tmp='~/cache/render')
    out = render_summary.render(config, clips, probe_data, draft=True)
    assert out == home / 'trip' / 'SUMMARY_VIDEO.draft.mp4'
    assert out.exists()
    assert (home / 'cache' / 'render' / 'render-manifest.json').exists()
    assert list(work.iterdir()) == []


def test_render_expands_home_in_music_file(render_project, tmp_path, square_clip, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=48000:d=1',
         '-c:a', 'aac', str(home / 'song.m4a')])
    monkeypatch.setenv('HOME', str(home))
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)], tmp_path / 'tmp',
                                               music={'file': '~/song.m4a', 'mode': 'replace'})
    out = render_summary.render(config, clips, probe_data, draft=True)
    assert _stream(_streams(out), 'audio')['channels'] == 2


def test_render_refuses_missing_music_file(render_project, tmp_path, square_clip):
    config, clips, probe_data = render_project(tmp_path / 'p', [(square_clip, 'a.mp4', 'A', False)], tmp_path / 'tmp',
                                               music={'file': str(tmp_path / 'nope.mp3'), 'mode': 'duck'})
    _assert_refused(config, clips, probe_data, 'music file not found')
    assert not (tmp_path / 'tmp').exists()
