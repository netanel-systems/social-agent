"""Tests for social_agent.prompts."""

from __future__ import annotations

from social_agent.prompts import NAMESPACES, PROMPTS


def test_all_namespaces_have_prompts() -> None:
    """Every namespace in NAMESPACES has a corresponding prompt."""
    for ns in NAMESPACES:
        assert ns in PROMPTS, f"Missing prompt for namespace: {ns}"


def test_four_namespaces() -> None:
    """Architecture defines exactly 4 namespaces."""
    assert len(NAMESPACES) == 4


def test_expected_namespaces() -> None:
    """Namespace names match Architecture Section 4."""
    expected = {"moltbook-decide", "moltbook-content", "moltbook-reply", "moltbook-analyze"}
    assert set(NAMESPACES) == expected


def test_prompts_not_empty() -> None:
    """Every prompt has substantive content."""
    for ns, prompt in PROMPTS.items():
        assert len(prompt.strip()) > 50, f"Prompt for {ns} is too short"


def test_namespaces_matches_prompts_keys() -> None:
    """NAMESPACES list is exactly the PROMPTS keys (same order)."""
    assert list(PROMPTS.keys()) == NAMESPACES
