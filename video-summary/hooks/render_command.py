import re
import shlex
from pathlib import Path

PYTHON = re.compile(r'python(3(\.\d+)?)?')
OPERATORS = set('();<>|&')


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _is_operator(token: str) -> bool:
    return bool(token) and set(token) <= OPERATORS


def render_project(command: str, cwd: str) -> Path | None:
    try:
        tokens = _tokens(command)
    except ValueError:
        return None
    base = Path(cwd or '.')
    segment: list[str] = []
    for token in tokens + [';']:
        if not _is_operator(token):
            segment.append(token)
            continue
        found = _project_in(segment, base)
        if found is not None:
            return found
        if len(segment) == 2 and segment[0] == 'cd':
            base = base / Path(segment[1]).expanduser()
        segment = []
    return None


def _project_in(segment: list[str], base: Path) -> Path | None:
    for i, token in enumerate(segment):
        if i and Path(token).name == 'render_summary.py' and PYTHON.fullmatch(Path(segment[i - 1]).name):
            arg = next((t for t in segment[i + 1:] if not t.startswith('-')), None)
            return base / Path(arg).expanduser() if arg else base
    return None
