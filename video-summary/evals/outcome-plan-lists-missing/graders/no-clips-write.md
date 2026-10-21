---
type: tool_used
tool: Bash
input_match: 'project\.py(?:[^"\\]|\\.)*\bwrite\b(?:[^"\\]|\\.)*clips\.json|\bsed\s(?:[^|;&]*\s)?-i\b[^|;&]*clips\.json|>>?\s*\S*clips\.json|\btee\s[^|;&]*clips\.json|\bsponge\s[^|;&]*clips\.json|\b(?:cp|mv)\s[^|;&]*clips\.json(?:\\"|")*\s*(?:\}|[;&|]|\d?>|$)|\bpython3?\s+-c\b(?=.*clips\.json)(?=.*(?:\bwrite\b|\bdump\b))'
min: 0
max: 0
arm: both
---
