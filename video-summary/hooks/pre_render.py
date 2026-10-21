#!/usr/bin/env python3
import sys

if sys.version_info < (3, 11):
    sys.exit(0)

import json  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_command import render_project  # noqa: E402
from verify import validate_project  # noqa: E402


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        command = payload.get('tool_input', {}).get('command', '')
        cwd = payload.get('cwd') or '.'
    except (ValueError, AttributeError):
        return
    project = render_project(command, cwd)
    if project is None or not (project / 'config.json').exists():
        return
    problems = validate_project(project)
    if problems:
        print('Pre-render check failed:\n' + '\n'.join(f'  {p}' for p in problems), file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
