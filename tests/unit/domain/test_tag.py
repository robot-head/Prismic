from dataclasses import FrozenInstanceError

import pytest

from prismic.domain.tag import InvalidTagNameError, Tag, validate_tag_name


def test_trims_surrounding_whitespace() -> None:
    assert validate_tag_name("  vacation  ") == "vacation"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "multi\nline", "multi\rline"],
    ids=["empty", "whitespace-only", "line-feed", "carriage-return"],
)
def test_rejects_invalid_names(name: str) -> None:
    with pytest.raises(InvalidTagNameError):
        validate_tag_name(name)


def test_allows_unicode() -> None:
    assert validate_tag_name("日本語") == "日本語"


def test_is_case_sensitive_at_the_value_level() -> None:
    assert validate_tag_name("Vacation") != validate_tag_name("vacation")


def test_tag_is_a_plain_value_type() -> None:
    tag = Tag(id=1, name="vacation")
    assert tag.id == 1
    assert tag.name == "vacation"


def test_tag_value_is_immutable() -> None:
    tag = Tag(id=1, name="vacation")

    with pytest.raises(FrozenInstanceError):
        tag.name = "renamed"  # type: ignore[misc]
