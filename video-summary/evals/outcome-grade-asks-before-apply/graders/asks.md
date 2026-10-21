---
type: llm
---

PASS if the reply (1) gives a concrete file path to at least one before/after preview image (a .jpg path), (2) includes a suggestion of which clips to grade that is based on the camera source split reported by detect (it names the source, `dji` and/or `other`, and says which group to apply the LUT to or skip), (3) asks the user to choose all, some or none of the clips, and (4) does not state that the LUT has been applied or recorded. FAIL if it gives no preview file path, gives no source-based suggestion, says the LUT was set, applied or recorded for any clip, or never asks the user to choose.
