import asyncio
from types import SimpleNamespace

import httpx

import app.services.provider_strategy as provider_module
from app.core.security import encrypt_secret
from app.services.provider_strategy import Sub2ApiStrategy, YunjinNewApiSiteStrategy


def platform(base_url: str) -> SimpleNamespace:
    return SimpleNamespace(base_url=base_url)


def test_yunjin_site_url_keeps_subpath_deployment() -> None:
    assert (
        YunjinNewApiSiteStrategy.site_url(platform("https://example.com/yunjin/login"))
        == "https://example.com/yunjin/"
    )


def test_yunjin_site_url_strips_page_and_api_suffixes() -> None:
    assert (
        YunjinNewApiSiteStrategy.site_url(platform("https://example.com/yunjin/pricing"))
        == "https://example.com/yunjin/"
    )
    assert (
        YunjinNewApiSiteStrategy.site_url(platform("https://example.com/yunjin/api"))
        == "https://example.com/yunjin/"
    )


def test_yunjin_site_url_root_domain_has_trailing_slash() -> None:
    assert (
        YunjinNewApiSiteStrategy.site_url(platform("https://relayai.tech/login"))
        == "https://relayai.tech/"
    )


def test_yunjin_origin_ignores_subpath() -> None:
    assert (
        YunjinNewApiSiteStrategy.site_origin(platform("https://example.com/yunjin/login"))
        == "https://example.com"
    )


def test_relative_endpoint_keeps_subpath_base_url() -> None:
    with httpx.Client(base_url="https://example.com/yunjin/") as client:
        request = client.build_request("GET", "api/pricing")

    assert str(request.url) == "https://example.com/yunjin/api/pricing"


def test_yunjin_group_catalog_parser_reads_desc_and_ratio() -> None:
    payload = {
        "data": {
            "codex": {
                "desc": "codex分组，（自营稳定）",
                "ratio": 0.08,
            },
            "A-CCMAX": {
                "desc": "Claude MAX",
                "ratio": "1.8",
            },
        },
        "message": "",
        "success": True,
    }

    groups = YunjinNewApiSiteStrategy.parse_group_catalog_payload(payload)

    assert groups is not None
    assert [item.external_group_id for item in groups] == ["codex", "A-CCMAX"]
    assert groups[0].description == "codex分组，（自营稳定）"
    assert groups[0].rate_multiplier == 0.08
    assert groups[1].rate_multiplier == 1.8


def test_sub2api_api_base_url_uses_configured_platform_base_url() -> None:
    assert (
        Sub2ApiStrategy.api_base_url(platform("https://example.com"))
        == "https://example.com/api/v1"
    )
    assert (
        Sub2ApiStrategy.api_base_url(platform("https://example.com/sub2/login"))
        == "https://example.com/sub2/api/v1"
    )
    assert (
        Sub2ApiStrategy.api_base_url(platform("https://example.com/sub2/api/v1"))
        == "https://example.com/sub2/api/v1"
    )


def test_sub2api_group_catalog_applies_user_rate_overrides() -> None:
    groups = Sub2ApiStrategy.parse_group_catalog_payload(
        [
            {
                "id": 7,
                "name": "codex",
                "description": "Codex 分组",
                "platform": "openai",
                "rate_multiplier": 0.2,
                "rpm_limit": 60,
            },
            {
                "id": 8,
                "name": "claude",
                "platform": "anthropic",
                "rate_multiplier": "0.5",
            },
        ],
        {"7": 0.12},
    )

    assert [item.external_group_id for item in groups] == ["7", "8"]
    assert groups[0].name == "codex"
    assert groups[0].rate_multiplier == 0.12
    assert groups[0].rpm_limit == 60
    assert "专属倍率覆盖: 0.2 -> 0.12" in (groups[0].description or "")
    assert groups[1].rate_multiplier == 0.5


def test_sub2api_fetch_account_balance_logs_in_and_reads_user_usage(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs["base_url"])
            self.headers = dict(kwargs.get("headers") or {})
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, path: str, json: dict):
            self.requests.append(("POST", path, json))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "success",
                    "data": {
                        "access_token": "token-123",
                        "user": {
                            "balance": 12.5,
                            "total_recharged": 20,
                        },
                    },
                },
                request=httpx.Request("POST", f"{self.base_url}{path}"),
            )

        async def get(self, path: str):
            self.requests.append(("GET", path, None))
            payloads = {
                "usage/dashboard/stats": {
                    "code": 0,
                    "message": "success",
                    "data": {"total_actual_cost": 7.5},
                },
                "keys?page=1&page_size=100": {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "items": [
                            {
                                "id": 101,
                                "name": "prod-key",
                                "group_id": 7,
                                "group": {"id": 7, "name": "codex"},
                                "quota_used": 2,
                                "quota": 10,
                            }
                        ]
                    },
                },
            }
            return httpx.Response(
                200,
                json=payloads[path],
                request=httpx.Request("GET", f"{self.base_url}{path}"),
            )

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        Sub2ApiStrategy().fetch_account_balance(
            SimpleNamespace(base_url="https://sub2.example.com"),
            SimpleNamespace(
                external_account_id="me",
                username="user@example.com",
                password_encrypted=encrypt_secret("secret"),
            ),
        )
    )

    assert result.error is None
    assert result.balance == 12.5
    assert result.quota_used == 7.5
    assert result.quota_limit == 20
    assert result.key_summaries == (
        {"id": "101", "name": "prod-key", "group_id": "7", "group_name": "codex"},
    )
