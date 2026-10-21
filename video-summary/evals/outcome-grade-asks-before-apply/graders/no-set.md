---
type: tool_used
tool: Bash
input_match: 'lut\.py(?:[^"\\]|\\.)*\bset\b|\bsed\s(?:[^|;&]*\s)?-i\b[^|;&]*moments\.json|>>?\s*\S*moments\.json|\btee\s[^|;&]*moments\.json|\bsponge\s[^|;&]*moments\.json|\b(?:cp|mv)\s[^|;&]*moments\.json(?:\\"|")*\s*(?:\}|[;&|]|\d?>|$)|\bpython3?\s+-c\b(?=.*moments\.json)(?=.*(?:\bwrite\b|\bdump\b))'
min: 0
max: 0
arm: both
---
