from __future__ import annotations

from typing import Any

import httpx


class CoolifyClient:
    def __init__(self, base_url: str, token: str | None, *, verify_tls: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify_tls = verify_tls

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def health(self) -> dict[str, Any]:
        response = httpx.get(f"{self.base_url}/api/health", verify=self.verify_tls, timeout=10)
        response.raise_for_status()
        return response.json()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/"):
            path = f"/{path}"
        if not path.startswith("/api/"):
            path = f"/api/v1{path}"
        response = httpx.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            json=payload,
            verify=self.verify_tls,
            timeout=20,
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()
