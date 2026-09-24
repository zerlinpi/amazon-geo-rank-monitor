from __future__ import annotations

from typing import Any


class ProviderRegistry:
    def __init__(self, *, managed: Any, strict: Any) -> None:
        self._providers = {"managed": managed, "strict": strict}

    def get(self, mode: str) -> Any:
        try:
            return self._providers[mode]
        except KeyError as exc:
            raise ValueError(f"unsupported provider mode: {mode}") from exc
