"""Disposable LiteLLM router-plugin spike.

This module proves the v1.101.0 plugin boundary. It is intentionally not the
production routing policy from implementation-plan stage 3.
"""

from typing import Protocol


class RoutingContextLike(Protocol):
    candidate_models: list[str]
    signals: dict[str, object]


class SpikePolicyRouter:
    """Select the free mock deployment and expose an explainability signal."""

    FREE_MODEL = "openai/spike-free"

    async def run(self, context: RoutingContextLike) -> RoutingContextLike:
        candidates_before = tuple(context.candidate_models)
        if self.FREE_MODEL not in candidates_before:
            raise ValueError(f"Required spike candidate is unavailable: {self.FREE_MODEL}")

        context.candidate_models = [self.FREE_MODEL]
        context.signals["token_center"] = {
            "policy": "spike-free-first",
            "selected_model": self.FREE_MODEL,
            "candidates_before": list(candidates_before),
            "reason": "free candidate is available",
        }
        return context


spike_policy_router = SpikePolicyRouter()
