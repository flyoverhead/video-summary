# video-summary

Claude Code plugin (marketplace root; plugin lives in `video-summary/`). Python stdlib helpers + ffmpeg.

## Commands

- Test: `python3 -m pytest -v`
- Evals: `scripts/eval.sh` (all cases, then the gate script named by `EVAL_GATE` if set; extra args such as `--case 'outcome-*'` pass through; `EVAL_MODEL` overrides sonnet)

## Constraints

- Stdlib only in plugin scripts; pytest for tests.
- Every ffmpeg/ffprobe call goes through `common.run` / `common.ffmpeg_env()` (PATH prefixed with `/opt/homebrew/opt/ffmpeg-full/bin`), including test fixtures.
- Write project outputs only via `common.write_output` (skills: `scripts/project.py write`, `moments.py merge|pick`, `lut.py set`) (whitelisted names, no overwrite without `overwrite=True`); never modify source footage under `~/Movies`.
- Caches go to `~/.cache/video-summary/<slug>` via `common.cache_dir`, never into the project folder.
- Code without comments except a non-obvious why.
- Commits: conventional, `git commit -s`, no AI attribution; work on `feat/*` branches, never commit to `main`.
