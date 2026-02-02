from __future__ import annotations

import json
from typing import Any, List


class JSONLParseError(ValueError):
    """Raised when JSONL parsing fails with line context."""


def _check_json_depth(obj: object, max_depth: int, current_depth: int = 0) -> bool:
    """Return True if JSON nesting depth is within limit."""

    if current_depth >= max_depth:
        return False
    if isinstance(obj, dict):
        for v in obj.values():
            if not _check_json_depth(v, max_depth, current_depth + 1):
                return False
        return True
    if isinstance(obj, list):
        for item in obj:
            if not _check_json_depth(item, max_depth, current_depth + 1):
                return False
        return True
    return True


def parse_jsonl(
    content: str,
    *,
    max_depth: int = 10,
    max_count: int = 10000,
) -> List[dict[str, Any]]:
    """
    Parse JSONL content into a list of dicts.

    - Skips empty lines
    - Validates max_count incrementally (fails fast)
    - Validates per-record nesting depth

    Raises:
        JSONLParseError: on invalid JSON, recursion errors, or depth/count violations
    """

    issues: list[dict[str, Any]] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if len(issues) >= max_count:
            raise JSONLParseError(f"Too many issues: exceeds limit of {max_count}")
        try:
            issue = json.loads(line)
        except json.JSONDecodeError as e:
            raise JSONLParseError(f"Invalid JSON on line {line_num}: {e.msg}") from e
        except RecursionError as e:
            raise JSONLParseError(
                f"JSON nesting too deep on line {line_num}: exceeds recursion limit"
            ) from e
        if not isinstance(issue, dict):
            raise JSONLParseError(f"JSON on line {line_num} must be an object")
        if not _check_json_depth(issue, max_depth):
            raise JSONLParseError(
                f"JSON nesting depth exceeds limit ({max_depth}) on line {line_num}"
            )
        issues.append(issue)
    return issues
