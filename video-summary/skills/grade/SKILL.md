---
name: grade
description: Grades video-summary footage with the bundled DJI Osmo Action 6 D-LogM to Rec.709 LUT — lists clips by camera source, renders before/after previews from the user's own frames, asks all / some / none and records the per-file decision in moments.json and clips.json. Use when deciding or changing which clips get the LUT. Not for rendering the video — use video-summary:render.
argument-hint: "[project-folder]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/*) Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*) Read Glob
---

# Grade (LUT decision)

Project folder: $ARGUMENTS

The LUT is applied only after the user has seen a before/after frame and answered. There is no
automatic D-LogM detection: D-LogM clips report `bt709` tags, and on real trips frame statistics
of D-LogM thumbnails overlap those of the same frames graded to Rec.709 (calibration 2026-10-20,
`skills/render/references/dji-known-issues.md`). Every clip is `unknown` until the user decides
from a preview. Quote every path.

## Checklist

Copy and track:

```
- [ ] 1. lut.py detect
- [ ] 2. Preview: one clip per trip folder and camera source
- [ ] 3. Ask all / some (list) / none
- [ ] 4. lut.py set; check with lut.py show
```

Preconditions: `probe.json` and `moments.json` exist with thumbnails (from
`video-summary:analyze`). Runs after analyze and before plan (spec pipeline order).

## 1. Detect

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lut.py" "<project>" detect
```

One line per `probe.json` clip: `unknown  dji    22.08/DJI_0001_D.MP4`. The status is always
`unknown`. The source is `dji` when the file has the Osmo Action `djmd` metadata track (straight
from the camera), `other` otherwise (phone clip, editor export, earlier render). Source only
groups the previews: an export of D-LogM footage is `other` and can still be flat.

## 2. Previews

Choose clips to preview:

- at least one per trip folder (the first path segment of `file`, or the root);
- within a folder, one per camera source when both `dji` and `other` clips are present.

For the time `T`, use the `t` of that clip's first (highest-ranked) line in the digest
(`moments.py "<project>" digest` prints its path; candidates are listed by rank with the clip key
from its Clips section), or half the clip's duration. Do not Read `moments.json` itself: on a
long trip it exceeds a Read.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lut.py" "<project>" preview "22.08/DJI_0001_D.MP4" 31.5
```

It prints a JPEG path in the cache (BEFORE | AFTER side by side). Read each image to describe
what changed (contrast, saturation, skin, sky), and give the user every path to open
themselves. The source clip is only read.

## 3. Ask

One numbered message:

```
14 clips, colour profile unknown (13 dji, 1 other). Previews:
  22.08: ~/.cache/video-summary/squash/lut-preview-DJI_0001_D-31.5.jpg (dji)
  22.08: ~/.cache/video-summary/squash/lut-preview-squash-08-40.0.jpg (other)
  25.08: ~/.cache/video-summary/squash/lut-preview-DJI_0107_D-12.0.jpg (dji)
Suggest: apply to the 13 dji clips, skip the 1 other (raw Osmo files are usually shot in
D-LogM; check the previews, a dji clip can also be in the Normal profile).
1. Apply the LUT to: all / some (list files or folders) / none?
```

Always add the `Suggest:` line, built from detect's source split: the `dji` clips on, the
`other` clips off, unless a preview clearly contradicts it (then say which and why). The
suggestion is not a decision: record nothing until the user answers. A skipped, unclear or
off-topic reply is not consent; ask again. Offer more previews of any clip the user names.

## 4. Record

- all → `--all true`
- none → `--all false`
- some → `--all false` plus the chosen files set to true (expand a folder to its files from
  `probe.json`)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lut.py" "<project>" set --all false "22.08/DJI_0001_D.MP4=true" "22.08/DJI_0002_D.MP4=true"
```

Output: `moments.json lut: 2 on, 12 off`, then each `clips.json` flag it changed, or
`clips.json: no flag changes` (also printed when `clips.json` does not exist yet; the
clip-editor takes the flags from the digest's Clips section when it drafts). Report the result,
then continue with `video-summary:plan` (or return to `video-summary:start`). Grade normally
runs before plan; run again later, it also updates the flags in an existing `clips.json`, and
plan should then rewrite `SUMMARY.md`.

## Validate → fix → re-run

1. `lut.py set` exits 0.
2. Check the recorded state (never Read `moments.json`):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lut.py" "<project>" show
   ```

   One `on`/`off` line per `probe.json` clip (absent counts as `off`) must match the user's
   answer. The last line is `clips.json: N clips match` or `clips.json: not written yet`; a
   `clip <i> <file>: clips.json lut ..., moments.json ...` line and exit 1 mean a mismatch: re-run
   `set` with the user's answer.

`ERROR: not in probe.json: <file>` means a typo or a path not relative to the project root: fix
the name from `probe.json` and re-run `set`. A preview error names the clip and time; pick a time
inside the clip and re-run `preview`.
