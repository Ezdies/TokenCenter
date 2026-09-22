import asyncio
from dataclasses import dataclass, field

import pytest

from policy_engine.litellm_plugin import SpikePolicyRouter


@dataclass
class FakeRoutingContext:
    candidate_models: list[str]
    signals: dict[str, object] = field(default_factory=dict)


def test_spike_plugin_selects_free_candidate_and_records_reason() -> None:
    context = FakeRoutingContext(candidate_models=["openai/spike-paid", "openai/spike-free"])

    result = asyncio.run(SpikePolicyRouter().run(context))

    assert result.candidate_models == ["openai/spike-free"]
    assert result.signals["token_center"] == {
        "policy": "spike-free-first",
        "selected_model": "openai/spike-free",
        "candidates_before": ["openai/spike-paid", "openai/spike-free"],
        "reason": "free candidate is available",
    }


def test_spike_plugin_fails_closed_without_required_candidate() -> None:
    context = FakeRoutingContext(candidate_models=["openai/spike-paid"])

    with pytest.raises(ValueError, match="Required spike candidate is unavailable"):
        asyncio.run(SpikePolicyRouter().run(context))
