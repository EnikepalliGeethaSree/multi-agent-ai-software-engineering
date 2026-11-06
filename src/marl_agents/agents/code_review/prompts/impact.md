version: 1.0
---
## Change impact check

A code change modified `{qualname}` in `{file}`. Its callers below were NOT updated by the change.
Decide, for each caller, whether it will now break or behave incorrectly because of the change
(e.g. a different return type or shape, None returned where a value was expected, a new exception,
a changed unit or meaning of a value, removed side effect, changed parameter meaning).

### `{qualname}` BEFORE the change
```python
{old_code}
```

### `{qualname}` AFTER the change (line numbers in `{file}`)
```python
{new_code}
```

## Callers not updated by the change
{callers}

## Output
Report ONLY callers that will break or misbehave. Each finding must be located at the CALLER's lines
(file and line numbers of the caller shown above), with evidence copied exactly from the caller code.
If every caller is still correct, return an empty findings list.

Return JSON exactly in this shape:
{{
  "findings": [
    {{
      "file": "<caller file>",
      "start_line": <int>,
      "end_line": <int>,
      "category": "bug|error_handling|edge_case",
      "severity": "critical|high|medium|low",
      "title": "<short title>",
      "description": "<what changed in {qualname} and why this caller now fails>",
      "evidence": ["<exact caller code line(s)>"],
      "recommendation": "<how to update the caller (or keep {qualname} compatible)>",
      "test_recommendation": "<test that would catch this>",
      "confidence": <0.0-1.0>
    }}
  ],
  "static_assessments": []
}}
