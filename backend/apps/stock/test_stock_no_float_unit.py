"""Unit test: the stock app must never use float for money values.

Parses every .py file under apps/stock (including test files, excluding this
one) with ast and fails on any float literal, float() call or import of the
float type. Reports the offending file and line.

Pure logic, no database. Marked unit.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

STOCK_DIR = Path(__file__).resolve().parent
SELF = Path(__file__).resolve().name
REPO_ROOT = STOCK_DIR.parents[2]


def _float_violations(source: str, filename: str) -> list[str]:
    violations: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, float):
                violations.append(f"{filename}:{node.lineno}: float literal {node.value!r}")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id == "float":
                violations.append(f"{filename}:{node.lineno}: float() call")
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                if alias.name == "float":
                    violations.append(f"{filename}:{node.lineno}: import of float type")
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                if alias.name == "float":
                    violations.append(
                        f"{filename}:{node.lineno}: import of float type from {node.module!r}"
                    )
            self.generic_visit(node)

    tree = ast.parse(source, filename=filename)
    Visitor().visit(tree)
    return violations


def _iter_stock_files() -> list[Path]:
    return sorted(p for p in STOCK_DIR.rglob("*.py") if p.name != SELF)


def test_no_float_used_for_money_values():
    violations: list[str] = []
    for path in _iter_stock_files():
        rel = path.relative_to(REPO_ROOT)
        violations.extend(_float_violations(path.read_text(encoding="utf-8"), str(rel)))
    assert not violations, "float used for money values in apps/stock:\n" + "\n".join(violations)
