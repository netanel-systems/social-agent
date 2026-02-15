"""Tests for social_agent.brain.

All tests use mocked LearningLLM — no real LLM API calls.
Tests verify namespace management, prompt seeding, lazy initialization,
stats aggregation, and error handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from social_agent.brain import AgentBrain
from social_agent.prompts import NAMESPACES

if TYPE_CHECKING:
    from pathlib import Path


# --- Fixtures ---


@pytest.fixture
def tmp_memories(tmp_path: Path) -> Path:
    """Temporary memories directory."""
    memories = tmp_path / "memories"
    memories.mkdir()
    return memories


@pytest.fixture
def brain(tmp_memories: Path) -> AgentBrain:
    """AgentBrain with temporary memories directory."""
    return AgentBrain(memories_dir=tmp_memories)


# --- Constructor ---


def test_default_construction(tmp_memories: Path) -> None:
    """AgentBrain can be created with just memories_dir."""
    brain = AgentBrain(memories_dir=tmp_memories)
    assert brain.memories_dir == tmp_memories
    assert brain.initialized_namespaces == []


def test_custom_models(tmp_memories: Path) -> None:
    """AgentBrain accepts custom model configuration."""
    brain = AgentBrain(
        memories_dir=tmp_memories,
        primary_model="gpt-4o",
        evaluator_model="gpt-4o",
        quality_threshold=0.8,
    )
    assert brain._primary_model == "gpt-4o"
    assert brain._evaluator_model == "gpt-4o"
    assert brain._quality_threshold == 0.8


# --- Namespace validation ---


def test_validate_known_namespace(brain: AgentBrain) -> None:
    """Known namespaces pass validation."""
    for ns in NAMESPACES:
        brain._validate_namespace(ns)  # Should not raise


def test_validate_unknown_namespace(brain: AgentBrain) -> None:
    """Unknown namespace raises ValueError."""
    with pytest.raises(ValueError, match="Unknown namespace"):
        brain._validate_namespace("invalid-namespace")


def test_call_unknown_namespace(brain: AgentBrain) -> None:
    """call() rejects unknown namespaces."""
    with pytest.raises(ValueError, match="Unknown namespace"):
        brain.call("not-a-namespace", "task")


def test_stats_unknown_namespace(brain: AgentBrain) -> None:
    """stats() rejects unknown namespaces."""
    with pytest.raises(ValueError, match="Unknown namespace"):
        brain.stats("not-a-namespace")


# --- Prompt seeding ---


@patch("social_agent.brain.LearningLLM")
def test_prompt_seeded_on_first_use(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """Initial prompt is written to disk on first namespace use."""
    brain = AgentBrain(memories_dir=tmp_memories)
    brain._get_or_create("moltbook-decide")

    # Prompt file should exist
    prompt_dir = tmp_memories / "moltbook-decide" / "prompts"
    prompt_file = prompt_dir / "prompt_current.md"
    assert prompt_file.exists()

    # Content should match the PROMPTS dict
    content = prompt_file.read_text()
    assert "strategic decision-maker" in content


@patch("social_agent.brain.LearningLLM")
def test_prompt_not_overwritten(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """Existing prompt is preserved (not overwritten on re-init)."""
    brain = AgentBrain(memories_dir=tmp_memories)

    # First init — seeds prompt
    brain._get_or_create("moltbook-content")
    prompt_file = tmp_memories / "moltbook-content" / "prompts" / "prompt_current.md"
    assert prompt_file.exists()

    # Modify prompt (simulating evolution)
    prompt_file.write_text("Evolved prompt content")

    # New brain instance — should NOT overwrite
    brain2 = AgentBrain(memories_dir=tmp_memories)
    brain2._get_or_create("moltbook-content")
    assert prompt_file.read_text() == "Evolved prompt content"


@patch("social_agent.brain.LearningLLM")
def test_all_namespaces_seed_correctly(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """All 4 namespaces seed their prompts."""
    brain = AgentBrain(memories_dir=tmp_memories)
    for ns in NAMESPACES:
        brain._get_or_create(ns)

    for ns in NAMESPACES:
        prompt_file = tmp_memories / ns / "prompts" / "prompt_current.md"
        assert prompt_file.exists(), f"Prompt not seeded for {ns}"


# --- Lazy initialization ---


@patch("social_agent.brain.LearningLLM")
def test_lazy_init(mock_llm_class: MagicMock, tmp_memories: Path) -> None:
    """LearningLLM is only created on first call to a namespace."""
    brain = AgentBrain(memories_dir=tmp_memories)
    assert brain.initialized_namespaces == []

    brain._get_or_create("moltbook-decide")
    assert "moltbook-decide" in brain.initialized_namespaces
    assert mock_llm_class.call_count == 1

    # Second call reuses existing instance
    brain._get_or_create("moltbook-decide")
    assert mock_llm_class.call_count == 1  # Not called again


@patch("social_agent.brain.LearningLLM")
def test_separate_instances_per_namespace(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """Each namespace gets its own LearningLLM instance."""
    brain = AgentBrain(memories_dir=tmp_memories)
    brain._get_or_create("moltbook-decide")
    brain._get_or_create("moltbook-content")
    assert mock_llm_class.call_count == 2
    assert len(brain.initialized_namespaces) == 2


# --- call() ---


@patch("social_agent.brain.LearningLLM")
def test_call_delegates_to_llm(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """call() delegates to the correct LearningLLM instance."""
    mock_result = MagicMock()
    mock_result.response = "READ_FEED"
    mock_result.score = 0.85
    mock_result.passed = True

    mock_instance = MagicMock()
    mock_instance.call.return_value = mock_result
    mock_llm_class.return_value = mock_instance

    brain = AgentBrain(memories_dir=tmp_memories)
    result = brain.call("moltbook-decide", "What should I do?")

    assert result.response == "READ_FEED"
    assert result.score == 0.85
    mock_instance.call.assert_called_once_with("What should I do?")


@patch("social_agent.brain.LearningLLM")
def test_call_different_namespaces(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """Different namespaces use separate LLM instances."""
    mock_decide = MagicMock()
    mock_content = MagicMock()

    # Return different mocks for different calls
    mock_llm_class.side_effect = [mock_decide, mock_content]

    brain = AgentBrain(memories_dir=tmp_memories)
    brain.call("moltbook-decide", "decide task")
    brain.call("moltbook-content", "content task")

    mock_decide.call.assert_called_once_with("decide task")
    mock_content.call.assert_called_once_with("content task")


# --- stats() ---


def test_stats_uninitialized_namespace(brain: AgentBrain) -> None:
    """stats() returns minimal data for uninitialized namespace."""
    result = brain.stats("moltbook-decide")
    assert result["total_calls"] == 0
    assert result["initialized"] is False
    assert result["namespace"] == "moltbook-decide"


@patch("social_agent.brain.LearningLLM")
def test_stats_initialized_namespace(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """stats() returns full data for initialized namespace."""
    mock_instance = MagicMock()
    mock_instance.stats = {
        "total_calls": 42,
        "total_learnings_stored": 10,
        "calls_since_evolution": 12,
        "evaluator_threshold": 0.75,
    }
    mock_llm_class.return_value = mock_instance

    brain = AgentBrain(memories_dir=tmp_memories)
    brain._get_or_create("moltbook-reply")

    result = brain.stats("moltbook-reply")
    assert result["total_calls"] == 42
    assert result["initialized"] is True
    assert result["namespace"] == "moltbook-reply"


# --- all_stats() ---


@patch("social_agent.brain.LearningLLM")
def test_all_stats_covers_all_namespaces(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """all_stats() returns stats for all 4 namespaces."""
    brain = AgentBrain(memories_dir=tmp_memories)
    result = brain.all_stats()

    assert len(result) == len(NAMESPACES)
    for ns in NAMESPACES:
        assert ns in result
        assert result[ns]["namespace"] == ns


@patch("social_agent.brain.LearningLLM")
def test_all_stats_mixed_initialized(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """all_stats() handles mix of initialized and uninitialized namespaces."""
    mock_instance = MagicMock()
    mock_instance.stats = {"total_calls": 5, "total_learnings_stored": 1}
    mock_llm_class.return_value = mock_instance

    brain = AgentBrain(memories_dir=tmp_memories)
    brain._get_or_create("moltbook-decide")

    result = brain.all_stats()
    assert result["moltbook-decide"]["initialized"] is True
    assert result["moltbook-content"]["initialized"] is False


# --- get_store() ---


@patch("social_agent.brain.LearningLLM")
def test_get_store_returns_memory_store(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """get_store() returns the MemoryStore for a namespace."""
    brain = AgentBrain(memories_dir=tmp_memories)
    store = brain.get_store("moltbook-analyze")

    # Should have initialized the namespace
    assert "moltbook-analyze" in brain.initialized_namespaces
    assert store is not None


@patch("social_agent.brain.LearningLLM")
def test_get_store_unknown_namespace(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """get_store() rejects unknown namespaces."""
    brain = AgentBrain(memories_dir=tmp_memories)
    with pytest.raises(ValueError, match="Unknown namespace"):
        brain.get_store("bad-namespace")


# --- NathanConfig wiring ---


@patch("social_agent.brain.LearningLLM")
def test_config_uses_correct_namespace(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """NathanConfig is created with the correct namespace."""
    brain = AgentBrain(memories_dir=tmp_memories)
    brain._get_or_create("moltbook-decide")

    config = brain._configs["moltbook-decide"]
    assert config.namespace == "moltbook-decide"
    assert config.memories_dir == tmp_memories


@patch("social_agent.brain.LearningLLM")
def test_config_uses_custom_models(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """NathanConfig picks up custom model settings."""
    brain = AgentBrain(
        memories_dir=tmp_memories,
        primary_model="gpt-4o",
        evaluator_model="gpt-4o",
    )
    brain._get_or_create("moltbook-content")

    config = brain._configs["moltbook-content"]
    assert config.models.primary_model == "gpt-4o"
    assert config.models.evaluator_model == "gpt-4o"
    assert config.models.extractor_model == "gpt-4o"


@patch("social_agent.brain.LearningLLM")
def test_config_uses_custom_quality_threshold(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """NathanConfig applies custom quality threshold to both safety and eval."""
    brain = AgentBrain(
        memories_dir=tmp_memories,
        quality_threshold=0.8,
    )
    brain._get_or_create("moltbook-reply")

    config = brain._configs["moltbook-reply"]
    assert config.safety.quality_threshold == 0.8
    assert config.evaluation.initial_threshold == 0.8


@patch("social_agent.brain.LearningLLM")
def test_directories_created_on_init(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """Memory directories are created when a namespace is initialized."""
    brain = AgentBrain(memories_dir=tmp_memories)
    brain._get_or_create("moltbook-decide")

    patterns_dir = tmp_memories / "moltbook-decide" / "patterns"
    prompts_dir = tmp_memories / "moltbook-decide" / "prompts"
    global_dir = tmp_memories / "global" / "patterns"

    assert patterns_dir.is_dir()
    assert prompts_dir.is_dir()
    assert global_dir.is_dir()


# --- LearningLLM receives correct config ---


@patch("social_agent.brain.LearningLLM")
def test_llm_created_with_config(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """LearningLLM is created with the correct NathanConfig."""
    brain = AgentBrain(memories_dir=tmp_memories)
    brain._get_or_create("moltbook-analyze")

    mock_llm_class.assert_called_once()
    passed_config = mock_llm_class.call_args[0][0]
    assert passed_config.namespace == "moltbook-analyze"


# --- Edge cases ---


@patch("social_agent.brain.LearningLLM")
def test_multiple_calls_same_namespace(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """Multiple calls to same namespace reuse the same instance."""
    mock_instance = MagicMock()
    mock_result = MagicMock()
    mock_instance.call.return_value = mock_result
    mock_llm_class.return_value = mock_instance

    brain = AgentBrain(memories_dir=tmp_memories)
    brain.call("moltbook-decide", "task 1")
    brain.call("moltbook-decide", "task 2")

    assert mock_llm_class.call_count == 1  # Only one LearningLLM created
    assert mock_instance.call.call_count == 2  # But two calls made


@patch("social_agent.brain.LearningLLM")
def test_initialized_namespaces_ordering(
    mock_llm_class: MagicMock, tmp_memories: Path
) -> None:
    """initialized_namespaces reflects order of initialization."""
    brain = AgentBrain(memories_dir=tmp_memories)
    brain._get_or_create("moltbook-content")
    brain._get_or_create("moltbook-decide")

    initialized = brain.initialized_namespaces
    assert initialized == ["moltbook-content", "moltbook-decide"]
