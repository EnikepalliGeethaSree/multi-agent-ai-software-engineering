version: 1.1
---
## Repository file
`{file}` (excerpt: lines {start_line}-{end_line} of {total_lines}{scope_note})

{context_section}

{static_section}

## Excerpt to analyse
Line numbers are in the gutter.{changed_legend} Report defects in these lines only.

```python
{numbered_code}
```

## Output
Return JSON exactly in this shape. Use an empty `findings` list if the code is correct.
{{
  "findings": [
    {{
      "file": "{file}",
      "start_line": <int>,
      "end_line": <int>,
      "category": "bug|error_handling|edge_case|security",
      "bug_type": "logic|null_exception|boundary|resource_leak|concurrency|security|other",
      "severity": "critical|high|medium|low",
      "title": "<short title>",
      "root_cause": "<why the code misbehaves>",
      "trigger": "<the concrete input or state that makes it fail>",
      "expected": "<what should happen for that trigger>",
      "actual": "<what happens instead>",
      "involved_names": ["<identifiers the claim depends on, spelled as in the code>"],
      "evidence": ["<exact code line(s) copied from the excerpt>"],
      "repro_steps": ["<short steps a developer can follow to see the failure>"],
      "recommendation": "<concrete fix>",
      "fix_explanation": "<why that fix removes the bug>",
      "test_recommendation": "<a test that fails today and passes after the fix>",
      "confidence": <0.0-1.0>,
      "context_refs": ["<ids (C1, C2, ...) of project context items that support this finding; [] if none>"]
    }}
  ],
  "static_assessments": [
    {{"ref": "S1", "verdict": "confirm|false_positive|uncertain"}}
  ]
}}
