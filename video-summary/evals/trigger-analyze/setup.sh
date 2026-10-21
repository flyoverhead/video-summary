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
