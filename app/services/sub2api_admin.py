from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class Sub2APIAdminSettings:
    base_url: str | None
    api_key: str | None
    timeout_seconds: float = 10.0

    @property
    def is_configured(self) -> bool:
        return bool((self.base_url or "").strip() and (self.api_key or "").strip())


class Sub2APIAdminClient:
    def __init__(self, settings: Sub2APIAdminSettings) -> None:
        self.settings = settings

    def _url(self, path: str) -> str:
        base_url = (self.settings.base_url or "").strip().rstrip("/")
        if not base_url:
            raise RuntimeError("Sub2API admin base URL is not configured")
        if base_url.endswith("/api/v1"):
            prefix = base_url
        else:
            prefix = f"{base_url}/api/v1"
        return f"{prefix}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        api_key = (self.settings.api_key or "").strip()
        if not api_key:
            raise RuntimeError("Sub2API admin API key is not configured")
        return {"x-api-key": api_key}

    async def list_accounts(
        self,
        *,
        page_size: int = 200,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
            for page in range(1, max_pages + 1):
                response = await client.get(
                    self._url("/admin/accounts"),
                    headers=self._headers(),
                    params={"page": page, "page_size": page_size},
                )
                response.raise_for_status()
                payload = response.json()
                items = account_page_items(payload)
                accounts.extend(items)
                total = account_page_total(payload)
                if total is not None and len(accounts) >= total:
                    break
                if len(items) < page_size:
                    break
        return accounts

    async def bulk_set_schedulable(
        self,
        account_ids: Sequence[int],
        schedulable: bool,
    ) -> dict[str, Any]:
        return await self.bulk_update_accounts(account_ids, {"schedulable": schedulable})

    async def bulk_update_accounts(
        self,
        account_ids: Sequence[int],
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        ids = [int(account_id) for account_id in account_ids]
        if not ids:
            return {"success": 0, "failed": 0, "success_ids": [], "failed_ids": [], "results": []}
        async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
            response = await client.post(
                self._url("/admin/accounts/bulk-update"),
                headers=self._headers(),
                json={"account_ids": ids, **updates},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Sub2API bulk-update returned a non-object response")
        return payload


def account_page_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("items")
    if raw_items is None:
        raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def account_page_total(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    total = payload.get("total")
    return int(total) if isinstance(total, int | float) else None
