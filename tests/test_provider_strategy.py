import asyncio
from types import SimpleNamespace

import httpx

import app.services.provider_strategy as provider_module
from app.core.security import encrypt_secret
from app.services.provider_strategy import NewApiStrategy, Sub2ApiStrategy, YunjinNewApiSiteStrategy


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


def test_sub2api_key_group_catalog_reads_key_group_bindings() -> None:
    groups = Sub2ApiStrategy.parse_key_group_catalog(
        {
            "items": [
                {
                    "id": 101,
                    "name": "prod-key",
                    "group_id": 7,
                    "group": {"id": 7, "name": "codex"},
                },
                {
                    "id": 102,
                    "name": "no-group",
                    "group_id": None,
                },
            ]
        }
    )

    assert len(groups) == 1
    assert groups[0].external_group_id == "7"
    assert groups[0].name == "codex"


def test_newapi_channel_rate_parser_reads_official_ratio_sync_shape() -> None:
    channels_payload = {
        "success": True,
        "data": [
            {
                "id": 1,
                "name": "OpenAI Official",
                "base_url": "https://api.openai.com",
                "status": 1,
                "type": 1,
            }
        ],
    }
    admin_channels_payload = {
        "success": True,
        "data": {
            "items": [
                {
                    "id": 1,
                    "name": "OpenAI Official",
                    "models": "gpt-4o,gpt-4o-mini",
                    "group": "default,paid",
                }
            ]
        },
    }
    ratio_payload = {
        "success": True,
        "data": {
            "differences": {
                "gpt-4o": {
                    "model_ratio": {
                        "current": 1,
                        "upstreams": {"OpenAI Official(1)": 2},
                    }
                },
                "gpt-4o-mini": {
                    "model_ratio": {
                        "current": 3,
                        "upstreams": {"OpenAI Official(1)": "same"},
                    }
                },
            }
        },
    }

    channels = NewApiStrategy.parse_channel_rate_results(
        channels_payload,
        ratio_payload=ratio_payload,
        admin_channels_payload=admin_channels_payload,
    )

    assert len(channels) == 1
    assert channels[0].external_channel_id == "1"
    assert channels[0].name == "OpenAI Official"
    assert channels[0].base_url == "https://api.openai.com"
    assert channels[0].status == "启用"
    assert channels[0].rate_multiplier == 2.5
    assert channels[0].model_rates == {"gpt-4o": 2.0, "gpt-4o-mini": 3.0}
    assert "分组: default, paid" in (channels[0].description or "")


def test_newapi_fetch_account_balance_reads_key_summaries(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(
            self,
            path: str,
            params: dict | None = None,
            headers: dict | None = None,
        ):
            self.requests.append(("GET", path, params))
            target = path
            if target.startswith("https://"):
                target = target.split("https://newapi.example.com/", 1)[-1]
            if path == "api/token/":
                assert self.headers.get("Authorization") == "token-123"
                assert self.headers.get("New-Api-User") == "123"
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "items": [
                                {"id": 11, "name": "prod-key"},
                                {"id": 12, "name": "ops-key"},
                            ],
                            "total": 2,
                            "page_size": 100,
                        },
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if target == "api/token/11":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {"id": 11, "name": "prod-key", "group": {"id": 7, "name": "codex"}},
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if target == "api/token/12":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {"id": 12, "name": "ops-key", "group_id": 9, "group_name": "ops"},
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if target.endswith("/api/account/123") or target == "api/account/123":
                return httpx.Response(
                    200,
                    json={"balance": 12.5, "used_quota": 3.5, "quota": 20},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_account_balance(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                site_strategy="generic",
                api_key_encrypted=encrypt_secret("Bearer token-123"),
                auth_header_name="Authorization",
                auth_header_prefix="Bearer",
                account_monitors=[
                    SimpleNamespace(enabled=True, external_account_id="123", username="Bearer 123")
                ],
            ),
            SimpleNamespace(
                external_account_id="123",
                username=None,
                password_encrypted=None,
                enabled=True,
            ),
        )
    )

    assert result.error is None
    assert result.balance == 12.5
    assert result.quota_used == 3.5
    assert result.quota_limit == 20
    assert result.key_summaries == (
        {"id": "11", "name": "prod-key", "group_id": "7", "group_name": "codex"},
        {"id": "12", "name": "ops-key", "group_id": "9", "group_name": "ops"},
    )


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
