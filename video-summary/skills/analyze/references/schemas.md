# Project file schemas

All files live in the project root (the footage folder the user named) except
`render-manifest.json` and the thumbnails, which live under `~/.cache/video-summary/<slug>/`.
Paths in `file` fields are relative to the project root.

## Contents

- [Who writes what](#who-writes-what)
- [brief.json](#briefjson)
- [probe.json](#probejson)
- [moments.json](#momentsjson)
- [clips.json](#clipsjson)
- [config.json](#configjson)
- [render-manifest.json](#render-manifestjson)

## Who writes what

| File | Written by | Overwrite |
|---|---|---|
| `brief.json` | `project.py write` (start, plan) | diff shown, `--overwrite` after a yes |
| `probe.json` | `probe.py` | `--overwrite` after a yes |
| `moments.json` | `sample.py`, then `moments.py merge/group/pick`, `lut.py set` | `sample.py --overwrite` discards all scores; the others update in place |
| `clips.json` | `project.py write` (plan); `lut.py set` updates `lut` flags | diff shown, `--overwrite` after a yes |
| `config.json` | `project.py write` (plan) | diff shown, `--overwrite` after a yes |
| `SUMMARY.md` | `project.py write` (plan) | diff shown, `--overwrite` after a yes |
| `SUMMARY_VIDEO.mp4` | `render_summary.py` | `--overwrite` after a yes |
| `SUMMARY_VIDEO.draft.mp4` | `render_summary.py --draft` | always replaced (disposable) |

Nothing else is ever written into the project folder, and source clips are never modified.

## brief.json

```json
{"type": "trip", "source": "/abs/folder", "description": "...", "timeline": "...",
 "tone": "calm and nostalgic", "must_find": [{"id": "m1", "text": "kids on the cable car"}],
 "keep_memories": ["grandma's laugh"], "target_min": [10, 15], "quality": 60,
 "music": null, "force_include": [], "force_exclude": []}
```

- `type`: `trip` | `sport` | `everyday` | `other`.
- `must_find` ids are `m1`, `m2`, … in the order the user listed them; never renumber.
- `music`: `null` or `{"file": "/abs/song.mp3", "mode": "duck" | "replace"}`.
- `force_include` / `force_exclude`: file names or short descriptions. A `force_exclude` entry
  that equals a clip's path, base name or one of its folders keeps that clip out of `sample.py`.

## probe.json

```json
{"clips": [{"file": "22.08/DJI_0001_D.MP4", "duration": 61.2, "fps": 50.0, "width": 3840,
            "height": 3840, "audio_channels": 2, "created": "2026-08-22T10:00:00"}],
 "frame": {"shape": "square", "width": 2560, "height": 2560, "fps": 50.0}}
```

## moments.json

```json
{"candidates": [{"id": "c0001", "file": "22.08/DJI_0001_D.MP4", "t": 12.5,
                 "source": "scene", "thumb": "/abs/cache/thumbs/c0001.jpg"}],
 "scores": {"c0001": {"people": 2, "emotion": 4, "view": 1, "detail": 0, "brief_match": 3,
                      "quality": "good", "kind": "highlight", "process": null,
                      "desc": "Kids laugh at the cake", "in": 10.0, "out": 18.0,
                      "must_find": ["m1"]}},
 "groups": [{"id": "g1", "process": "metro ride", "members": ["c0004", "c0007"],
             "pick": "c0007", "clip_s": 6.0},
            {"id": "g2", "process": "walking", "members": ["c0009"], "pick": "c0009",
             "clip_s": 4.0, "dropped": true}],
 "group_overrides": {"metro ride|c0004": {"pick": "c0007"}, "walking|c0009": {"dropped": true}},
 "must_find": [{"id": "m1", "text": "kids on the cable car", "status": "found",
                "where": ["c0001", "c0009"], "required": ["c0001"], "extras": ["c0009"],
                "best": {"id": "c0001", "file": "22.08/DJI_0001_D.MP4", "t": 12.5,
                         "thumb": "/abs/cache/thumbs/c0001.jpg"}}],
 "lut": {"22.08/DJI_0001_D.MP4": true}}
```

- `source`: `scene` | `loud` | `baseline`.
- Score integers are 0–5; `quality` `good` | `fair` | `poor`; `kind` `highlight` | `routine`;
  `process` a string for routine, `null` for highlight; `0 <= in < out`; `must_find` ids must
  exist in `brief.json`. `moments.py merge` rejects the whole batch on any violation and names
  each bad id and field.
- Rank = `2*brief_match + people + emotion + view + detail`, minus 3 for `poor`.
- `must_find[].best` is the highest-ranked match (shown as `file @ t` + thumb in the shortlist);
  `required` is that match plus the best match in each other clip, which the clip-editor always
  keeps; `extras` are the other matches, which compete by rank.
- `groups` and `must_find` are rebuilt by `moments.py group`. Group `id`s are `g1`, `g2`, … in
  time order and never shift within one grouping; a dropped group stays in the list with
  `"dropped": true` and is left out of the cut.
- `group_overrides` holds the user's `moments.py pick` choices, keyed `<process>|<first member>`,
  and is re-applied by every `group`; an override that matches no group is kept and reported on
  stderr.
- `moments.py pending` writes `<cache>/scores/input-<first id>.json` per batch
  (`{"candidates": [{"id", "file", "t", "thumb", "duration"}], "process_labels": [str]}`), the
  frame-analyst's only input besides `brief.json`; its scores go to
  `<cache>/scores/batch-<first id>.json` and are merged from there. `pending` deletes a stale
  scores file before printing its path; `sample.py --overwrite` clears `<cache>/scores/`.
- The cache folder is `~/.cache/video-summary/<path under ~/Movies/camera with / as ->`, or
  `<folder name>-<8-hex hash of the resolved path>` for a project elsewhere.
- `moments.py digest` writes `<cache>/digest.txt`, one line per clip, must-find, group and scored
  candidate (by rank); the clip-editor and the skills read it instead of `moments.json`, which
  grows to megabytes on a long trip.
- `lut` is the per-file grade decision; absent means `false`. It is only ever the user's answer
  after a preview (`lut.py set`); there is no automatic D-LogM detection to fill it, because
  frame statistics did not separate D-LogM from Rec.709 on real footage. `lut.py show` prints it
  per clip and checks `clips.json` against it.

## clips.json

```json
[{"file": "22.08/DJI_0001_D.MP4", "start": 10.0, "duration": 8.0, "label": "Old Town Square",
  "lut": true}]
```

No `time` field and no timestamps in labels; labels show place or moment only.

## config.json

```json
{"src": "/abs/folder", "out": "/abs/folder/SUMMARY_VIDEO.mp4",
 "tmp": "/abs/home/.cache/video-summary/<slug>/render",
 "frame": {"shape": "square", "width": 2560, "height": 2560, "fps": 50.0},
 "quality": 60, "audio_br": "192k", "lut": null,
 "music": null}
```

- `src` is the project folder; `out` is exactly `<src>/SUMMARY_VIDEO.mp4` (drafts go to
  `SUMMARY_VIDEO.draft.mp4` beside it); `tmp` must be outside it. `render_summary.py` and the
  pre-render hook refuse any other `out`, an `out` that is a clip in `probe.json`, and any clip
  whose `start + duration` passes its `probe.json` duration by more than 0.1 s. Use the cache
  folder that holds the thumbnails (`dirname(dirname(thumb))`) plus `/render`.
- `frame` is copied from `probe.json`.
- `quality`: 40 draft, 60 standard, 75 high (`hevc_videotoolbox -q:v`, 1-100, higher is better). `--draft` renders use `render.draft_quality` (35) from `scripts/defaults.json`.
- `lut: null` falls back to the bundled
  `assets/luts/dji-osmo-action6-dlogm-to-rec709.cube`; set a path only for a different LUT.
- `music`: `null` or `{"file": "/abs/song.mp3", "mode": "duck" | "replace", "duck_db": -18}`; `file` may start with `~`
  and must exist, or validation refuses the render.

## render-manifest.json

Written by `render_summary.py` into `config.tmp`, read by `verify.py`:

```json
{"clips": [{"index": 0, "file": "22.08/DJI_0001_D.MP4", "lut": true, "duration": 8.0}],
 "draft": false, "out": "/abs/folder/SUMMARY_VIDEO.mp4"}
```
