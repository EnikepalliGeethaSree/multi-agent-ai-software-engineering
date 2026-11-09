version: 1.1
---
## Repository file
`{file}` (review unit: lines {start_line}-{end_line} of {total_lines}{scope_note})

{context_section}

{static_section}

## Review unit
Line numbers are in the gutter.{changed_legend} Review ONLY these lines.

```python
{numbered_code}
```

## Output
Return JSON exactly in this shape:
{{
  "findings": [
    {{
      "file": "{file}",
      "start_line": <int>,
      "end_line": <int>,
      "category": "bug|security|error_handling|edge_case|performance|maintainability|quality|testing|standards|documentation",
      "severity": "critical|high|medium|low|info",
      "title": "<short title>",
      "description": "<what is wrong and why it matters>",
      "evidence": ["<exact code line(s) copied from the review unit>"],
      "recommendation": "<concrete fix>",
      "test_recommendation": "<concrete test to add>",
      "confidence": <0.0-1.0>,
      "cwe": "<CWE-id or null>",
      "context_refs": ["<ids (C1, C2, ...) of project context items that support this finding; [] if none>"]
    }}
  ],
  "static_assessments": [
    {{"ref": "S1", "verdict": "confirm|false_positive|uncertain", "recommendation": "<optional better fix>"}}
  ]
}}
