import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / 'video-summary'
PRE = ROOT / 'hooks' / 'pre_render.py'
POST = ROOT / 'hooks' / 'post_render.py'
RENDER = ROOT / 'scripts' / 'render_summary.py'


def _hook(script, payload, raw=None):
    stdin = raw if raw is not None else json.dumps(payload)
    return subprocess.run([sys.executable, str(script)], input=stdin, capture_output=True, text=True)


def _bash(command, **extra):
    return {'tool_input': {'command': command}, **extra}


def _bad_project(rendered_project, tmp_path, name='bad proj'):
    dest = tmp_path / name
    shutil.copytree(rendered_project['project'], dest)
    (dest / 'clips.json').write_text('[]')
    return dest


def test_pre_hook_blocks_invalid(rendered_project, tmp_path):
    bad = _bad_project(rendered_project, tmp_path)
    result = _hook(PRE, _bash(f'python3 {RENDER} "{bad}"'))
    assert result.returncode == 2
    assert 'clips.json' in result.stderr


def test_pre_hook_uses_cwd_when_no_arg(rendered_project, tmp_path):
    bad = _bad_project(rendered_project, tmp_path)
    assert _hook(PRE, _bash(f'python3 {RENDER}', cwd=str(bad))).returncode == 2


def test_pre_hook_flag_then_dot_resolves_to_cwd(rendered_project, tmp_path):
    bad = _bad_project(rendered_project, tmp_path)
    assert _hook(PRE, _bash(f'python3 {RENDER} --draft .', cwd=str(bad))).returncode == 2


def test_pre_hook_honours_cd(rendered_project, tmp_path):
    bad = _bad_project(rendered_project, tmp_path)
    result = _hook(PRE, _bash(f'cd "{bad.name}" && python3 /x/render_summary.py .', cwd=str(tmp_path)))
    assert result.returncode == 2


def test_pre_hook_stops_at_operator(rendered_project, tmp_path):
    bad = _bad_project(rendered_project, tmp_path)
    result = _hook(PRE, _bash(f'python3 {RENDER} "{bad}" && echo done'))
    assert result.returncode == 2
    good = rendered_project['project']
    assert _hook(PRE, _bash(f'python3 {RENDER} "{good}" ; echo done')).returncode == 0


def test_pre_hook_no_config_is_silent(tmp_path):
    result = _hook(PRE, _bash(f'python3 {RENDER} "{tmp_path}"'))
    assert result.returncode == 0 and result.stderr == ''


@pytest.mark.parametrize('command', [
    'python3 -m pytest tests/test_render_summary.py',
    'cat scripts/render_summary.py',
    'grep x render_summary.py',
    'git diff render_summary.py',
    'python3 -m pytest x && cat render_summary.py',
])
def test_pre_hook_ignores_script_mentions(command, tmp_path):
    result = _hook(PRE, _bash(command, cwd=str(tmp_path)))
    assert result.returncode == 0
    assert result.stdout == '' and result.stderr == ''


def _context(result):
    data = json.loads(result.stdout)
    assert data['hookSpecificOutput']['hookEventName'] == 'PostToolUse'
    return data['hookSpecificOutput']['additionalContext']


def test_post_hook_honours_cd(rendered_project):
    project = rendered_project['project']
    payload = _bash(f'cd "{project.name}" && python3 /x/render_summary.py .', cwd=str(project.parent),
                    tool_response={'output': f'Done!  {rendered_project["out"]}\n'})
    assert 'OK' in _context(_hook(POST, payload))


@pytest.mark.parametrize('script', [PRE, POST])
def test_version_guard_precedes_imports(script):
    lines = script.read_text().splitlines()
    guard = lines.index('if sys.version_info < (3, 11):')
    imports = [i for i, line in enumerate(lines) if line.startswith(('from ', 'import ')) and line != 'import sys']
    assert guard < min(imports)
    assert lines[guard + 1].strip() == 'sys.exit(0)'


def test_pre_hook_passes_valid(rendered_project):
    result = _hook(PRE, _bash(f'python3 {RENDER} {rendered_project["project"]} --draft'))
    assert result.returncode == 0
    assert result.stderr == ''


def test_pre_hook_ignores_other_commands():
    result = _hook(PRE, _bash('ls -la'))
    assert result.returncode == 0
    assert result.stdout == '' and result.stderr == ''


def test_pre_hook_ignores_malformed_stdin():
    assert _hook(PRE, None, raw='not json').returncode == 0


def test_post_hook_reports(rendered_project):
    cmd = f'python3 {RENDER} {rendered_project["project"]}'
    payload = _bash(cmd, tool_response={'output': f'Concatenating...\nDone!  {rendered_project["out"]}\n'})
    result = _hook(POST, payload)
    assert result.returncode == 0
    context = _context(result)
    assert f'Output:   {rendered_project["out"]}' in context
    assert 'Duration:' in context and 'Size:' in context and context.rstrip().endswith('OK')


def test_post_hook_reads_stdout_shape(rendered_project):
    cmd = f'python3 {RENDER} {rendered_project["project"]}'
    payload = _bash(cmd, tool_response={'stdout': f'Done!  {rendered_project["out"]}\n'})
    assert 'Duration:' in _context(_hook(POST, payload))


def test_post_hook_reports_problems(rendered_project, tmp_path):
    dest = tmp_path / 'p'
    shutil.copytree(rendered_project['project'], dest)
    clips = json.loads((dest / 'clips.json').read_text())
    clips[0]['duration'] += 20
    (dest / 'clips.json').write_text(json.dumps(clips))
    payload = _bash(f'python3 {RENDER} "{dest}"', tool_response={'output': f'Done!  {dest / "SUMMARY_VIDEO.mp4"}\n'})
    context = _context(_hook(POST, payload))
    assert 'PROBLEM: duration' in context


def test_post_hook_silent_without_done(rendered_project):
    payload = _bash(f'python3 {RENDER} {rendered_project["project"]}', tool_response={'output': 'error'})
    result = _hook(POST, payload)
    assert result.returncode == 0 and result.stdout == ''


def test_post_hook_malformed_stdin():
    assert _hook(POST, None, raw='{').returncode == 0


def test_hooks_json():
    data = json.loads((ROOT / 'hooks' / 'hooks.json').read_text())
    for event, name in (('PreToolUse', 'pre_render.py'), ('PostToolUse', 'post_render.py')):
        entry = data['hooks'][event][0]
        assert entry['matcher'] == 'Bash'
        assert entry['hooks'][0]['command'] == f'python3 "${{CLAUDE_PLUGIN_ROOT}}/hooks/{name}"'
