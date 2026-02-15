"""Agent brain — per-namespace self-learning LLM instances.

Wraps netanel-core's LearningLLM with namespace-aware configuration.
Each namespace (decide, content, reply, analyze) learns independently.
Prompts are seeded on first use and evolve automatically over time.

All reasoning runs locally (LLM API calls). Actions execute in E2B.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from netanel_core import CallResult, LearningLLM, MemoryStore, NathanConfig
from netanel_core.config import EvalConfig, ModelConfig, SafetyBounds

from social_agent.prompts import NAMESPACES, PROMPTS

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class AgentBrain:
    """Per-namespace self-learning brain powered by netanel-core.

    Each namespace has its own LearningLLM instance with independent
    memory, evaluation, and prompt evolution. Prompts are seeded from
    social_agent.prompts on first use and evolve automatically as the
    agent learns from interactions.

    Usage::

        brain = AgentBrain(memories_dir=Path("memories"))
        result = brain.call("moltbook-decide", "What should I do next?")
        print(result.response)  # The decision
        print(result.score)     # Quality score

    """

    def __init__(
        self,
        memories_dir: Path,
        *,
        primary_model: str = "gpt-4o-mini",
        evaluator_model: str = "gpt-4o-mini",
        quality_threshold: float = 0.7,
    ) -> None:
        self._memories_dir = memories_dir
        self._primary_model = primary_model
        self._evaluator_model = evaluator_model
        self._quality_threshold = quality_threshold
        self._instances: dict[str, LearningLLM] = {}
        self._configs: dict[str, NathanConfig] = {}
        self._stores: dict[str, MemoryStore] = {}

    def _validate_namespace(self, namespace: str) -> None:
        """Validate namespace is one of the known namespaces.

        Raises:
            ValueError: If namespace is not in NAMESPACES.
        """
        if namespace not in NAMESPACES:
            msg = f"Unknown namespace '{namespace}'. Valid: {NAMESPACES}"
            raise ValueError(msg)

    def _get_or_create(self, namespace: str) -> LearningLLM:
        """Get or lazily create a LearningLLM for a namespace.

        On first call for a namespace:
        1. Creates NathanConfig with the namespace's settings
        2. Seeds the initial prompt if not already present
        3. Creates and caches the LearningLLM instance

        Args:
            namespace: One of NAMESPACES.

        Returns:
            The LearningLLM instance for this namespace.
        """
        if namespace in self._instances:
            return self._instances[namespace]

        config = NathanConfig(
            namespace=namespace,
            memories_dir=self._memories_dir,
            models=ModelConfig(
                primary_model=self._primary_model,
                evaluator_model=self._evaluator_model,
                extractor_model=self._primary_model,
            ),
            safety=SafetyBounds(
                quality_threshold=self._quality_threshold,
            ),
            evaluation=EvalConfig(
                initial_threshold=self._quality_threshold,
            ),
        )
        config.ensure_directories()

        store = MemoryStore(config)
        existing_prompt = store.read_prompt()
        if existing_prompt is None and namespace in PROMPTS:
            store.write_prompt(PROMPTS[namespace])
            logger.info("Seeded initial prompt for namespace '%s'", namespace)

        llm = LearningLLM(config)

        self._configs[namespace] = config
        self._stores[namespace] = store
        self._instances[namespace] = llm

        logger.info("Initialized LearningLLM for namespace '%s'", namespace)
        return llm

    def call(self, namespace: str, task: str) -> CallResult:
        """Execute a self-learning LLM call in a namespace.

        The call goes through netanel-core's full pipeline:
        retrieve memories -> build context -> call LLM -> evaluate ->
        retry if needed -> extract learnings -> store patterns ->
        check evolution triggers -> return result.

        Args:
            namespace: One of NAMESPACES (e.g. "moltbook-decide").
            task: The task/instruction for the LLM.

        Returns:
            CallResult with response, quality score, metadata.

        Raises:
            ValueError: If namespace is unknown or task is empty.
        """
        self._validate_namespace(namespace)
        if not task or not task.strip():
            msg = "task must be a non-empty string"
            raise ValueError(msg)
        llm = self._get_or_create(namespace)
        return llm.call(task)

    def stats(self, namespace: str) -> dict[str, Any]:
        """Get learning statistics for a namespace.

        Args:
            namespace: One of NAMESPACES.

        Returns:
            Dict with total_calls, learnings_stored, threshold, etc.
            Returns minimal stats if namespace hasn't been used yet.

        Raises:
            ValueError: If namespace is unknown.
        """
        self._validate_namespace(namespace)
        if namespace not in self._instances:
            return {
                "total_calls": 0,
                "total_learnings_stored": 0,
                "calls_since_evolution": 0,
                "namespace": namespace,
                "initialized": False,
            }
        return {
            **self._instances[namespace].stats,
            "namespace": namespace,
            "initialized": True,
        }

    def all_stats(self) -> dict[str, dict[str, Any]]:
        """Get learning statistics for all namespaces.

        Returns:
            Dict mapping namespace name to stats dict.
            Uninitialized namespaces show minimal stats.
        """
        return {ns: self.stats(ns) for ns in NAMESPACES}

    def get_store(self, namespace: str) -> MemoryStore:
        """Get the MemoryStore for a namespace.

        Forces initialization if the namespace hasn't been used yet.
        Useful for writing global memories or inspecting stored patterns.

        Args:
            namespace: One of NAMESPACES.

        Returns:
            The MemoryStore instance for this namespace.

        Raises:
            ValueError: If namespace is unknown.
        """
        self._validate_namespace(namespace)
        self._get_or_create(namespace)
        return self._stores[namespace]

    @property
    def initialized_namespaces(self) -> list[str]:
        """List of namespaces that have been initialized."""
        return list(self._instances.keys())

    @property
    def memories_dir(self) -> Path:
        """Path to the memories directory."""
        return self._memories_dir
