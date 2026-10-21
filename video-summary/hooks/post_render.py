#!/usr/bin/env python3
import sys

if sys.version_info < (3, 11):
    sys.exit(0)

import json  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_command import render_project  # noqa: E402
from verify import report  # noqa: E402

MARKER = 'Done!  '


def response_text(response) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return '\n'.join(v for k in ('stdout', 'output') if isinstance(v := response.get(k), str))
    return ''


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        command = payload.get('tool_input', {}).get('command', '')
        text = response_text(payload.get('tool_response'))
        cwd = payload.get('cwd') or '.'
    except (ValueError, AttributeError):
        return
    if MARKER not in text:
        return
    out = next((line[line.index(MARKER) + len(MARKER):].strip()
                for line in text.splitlines() if MARKER in line), '')
    project = render_project(command, cwd)
    if not out or project is None or not (project / 'config.json').exists():
        return
    lines, _ = report(project, draft=out.endswith('.draft.mp4'))
    context = 'Post-render check (verify.py):\n' + '\n'.join(lines)
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': context}}))


if __name__ == '__main__':
    main()
