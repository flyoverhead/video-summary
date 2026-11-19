#!/usr/bin/env python3
import argparse
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

HEADER = '# video-summary preferences'


def prefs_path() -> Path:
    return Path.home() / '.config' / 'video-summary' / 'preferences.md'


def _lines() -> list[str]:
    path = prefs_path()
    return path.read_text(encoding='utf-8').splitlines() if path.exists() else []


def _is_rule(line: str) -> bool:
    return line.startswith('- ')


def load() -> list[str]:
    return [line[2:] for line in _lines() if _is_rule(line)]


def _save(lines: list[str]) -> None:
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.preferences-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def add(rule: str, project: str, today: date | None = None) -> int:
    rule = rule.strip()
    if not rule:
        raise ValueError('rule is empty')
    if len(rule.splitlines()) != 1:
        raise ValueError('rule must be a single line')
    if len(project.splitlines()) != 1:
        raise ValueError('project name must be a single line')
    stamp = (today or date.today()).isoformat()
    lines = _lines() or [HEADER, '']
    lines.append(f'- {rule} ({stamp}, {project})')
    _save(lines)
    return sum(1 for line in lines if _is_rule(line))


def remove(n: int) -> str:
    lines = _lines()
    rules = [i for i, line in enumerate(lines) if _is_rule(line)]
    if not 1 <= n <= len(rules):
        valid = f'valid 1-{len(rules)}' if rules else 'no preferences to remove'
        raise IndexError(f'no rule {n} ({valid})')
    removed = lines.pop(rules[n - 1])
    _save(lines)
    return removed[2:]


def main() -> None:
    parser = argparse.ArgumentParser(description='Persistent editing preferences')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sh = sub.add_parser('show', help='print numbered rules')
    sh.add_argument('--path', action='store_true', help='print the file path only')
    ad = sub.add_parser('add', help='append a rule')
    ad.add_argument('rule')
    ad.add_argument('--project', required=True)
    rm = sub.add_parser('remove', help='remove rule N')
    rm.add_argument('n', type=int)
    args = parser.parse_args()
    try:
        if args.cmd == 'show' and args.path:
            print(prefs_path())
            return
        if args.cmd == 'show':
            rules = load()
            if not rules:
                print(f'no preferences ({prefs_path()})')
            for i, rule in enumerate(rules, 1):
                print(f'{i}. {rule}')
            return
        if args.cmd == 'add':
            print(f'added {add(args.rule, args.project)}: {args.rule.strip()}')
            return
        print(f'removed: {remove(args.n)}')
    except (OSError, ValueError, IndexError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
