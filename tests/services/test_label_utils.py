from __future__ import annotations

import pytest

from backend.services.label_utils import dedup_key, validate_label_name


class TestValidateLabelName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Python", "python"),
            ("  future plans  ", "future plans"),
            ("future-plans", "future-plans"),
            ("future_plans", "future_plans"),
            ("cake123", "cake123"),
        ],
    )
    def test_valid_names_are_normalized(self, raw: str, expected: str) -> None:
        assert validate_label_name(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "a" * 65,
            "not! valid$$",
            "emoji🙂",
        ],
    )
    def test_invalid_names_return_none(self, raw: str) -> None:
        assert validate_label_name(raw) is None


class TestDedupKey:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("future-plans", "future_plans"),
            ("future_plans", "future plans"),
            ("Future Plans", "future plans"),
            ("  vegan  ", "vegan"),
        ],
    )
    def test_variants_collide(self, a: str, b: str) -> None:
        assert dedup_key(a) == dedup_key(b)

    def test_distinct_names_do_not_collide(self) -> None:
        assert dedup_key("cake") != dedup_key("chocolate")
