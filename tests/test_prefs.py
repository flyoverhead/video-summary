import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

import prefs

SCRIPT = Path(__file__).resolve().parent.parent / 'video-summary' / 'scripts' / 'prefs.py'


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    return tmp_path


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_add_creates_file_and_numbers(home):
    assert prefs.add('no clip under 3 s', 'hk', today=date(2026, 11, 18)) == 1
    assert prefs.add('keep speech whole', 'hk', today=date(2026, 11, 19)) == 2
    path = home / '.config' / 'video-summary' / 'preferences.md'
    assert prefs.prefs_path() == path
    lines = path.read_text().splitlines()
    assert lines[0] == '# video-summary preferences'
    assert '- no clip under 3 s (2026-11-18, hk)' in lines
    assert prefs.load() == ['no clip under 3 s (2026-11-18, hk)', 'keep speech whole (2026-11-19, hk)']


def test_remove_renumbers(home):
    for rule in ('a', 'b', 'c'):
        prefs.add(rule, 'p', today=date(2026, 11, 18))
    assert prefs.remove(2) == 'b (2026-11-18, p)'
    assert prefs.load() == ['a (2026-11-18, p)', 'c (2026-11-18, p)']
    assert prefs.prefs_path().read_text().startswith('# video-summary preferences')
    with pytest.raises(IndexError, match='1-2'):
        prefs.remove(3)
    with pytest.raises(IndexError):
        prefs.remove(0)


def test_rejects_multiline_rule():
    for bad in ('', '   ', 'a\nb'):
        with pytest.raises(ValueError):
            prefs.add(bad, 'p')
    assert not prefs.prefs_path().exists()


def test_show_empty(home):
    r = cli('show')
    assert r.returncode == 0
    assert r.stdout.strip() == f'no preferences ({home}/.config/video-summary/preferences.md)'


def test_cli_add_show_remove_and_errors(home):
    assert cli('add', 'no flashes', '--project', 'hk').returncode == 0
    shown = cli('show').stdout
    assert shown.startswith('1. no flashes (')
    assert cli('remove', '1').returncode == 0
    assert cli('show').stdout.startswith('no preferences')
    r = cli('remove', '5')
    assert r.returncode == 2 and r.stderr.startswith('ERROR:')
    r = cli('add', '', '--project', 'hk')
    assert r.returncode == 2 and r.stderr.startswith('ERROR:')


def test_show_path(home):
    assert cli('show', '--path').stdout.strip() == str(home / '.config' / 'video-summary' / 'preferences.md')


@pytest.mark.parametrize('sep', ['\x0b', '\x0c', '\x85', ' ', ' ', '\r'])
def test_rejects_unicode_line_breaks(sep):
    with pytest.raises(ValueError, match='single line'):
        prefs.add(f'a{sep}- injected', 'p')
    with pytest.raises(ValueError, match='single line'):
        prefs.add('ok', f'p{sep}q')
    assert not prefs.prefs_path().exists()


def test_russian_rule_round_trips(home):
    prefs.add('не обрезать речь на полуслове', 'алтай', today=date(2026, 11, 18))
    path = prefs.prefs_path()
    assert 'не обрезать речь' in path.read_text(encoding='utf-8')
    assert prefs.load() == ['не обрезать речь на полуслове (2026-11-18, алтай)']
    out = cli('show')
    assert out.returncode == 0
    assert '1. не обрезать речь на полуслове (2026-11-18, алтай)' in out.stdout


def test_rule_with_non_breaking_space_is_kept():
    prefs.add('a\xa0b', 'p', today=date(2026, 11, 18))
    assert prefs.load() == ['a\xa0b (2026-11-18, p)']
