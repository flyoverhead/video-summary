#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
cat > brief.json <<'JSON'
{"type": "trip", "source": "PROJ", "description": "Three days in Lisbon", "timeline": "Day 1 old town, day 2 Belem, day 3 beach",
 "tone": "calm and nostalgic", "must_find": [{"id": "m1", "text": "tram 28 climbing the hill"}, {"id": "m2", "text": "cat on the castle wall"}],
 "keep_memories": ["grandma's laugh"], "target_min": [10, 15], "quality": 60, "music": null, "force_include": [], "force_exclude": []}
JSON
sed -i.bak "s#PROJ#$PWD#" brief.json && rm brief.json.bak
mkdir -p 22.08
ffmpeg -hide_banner -v error -y -f lavfi -i "testsrc2=size=320x240:rate=25:duration=3" -f lavfi -i "sine=frequency=440:duration=3" -ac 2 -c:v libx264 -pix_fmt yuv420p -c:a aac 22.08/DJI_0001_D.MP4
mkdir -p thumbs
ffmpeg -hide_banner -v error -y -f lavfi -i "color=c=0x808080:size=320x240,format=gray,format=yuv420p" -frames:v 1 thumbs/c0001.jpg
cat > probe.json <<'JSON'
{"clips": [{"file": "22.08/DJI_0001_D.MP4", "duration": 3.0, "fps": 25.0, "width": 320, "height": 240, "audio_channels": 2, "created": "2026-08-22T10:00:00"}],
 "frame": {"shape": "wide", "width": 320, "height": 240, "fps": 25.0}}
JSON
cat > moments.json <<'JSON'
{"candidates": [{"id": "c0001", "file": "22.08/DJI_0001_D.MP4", "t": 1.0, "source": "scene", "thumb": "THUMB"}],
 "scores": {"c0001": {"people": 2, "emotion": 4, "view": 3, "detail": 1, "brief_match": 4, "quality": "good", "kind": "highlight", "process": null,
   "desc": "Tram 28 climbs the hill", "in": 0.0, "out": 3.0, "must_find": ["m1"]}},
 "groups": [],
 "must_find": [{"id": "m1", "text": "tram 28 climbing the hill", "status": "found", "where": ["c0001"]},
               {"id": "m2", "text": "cat on the castle wall", "status": "not_found", "where": []}],
 "lut": {}}
JSON
sed -i.bak "s#THUMB#$PWD/thumbs/c0001.jpg#" moments.json && rm moments.json.bak
