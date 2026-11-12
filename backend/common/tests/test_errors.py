"""Scan test: error code string literals must not appear outside common/errors.py and tests.

Every error code is defined once in ``common.errors`` and referenced as a
constant everywhere else. This test fails if any quoted string equal to a
constant value is found in production code (apps/ or common/, excluding
``common/errors.py`` itself and anything under a ``tests`` directory).
"""

import re
from pathlib import Path

from django.test import TestCase

from common import errors

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
SCAN_DIRS = [BACKEND_DIR / "apps", BACKEND_DIR / "common"]

_STRING_RE = re.compile(r"""["']([^"']*)["']""")

CODE_VALUES = {getattr(errors, name) for name in errors.__all__}


def _is_excluded(path: Path) -> bool:
    parts = path.relative_to(BACKEND_DIR).parts
    if parts == ("common", "errors.py"):
        return True
    if "tests" in parts:
        return True
    name = parts[-1]
    if name == "tests.py" or name.startswith("test_") or name.endswith("_tests.py"):
        return True
    return False


class TestErrorCodeLiterals(TestCase):
    """No error code string literals outside common/errors.py and tests."""

    def test_no_error_code_string_literals_outside_errors_module(self):
        violations = []
        for scan_dir in SCAN_DIRS:
            for path in sorted(scan_dir.rglob("*.py")):
                if _is_excluded(path):
                    continue
                text = path.read_text(encoding="utf-8")
                for match in _STRING_RE.finditer(text):
                    if match.group(1) in CODE_VALUES:
                        violations.append(f"{path}:{match.group(1)!r}")
        self.assertFalse(
            violations,
            "Found error code string literals outside common/errors.py and tests:\n"
            + "\n".join(sorted(violations)),
        )
