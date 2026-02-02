"""Tests for pagination helper module."""

import pytest
from pydantic import BaseModel

from beadhub.pagination import (
    DEFAULT_LIMIT,
    MAX_CURSOR_SIZE_BYTES,
    MAX_LIMIT,
    PaginatedResponse,
    decode_cursor,
    encode_cursor,
    validate_pagination_params,
)


class TestCursorEncoding:
    """Tests for cursor encoding/decoding."""

    def test_encode_cursor_returns_string(self):
        """encode_cursor should return a non-empty string."""
        cursor = encode_cursor({"id": "abc123", "timestamp": "2025-01-01T00:00:00Z"})
        assert isinstance(cursor, str)
        assert len(cursor) > 0

    def test_decode_cursor_reverses_encode(self):
        """decode_cursor should reverse encode_cursor."""
        data = {"id": "abc123", "timestamp": "2025-01-01T00:00:00Z"}
        cursor = encode_cursor(data)
        decoded = decode_cursor(cursor)
        assert decoded == data

    def test_encode_cursor_is_url_safe(self):
        """Encoded cursor should be URL-safe (no +, /, =)."""
        data = {"id": "test", "value": 12345}
        cursor = encode_cursor(data)
        # URL-safe base64 uses - and _ instead of + and /
        assert "+" not in cursor
        assert "/" not in cursor

    def test_decode_cursor_invalid_format(self):
        """decode_cursor should raise ValueError for invalid format."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("not-valid-base64!!!")

    def test_decode_cursor_invalid_json(self):
        """decode_cursor should raise ValueError for invalid JSON in cursor."""
        import base64

        invalid_json = base64.urlsafe_b64encode(b"not json").decode()
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(invalid_json)

    def test_decode_cursor_none(self):
        """decode_cursor should return None for None input."""
        assert decode_cursor(None) is None

    def test_decode_cursor_empty_string(self):
        """decode_cursor should return None for empty string."""
        assert decode_cursor("") is None

    def test_encode_cursor_handles_various_types(self):
        """encode_cursor should handle various JSON-serializable types."""
        data = {
            "string": "hello",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
        }
        cursor = encode_cursor(data)
        decoded = decode_cursor(cursor)
        assert decoded == data

    def test_encode_decode_empty_dict(self):
        """Empty dict should encode and decode correctly."""
        data = {}
        cursor = encode_cursor(data)
        decoded = decode_cursor(cursor)
        assert decoded == {}

    def test_encode_cursor_handles_unicode(self):
        """encode_cursor should handle non-ASCII characters."""
        data = {"user": "用户", "emoji": "🎉", "special": "café"}
        cursor = encode_cursor(data)
        decoded = decode_cursor(cursor)
        assert decoded == data

    def test_decode_cursor_rejects_non_dict(self):
        """decode_cursor should reject valid JSON that isn't a dict."""
        import base64

        # Encode a list instead of dict
        list_cursor = base64.urlsafe_b64encode(b"[1, 2, 3]").decode()
        with pytest.raises(ValueError, match="must decode to a dictionary"):
            decode_cursor(list_cursor)

        # Encode a string
        string_cursor = base64.urlsafe_b64encode(b'"just a string"').decode()
        with pytest.raises(ValueError, match="must decode to a dictionary"):
            decode_cursor(string_cursor)

    def test_decode_cursor_rejects_oversized_cursor(self):
        """decode_cursor should reject cursors exceeding MAX_CURSOR_SIZE_BYTES."""
        # Create a cursor that's too large
        oversized = "a" * (MAX_CURSOR_SIZE_BYTES + 1)
        with pytest.raises(ValueError, match="exceeds maximum size"):
            decode_cursor(oversized)


class TestValidatePaginationParams:
    """Tests for pagination parameter validation."""

    def test_default_limit(self):
        """Without limit, should return DEFAULT_LIMIT."""
        limit, cursor = validate_pagination_params(None, None)
        assert limit == DEFAULT_LIMIT
        assert cursor is None

    def test_explicit_limit(self):
        """Should accept explicit limit within bounds."""
        limit, cursor = validate_pagination_params(25, None)
        assert limit == 25

    def test_limit_clamped_to_max(self):
        """Limit above MAX_LIMIT should be clamped."""
        limit, cursor = validate_pagination_params(500, None)
        assert limit == MAX_LIMIT

    def test_limit_at_exact_max(self):
        """Limit exactly at MAX_LIMIT should be accepted unchanged."""
        limit, cursor = validate_pagination_params(MAX_LIMIT, None)
        assert limit == MAX_LIMIT

    def test_limit_minimum_is_one(self):
        """Limit less than 1 should be set to 1."""
        limit, cursor = validate_pagination_params(0, None)
        assert limit == 1

        limit, cursor = validate_pagination_params(-5, None)
        assert limit == 1

    def test_cursor_passed_through(self):
        """Valid cursor should be passed through."""
        original = encode_cursor({"id": "test"})
        limit, cursor = validate_pagination_params(10, original)
        assert cursor == {"id": "test"}

    def test_invalid_cursor_raises_error(self):
        """Invalid cursor should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            validate_pagination_params(10, "bad-cursor!!!")


class TestPaginatedResponse:
    """Tests for PaginatedResponse model."""

    def test_paginated_response_with_items(self):
        """Should create response with items, has_more, and cursor."""
        response = PaginatedResponse(
            items=[{"id": 1}, {"id": 2}],
            has_more=True,
            next_cursor="abc123",
        )
        assert len(response.items) == 2
        assert response.has_more is True
        assert response.next_cursor == "abc123"

    def test_paginated_response_no_more_items(self):
        """next_cursor should be None when has_more is False."""
        response = PaginatedResponse(
            items=[{"id": 1}],
            has_more=False,
            next_cursor=None,
        )
        assert response.has_more is False
        assert response.next_cursor is None

    def test_paginated_response_empty_items(self):
        """Should handle empty items list."""
        response = PaginatedResponse(
            items=[],
            has_more=False,
            next_cursor=None,
        )
        assert response.items == []
        assert response.has_more is False

    def test_paginated_response_with_typed_items(self):
        """Should work with typed item models."""

        class Item(BaseModel):
            id: str
            name: str

        response = PaginatedResponse[Item](
            items=[Item(id="1", name="first"), Item(id="2", name="second")],
            has_more=True,
            next_cursor="cursor123",
        )
        assert len(response.items) == 2
        assert response.items[0].id == "1"
        assert response.items[0].name == "first"

    def test_paginated_response_serializes_to_dict(self):
        """Should serialize to dict with correct structure."""
        response = PaginatedResponse(
            items=[{"id": 1}, {"id": 2}],
            has_more=True,
            next_cursor="abc",
        )
        data = response.model_dump()
        assert data == {
            "items": [{"id": 1}, {"id": 2}],
            "has_more": True,
            "next_cursor": "abc",
        }


class TestConstants:
    """Tests for pagination constants."""

    def test_default_limit_is_50(self):
        """Default limit should be 50 per spec."""
        assert DEFAULT_LIMIT == 50

    def test_max_limit_is_200(self):
        """Max limit should be 200 per spec."""
        assert MAX_LIMIT == 200
