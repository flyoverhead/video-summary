# Shapes per video type

Read by `video-summary:clip-editor` and by `video-summary:plan` when presenting the cut. The
type sets the structure; the emotional tone from `brief.json` `tone` tunes pacing inside it.

## Type shapes

| Type | Order | Pacing | Labels | Cut first |
|---|---|---|---|---|
| trip (default) | chronological journey | views get room; routine folded into short process clips | place | repetitive transit/walking |
| sport | by session → rallies/points | tight; peak action only | action / score | warm-up, pauses, retrieval |
| everyday | chronological | gentle; people-centric | moment | empty scenes |
| other | from brief | from emotional tone | context 2–4 words | weakest story fit |

- Sport sessions come from date subfolders when present (`squash/22.08/`), otherwise from
  creation-time gaps over 30 minutes.
- Routine groups are one clip each (`moments.json` `groups`, length `clip_s`), whatever the
  type; a group marked `"dropped": true` gets none. Their range comes from `scripts/defaults.json` `types.<type>.routine_clip_s`.
- Target length defaults: trip 10–15 min, sport 3–6, everyday 3–8, other 5–10
  (`types.<type>.target_min`).

## Tone modifiers

Match the user's own words to the closest row; mixed tones take the first one named.

| Tone (user's words) | Highlight length | Views | Arc | Routine |
|---|---|---|---|---|
| calm, nostalgic, warm, slow | 8–12 s | 10–15 s, let them breathe | even; end on a quiet view or a person | keep at the top of `routine_clip_s` |
| joyful, fun, family, friends | 6–9 s | 6–8 s | even with a lift near the end | middle of the range |
| energetic, dynamic, adventurous | 3–6 s | 4–6 s | builds to a peak in the last third | bottom of the range |
| epic, dramatic, awe | 6–10 s, longest at the peak | 10–15 s at the climax | builds to one peak, short coda | bottom of the range |
| documentary, factual, record | as found, 6–10 s | 6–8 s | strictly chronological, even | top of the range; keep context |

- No tone given: use the joyful row for trip and everyday, energetic for sport.
- Tone never removes a `must_find` match or a `force_include` clip; it only changes their length.
- Reactions (laughter, surprise) keep 1–2 s after the peak in every tone.

## Editing vocabulary

Terms the skills and agents use for the cut.

| Term | Meaning here |
|---|---|
| A-cut | The main storyline: highlight clips in story order, the material the viewer follows. |
| B-roll | Cutaway footage over the story: the single pick of each routine group (walking, transit, views). |
| Cut on pause | Clip edges snapped outward to the nearest silence (`moments.py snap`) so no clip starts or ends mid-utterance; edges the user set by hand are never moved. |
| Contact sheet | Pages of frames from every clip of the drafted cut, shown beside the clip table before the user confirms. |
| Pilot render | A draft of a clip range only (`--clips`), to check pacing and joins before the full render. |
| J/L cut | Audio leading or trailing the picture across a join. Not used: joins keep picture and sound together and get 50 ms audio fades to remove clicks. |
