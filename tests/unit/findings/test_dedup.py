def test_a_finding_joins_the_closest_duplicate_not_the_first() -> None:
    """Ruff+AST flag the except on lines 4-5 (error handling); the AST flags a leak on 3-4 (bug).
    The LLM's error-handling finding on line 4 is compatible with both and must join the first."""
    from marl_agents.core.schemas import Category, Finding, FindingSource, Severity
    from marl_agents.findings.dedup import deduplicate

    def mk(start: int, end: int, cat: Category, src: FindingSource, title: str, rule: str | None):
        return Finding(id="X", file="a.py", start_line=start, end_line=end, category=cat,
                       severity=Severity.MEDIUM, title=title, description=title, sources=[src],
                       rule_id=rule, confidence=0.7)  # fmt: skip

    leak = mk(3, 4, Category.BUG, FindingSource.AST, "File opened without a context manager",
              "AST-RESOURCE-LEAK")  # fmt: skip
    swallow = mk(4, 5, Category.ERROR_HANDLING, FindingSource.AST, "Broad exception swallowed",
                 "AST-SWALLOWED-EXCEPTION")  # fmt: skip
    llm = mk(4, 4, Category.ERROR_HANDLING, FindingSource.LLM, "Exception swallowed", None)
    out = deduplicate([leak, swallow, llm]).findings
    joined = next(f for f in out if FindingSource.LLM in f.sources)
    assert joined.rule_id == "AST-SWALLOWED-EXCEPTION"
    assert next(f for f in out if f.rule_id == "AST-RESOURCE-LEAK").sources == [FindingSource.AST]
