from marl_agents.parsing import SymbolKind, module_name_for, parse_python

SOURCE = '''"""Module doc."""
import os
import numpy as np
from .db import query as q, connect

@decorator
@other.deco(1)
def top(a, b=1, *args, key, **kw):
    """Top doc."""
    q("x")
    os.path.join(a, b)
    return helper(a)

async def fetch():
    await client.get()

class Service(Base):
    """Svc."""
    rate = compute_rate()

    def run(self):
        def inner():
            return 1
        return self.top()
'''


def test_symbols_kinds_lines_and_metadata() -> None:
    m = parse_python(SOURCE, "pkg/mod.py")
    by = {s.qualname: s for s in m.symbols}
    assert set(by) == {"top", "fetch", "Service", "Service.run", "Service.run.inner"}
    top = by["top"]
    assert top.kind is SymbolKind.FUNCTION
    assert top.start_line == 6 and top.def_line == 8  # decorators included
    assert top.decorators == ["decorator", "other.deco"]
    assert top.params == ["a", "b", "*args", "key", "**kw"]
    assert top.docstring == "Top doc."
    assert top.calls == ["q", "os.path.join", "helper"]
    assert top.return_count == 1
    assert by["fetch"].kind is SymbolKind.ASYNC_FUNCTION
    assert by["Service"].bases == ["Base"] and by["Service"].calls == ["compute_rate"]
    assert by["Service.run"].kind is SymbolKind.METHOD and by["Service.run"].parent == "Service"
    # calls of nested functions are not attributed to the parent
    assert by["Service.run"].calls == ["self.top"]
    assert m.docstring == "Module doc."


def test_imports_and_aliases() -> None:
    m = parse_python(SOURCE, "pkg/mod.py")
    aliases = {k: v for imp in m.imports for k, v in imp.alias_map.items()}
    assert aliases == {"os": "os", "np": "numpy", "q": "db.query", "connect": "db.connect"}
    rel = next(i for i in m.imports if i.is_from)
    assert rel.level == 1 and rel.module == "db"


def test_symbol_at_returns_innermost() -> None:
    m = parse_python(SOURCE, "pkg/mod.py")
    assert m.symbol_at(23).qualname == "Service.run.inner"  # type: ignore[union-attr]
    assert m.symbol_at(21).qualname == "Service.run"  # type: ignore[union-attr]
    assert m.symbol_at(2) is None


def test_syntax_error_is_reported_not_raised() -> None:
    m = parse_python("def broken(:\n    pass\n", "bad.py")
    assert m.syntax_error and m.syntax_error_line == 1 and m.symbols == []


def test_module_name_for() -> None:
    assert module_name_for("src/pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_name_for("pkg/__init__.py") == "pkg"
    assert module_name_for("app.py") == "app"


def test_repo_index_call_graph_and_tests(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index(
        {
            "app/__init__.py": "",
            "app/db.py": "def query(sql):\n    return run(sql)\n\ndef run(sql):\n    return sql\n",
            "app/service.py": "from .db import query\n\ndef get_user(uid):\n    return query(uid)\n",
            "app/other.py": "def query(x):\n    return x\n",
            "tests/test_service.py": "from app.service import get_user\n\ndef test_get_user():\n    assert get_user(1)\n",
        }
    )
    service = index.modules["app/service.py"]
    get_user = service.symbols[0]
    callees = index.callees("app/service.py", get_user)
    # resolved through the relative import, not to the unrelated app/other.py:query
    assert [(c.file, c.symbol.name) for c in callees] == [("app/db.py", "query")]
    db_query = index.modules["app/db.py"].symbols[0]
    assert [c.symbol.name for c in index.callers("app/db.py", db_query)] == ["get_user"]
    assert index.callees("app/db.py", db_query)[0].symbol.name == "run"  # same-file preference
    assert index.tests_referencing("get_user") == ["tests/test_service.py"]
    assert index.tests_referencing("run") == []
    assert index.has_tests()
