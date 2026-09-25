import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    redis_url: str
    litellm_base_url: str
    litellm_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://token_center:local-postgres-password@127.0.0.1:5432/gateway",
            ),
            redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            litellm_base_url=os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
            litellm_timeout_seconds=float(os.getenv("LITELLM_TIMEOUT_SECONDS", "120")),
        )
