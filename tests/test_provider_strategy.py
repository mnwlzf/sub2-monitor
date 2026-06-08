import asyncio
from types import SimpleNamespace

import httpx

import app.services.provider_strategy as provider_module
from app.core.security import encrypt_secret
from app.services.provider_strategy import NewApiStrategy, Sub2ApiStrategy, GenericNewApiSiteStrategy


def platform(base_url: str) -> SimpleNamespace:
    return SimpleNamespace(base_url=base_url)


def test_newapi_generic_site_url_keeps_subpath_deployment() -> None:
    assert (
        GenericNewApiSiteStrategy.site_url(platform("https://example.com/yunjin/login"))
        == "https://example.com/yunjin/"
    )


def test_newapi_generic_site_url_strips_page_and_api_suffixes() -> None:
    assert (
        GenericNewApiSiteStrategy.site_url(platform("https://example.com/yunjin/pricing"))
        == "https://example.com/yunjin/"
    )
    assert (
        GenericNewApiSiteStrategy.site_url(platform("https://example.com/yunjin/api"))
        == "https://example.com/yunjin/"
    )


def test_newapi_generic_site_url_root_domain_has_trailing_slash() -> None:
    assert (
        GenericNewApiSiteStrategy.site_url(platform("https://relayai.tech/login"))
        == "https://relayai.tech/"
    )


def test_newapi_generic_origin_ignores_subpath() -> None:
    assert (
        GenericNewApiSiteStrategy.site_origin(platform("https://example.com/yunjin/login"))
        == "https://example.com"
    )


def test_relative_endpoint_keeps_subpath_base_url() -> None:
    with httpx.Client(base_url="https://example.com/yunjin/") as client:
        request = client.build_request("GET", "api/pricing")

    assert str(request.url) == "https://example.com/yunjin/api/pricing"


def test_newapi_generic_group_catalog_parser_reads_desc_and_ratio() -> None:
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

    groups = GenericNewApiSiteStrategy.parse_group_catalog_payload(payload)

    assert groups is not None
    assert [item.external_group_id for item in groups] == ["codex", "A-CCMAX"]
    assert groups[0].description == "codex分组，（自营稳定）"
    assert groups[0].rate_multiplier == 0.08
    assert groups[1].rate_multiplier == 1.8


def test_newapi_group_catalog_fetches_self_groups_with_platform_token(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            if path == "api/user/self/groups":
                assert self.headers["Authorization"] == "Bearer token-123"
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "A-CCMAX(特价渠道)": {
                                "desc": "Claude MAX（满血，测试100%，特价不稳定）",
                                "ratio": 0.8,
                            },
                            "codex": {
                                "desc": "codex分组，（自营稳定）",
                                "ratio": 0.05,
                            },
                        },
                        "message": "",
                        "success": True,
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_group_catalog(
            SimpleNamespace(
                base_url="https://relayai.tech/",
                site_strategy="generic",
                api_key_encrypted=encrypt_secret("Bearer token-123"),
                auth_header_name="Authorization",
                auth_header_prefix="Bearer",
                account_monitors=[],
            )
        )
    )

    assert result is not None
    assert [item.name for item in result] == ["A-CCMAX(特价渠道)", "codex"]
    assert result[0].external_group_id == "A-CCMAX(特价渠道)"
    assert result[0].rate_multiplier == 0.8
    assert result[0].description == "Claude MAX（满血，测试100%，特价不稳定）"


def test_newapi_group_catalog_retries_with_cookie_when_access_token_is_rejected(monkeypatch) -> None:
    class StubAsyncClient:
        login_count = 0

        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            if path == "login":
                return httpx.Response(
                    200,
                    text="ok",
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/user/self/groups":
                if "Authorization" in self.headers:
                    assert self.headers["Authorization"] == "Bearer stale-token-123"
                    assert self.headers["Cookie"] == "session=session-token-123"
                    assert self.headers["New-Api-User"] == "647"
                    return httpx.Response(
                        200,
                        json={"success": False, "message": "invalid access token"},
                        request=httpx.Request("GET", f"{self.base_url}{path}"),
                    )
                assert self.headers["Cookie"] == "session=session-token-123"
                assert self.headers["New-Api-User"] == "647"
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "codex": {
                                "desc": "Codex group",
                                "ratio": 0.08,
                            },
                        },
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path == "api/user/login?turnstile=":
                StubAsyncClient.login_count += 1
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "",
                        "data": {"id": 647, "username": json["username"]},
                    },
                    headers={"Set-Cookie": "session=session-token-123; Path=/; HttpOnly"},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_group_catalog(
            SimpleNamespace(
                base_url="https://relayai.tech/",
                site_strategy="generic",
                api_key_encrypted=encrypt_secret("Bearer stale-token-123"),
                auth_header_name="Authorization",
                auth_header_prefix="Bearer",
                account_monitors=[
                    SimpleNamespace(
                        enabled=True,
                        external_account_id="user@example.com",
                        username="user@example.com",
                        password_encrypted=encrypt_secret("pw"),
                    ),
                ],
            )
        )
    )

    assert result is not None
    assert result[0].external_group_id == "codex"
    assert result[0].rate_multiplier == 0.08
    assert StubAsyncClient.login_count == 1


def test_newapi_group_catalog_missing_data_error_includes_response_summary(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            if path == "api/user/self/groups":
                return httpx.Response(
                    200,
                    text="<html>login</html>",
                    headers={"Content-Type": "text/html; charset=utf-8"},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    try:
        asyncio.run(
            NewApiStrategy().fetch_group_catalog(
                SimpleNamespace(
                    base_url="https://relayai.tech/",
                    site_strategy="generic",
                    api_key_encrypted=None,
                    auth_header_name="Authorization",
                    auth_header_prefix="Bearer",
                    account_monitors=[],
                )
            )
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected group catalog parse failure")

    assert "newapi group catalog response missing data" in message
    assert "status=200" in message
    assert "content_type=text/html" in message
    assert "<html>login</html>" in message


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
            if target == "api/token/":
                assert self.headers.get("Authorization") == "Bearer token-123"
                assert self.headers.get("New-Api-User") == "123"
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "items": [
                                {"id": 11, "name": "prod-key"},
                                {"id": 12, "name": "ops-key"},
                                {"id": 13, "name": "promo-key"},
                            ],
                            "total": 3,
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
            if target == "api/token/13":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "id": 13,
                            "name": "promo-key",
                            "group": "codex（特价分组-4）",
                        },
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if target.endswith("/api/account/123") or target == "api/account/123":
                assert headers == {"Authorization": "Bearer token-123", "New-Api-User": "123"}
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
        {
            "id": "13",
            "name": "promo-key",
            "group_id": "codex（特价分组-4）",
            "group_name": "codex（特价分组-4）",
        },
    )


def test_newapi_management_headers_normalize_authorization_and_user_id() -> None:
    headers = NewApiStrategy().management_headers(
        SimpleNamespace(
            api_key_encrypted=encrypt_secret("Bearer sk-test-123"),
            auth_header_name="X-Auth-Token",
            auth_header_prefix="Bearer",
            account_monitors=[
                SimpleNamespace(enabled=True, external_account_id="Bearer 456", username=None)
            ],
        )
    )

    assert headers["Authorization"] == "Bearer sk-test-123"
    assert "X-Auth-Token" not in headers
    assert headers["New-Api-User"] == "456"


def test_newapi_generic_fetch_account_balance_sends_authorization_header(monkeypatch) -> None:
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
            self.requests.append(("GET", path, headers))
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/status":
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"quota_per_unit": 500000}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/user/self":
                assert headers == {"Authorization": "Bearer login-token-123", "New-Api-User": "789"}
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"id": 789, "quota": 1000000, "used_quota": 250000}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/token/":
                assert headers == {"Authorization": "Bearer login-token-123", "New-Api-User": "789"}
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"items": [], "total": 0, "page_size": 100}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            self.requests.append(("POST", path, json))
            if path in {"api/user/login?turnstile=", "api/user/login"}:
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "id": 789,
                            "access_token": "login-token-123",
                        },
                    },
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        GenericNewApiSiteStrategy().fetch_account_balance(
            NewApiStrategy(),
            SimpleNamespace(
                base_url="https://newapi.example.com",
                api_key_encrypted=encrypt_secret("Bearer fallback-token"),
                auth_header_name="X-Auth-Token",
                auth_header_prefix="Bearer",
                account_monitors=[],
                site_strategy="yunjin",
            ),
            SimpleNamespace(username="user@example.com", password_encrypted=encrypt_secret("pw")),
        )
    )

    assert result.error is None
    assert result.balance == 2.0
    assert result.quota_used == 0.5


def test_newapi_generic_login_retries_after_rate_limit(monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    class StubAsyncClient:
        def __init__(self) -> None:
            self.post_calls = 0

        async def post(self, path: str, **kwargs):
            self.post_calls += 1
            if self.post_calls == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0.25"},
                    request=httpx.Request("POST", f"https://newapi.example.com/{path}"),
                )
            return httpx.Response(
                200,
                json={"success": True, "data": {"id": 789}},
                request=httpx.Request("POST", f"https://newapi.example.com/{path}"),
            )

    monkeypatch.setattr(provider_module.asyncio, "sleep", fake_sleep)
    strategy = GenericNewApiSiteStrategy()
    client = StubAsyncClient()

    response, endpoint = asyncio.run(
        strategy.post_login_with_rate_limit_retry(
            client,
            strategy.LOGIN_ENDPOINTS,
            json={"username": "user@example.com", "password": "pw"},
        )
    )

    assert response.status_code == 200
    assert endpoint == "api/user/login?turnstile="
    assert client.post_calls == 2
    assert sleep_calls == [0.25]


def test_newapi_management_login_candidates_throttle_same_site_accounts(monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def fake_login_for_account(self, platform, account):
        return {"New-Api-User": account.external_account_id}

    monkeypatch.setattr(provider_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        provider_module.NewApiStrategy,
        "login_management_headers_for_account",
        fake_login_for_account,
    )
    strategy = NewApiStrategy()
    platform = SimpleNamespace(
        base_url="https://newapi.example.com/yunjin/login",
        account_monitors=[
            SimpleNamespace(
                enabled=True,
                username="a@example.com",
                password_encrypted=encrypt_secret("pw"),
                external_account_id="101",
            ),
            SimpleNamespace(
                enabled=True,
                username="b@example.com",
                password_encrypted=encrypt_secret("pw"),
                external_account_id="102",
            ),
        ],
    )

    headers = asyncio.run(strategy.login_management_header_candidates(platform))

    assert headers == [{"New-Api-User": "101"}, {"New-Api-User": "102"}]
    assert sleep_calls == [strategy.ACCOUNT_LOGIN_SPACING_SECONDS]


def test_newapi_management_login_retries_after_rate_limit(monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})
            self.post_calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))

        async def post(self, path: str, **kwargs):
            self.post_calls += 1
            if self.post_calls == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0.25"},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            return httpx.Response(
                200,
                json={"success": True, "data": {"id": 789, "access_token": "token-789"}},
                request=httpx.Request("POST", f"{self.base_url}{path}"),
            )

    monkeypatch.setattr(provider_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    headers = asyncio.run(
        NewApiStrategy().login_management_headers_for_account(
            SimpleNamespace(base_url="https://newapi.example.com/yunjin/login"),
            SimpleNamespace(
                enabled=True,
                username="user@example.com",
                password_encrypted=encrypt_secret("pw"),
            ),
        )
    )

    assert headers == {"New-Api-User": "789", "Authorization": "Bearer token-789"}
    assert sleep_calls == [0.25]


def test_newapi_management_login_reuses_cached_headers(monkeypatch) -> None:
    class StubAsyncClient:
        post_calls = 0

        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))

        async def post(self, path: str, **kwargs):
            type(self).post_calls += 1
            return httpx.Response(
                200,
                json={"success": True, "data": {"id": 789, "access_token": "token-789"}},
                request=httpx.Request("POST", f"{self.base_url}{path}"),
            )

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    strategy = NewApiStrategy()
    platform = SimpleNamespace(base_url="https://newapi.example.com/yunjin/login")
    account = SimpleNamespace(
        enabled=True,
        username="user@example.com",
        password_encrypted=encrypt_secret("pw"),
    )

    first_headers = asyncio.run(strategy.login_management_headers_for_account(platform, account))
    second_headers = asyncio.run(strategy.login_management_headers_for_account(platform, account))

    assert first_headers == {"New-Api-User": "789", "Authorization": "Bearer token-789"}
    assert second_headers == first_headers
    assert StubAsyncClient.post_calls == 1


def test_newapi_management_login_uses_long_backoff_with_jitter(monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.post_calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))

        async def post(self, path: str, **kwargs):
            self.post_calls += 1
            if self.post_calls == 1:
                return httpx.Response(
                    429,
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            return httpx.Response(
                200,
                json={"success": True, "data": {"id": 789, "access_token": "token-789"}},
                request=httpx.Request("POST", f"{self.base_url}{path}"),
            )

    monkeypatch.setattr(provider_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(provider_module.random, "uniform", lambda start, end: 1.25)
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    headers = asyncio.run(
        NewApiStrategy().login_management_headers_for_account(
            SimpleNamespace(base_url="https://newapi.example.com/yunjin/login"),
            SimpleNamespace(
                enabled=True,
                username="user@example.com",
                password_encrypted=encrypt_secret("pw"),
            ),
        )
    )

    assert headers == {"New-Api-User": "789", "Authorization": "Bearer token-789"}
    assert sleep_calls == [6.25]


def test_newapi_channel_catalog_stops_logging_in_after_first_success(monkeypatch) -> None:
    login_accounts: list[str] = []
    catalog_headers: list[dict[str, str]] = []

    async def fake_login_for_account(self, platform, account):
        login_accounts.append(account.username)
        return {"New-Api-User": account.external_account_id}

    async def fake_fetch_with_headers(self, platform, headers):
        catalog_headers.append(dict(headers))
        return [
            provider_module.DiscoveredChannelRateResult(
                external_channel_id="11",
                name="prod-channel",
            )
        ]

    monkeypatch.setattr(
        provider_module.NewApiStrategy,
        "login_management_headers_for_account",
        fake_login_for_account,
    )
    monkeypatch.setattr(
        provider_module.NewApiStrategy,
        "fetch_channel_catalog_with_headers",
        fake_fetch_with_headers,
    )

    accounts = [
        SimpleNamespace(
            enabled=True,
            external_account_id=f"account-{100 + index}",
            username=f"user{index}@example.com",
            password_encrypted=encrypt_secret("pw"),
        )
        for index in range(5)
    ]

    result = asyncio.run(
        NewApiStrategy().fetch_channel_catalog(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                api_key_encrypted=None,
                auth_header_prefix="Bearer",
                account_monitors=accounts,
            )
        )
    )

    assert result is not None
    assert result[0].external_channel_id == "11"
    assert login_accounts == ["user0@example.com"]
    assert catalog_headers == [{"New-Api-User": "account-100"}]


def test_newapi_channel_catalog_logs_in_next_account_after_retryable_failure(monkeypatch) -> None:
    login_accounts: list[str] = []
    catalog_headers: list[dict[str, str]] = []

    async def fake_login_for_account(self, platform, account):
        login_accounts.append(account.username)
        return {"New-Api-User": account.external_account_id}

    async def fake_fetch_with_headers(self, platform, headers):
        catalog_headers.append(dict(headers))
        if headers["New-Api-User"] == "account-100":
            raise ValueError("insufficient privileges")
        return [
            provider_module.DiscoveredChannelRateResult(
                external_channel_id="11",
                name="prod-channel",
            )
        ]

    monkeypatch.setattr(
        provider_module.NewApiStrategy,
        "login_management_headers_for_account",
        fake_login_for_account,
    )
    monkeypatch.setattr(
        provider_module.NewApiStrategy,
        "fetch_channel_catalog_with_headers",
        fake_fetch_with_headers,
    )

    accounts = [
        SimpleNamespace(
            enabled=True,
            external_account_id=f"account-{100 + index}",
            username=f"user{index}@example.com",
            password_encrypted=encrypt_secret("pw"),
        )
        for index in range(5)
    ]

    result = asyncio.run(
        NewApiStrategy().fetch_channel_catalog(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                api_key_encrypted=None,
                auth_header_prefix="Bearer",
                account_monitors=accounts,
            )
        )
    )

    assert result is not None
    assert result[0].external_channel_id == "11"
    assert login_accounts == ["user0@example.com", "user1@example.com"]
    assert catalog_headers == [{"New-Api-User": "account-100"}, {"New-Api-User": "account-101"}]


def test_newapi_generic_fetch_account_balance_prefers_login_access_token(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})
            self.retry_count = 0

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
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/status":
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"quota_per_unit": 500000}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/user/self":
                if self.retry_count == 0:
                    self.retry_count += 1
                    assert headers == {"Authorization": "Bearer login-token-123", "New-Api-User": "789"}
                    return httpx.Response(
                        401,
                        text="Unauthorized, invalid access token",
                        request=httpx.Request("GET", f"{self.base_url}{path}"),
                    )
                assert headers == {"Authorization": "login-token-123", "New-Api-User": "789"}
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"id": 789, "quota": 1000000, "used_quota": 250000}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/token/":
                assert headers == {"Authorization": "login-token-123", "New-Api-User": "789"}
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"items": [], "total": 0, "page_size": 100}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path in {"api/user/login?turnstile=", "api/user/login"}:
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "id": 789,
                            "access_token": "login-token-123",
                        },
                    },
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        GenericNewApiSiteStrategy().fetch_account_balance(
            NewApiStrategy(),
            SimpleNamespace(
                base_url="https://newapi.example.com",
                api_key_encrypted=encrypt_secret("Bearer fallback-token"),
                auth_header_name="X-Auth-Token",
                auth_header_prefix="Bearer",
                account_monitors=[],
                site_strategy="yunjin",
            ),
            SimpleNamespace(username="user@example.com", password_encrypted=encrypt_secret("pw")),
        )
    )

    assert result.error is None
    assert result.balance == 2.0
    assert result.quota_used == 0.5


def test_newapi_generic_fetch_account_balance_uses_session_cookie_without_access_token(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

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
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/status":
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"quota_per_unit": 500000}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/user/self":
                assert headers == {"Cookie": "session=session-token-123", "New-Api-User": "647"}
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"id": 647, "quota": 1500000, "used_quota": 500000}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/token/":
                assert headers == {"Cookie": "session=session-token-123", "New-Api-User": "647"}
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "items": [
                                {"id": 811, "name": "111", "group": "codex（特价分组-1）"},
                            ],
                            "total": 1,
                            "page_size": 10,
                        },
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/token/811":
                assert headers == {"Cookie": "session=session-token-123", "New-Api-User": "647"}
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {"id": 811, "name": "111", "group": "codex（特价分组-1）"},
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path == "api/user/login?turnstile=":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "",
                        "data": {
                            "display_name": "user@example.com",
                            "group": "default",
                            "id": 647,
                            "role": 1,
                            "status": 1,
                            "username": "user@example.com",
                        },
                    },
                    headers={
                        "Set-Cookie": (
                            "session=session-token-123; Path=/; Expires=Mon, 06 Jul 2026 "
                            "04:48:25 GMT; Max-Age=2592000; HttpOnly; SameSite=Strict"
                        ),
                    },
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_account_balance(
            SimpleNamespace(
                base_url="https://relayai.tech",
                api_key_encrypted=encrypt_secret("Bearer invalid-management-token"),
                auth_header_name="X-Auth-Token",
                auth_header_prefix="Bearer",
                account_monitors=[],
                site_strategy="yunjin",
            ),
            SimpleNamespace(username="user@example.com", password_encrypted=encrypt_secret("pw")),
        )
    )

    assert result.error is None
    assert result.balance == 3.0
    assert result.quota_used == 1.0
    assert result.key_summaries == (
        {
            "id": "811",
            "name": "111",
            "group_id": "codex（特价分组-1）",
            "group_name": "codex（特价分组-1）",
        },
    )


def test_newapi_generic_fetch_account_balance_uses_user_session_when_password_is_configured(
    monkeypatch,
) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

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
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/status":
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"quota_per_unit": 500000}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/user/self":
                assert headers == {"Cookie": "session=session-token-123", "New-Api-User": "647"}
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"id": 647, "quota": 1500000, "used_quota": 500000}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/token/":
                assert headers == {"Cookie": "session=session-token-123", "New-Api-User": "647"}
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "items": [
                                {"id": 811, "name": "111", "group": "codex（特价分组-1）"},
                            ],
                            "total": 1,
                            "page_size": 10,
                        },
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/token/811":
                assert headers == {"Cookie": "session=session-token-123", "New-Api-User": "647"}
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {"id": 811, "name": "111", "group": "codex（特价分组-1）"},
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path == "api/user/login?turnstile=":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "",
                        "data": {"id": 647, "username": "user@example.com"},
                    },
                    headers={"Set-Cookie": "session=session-token-123; Path=/; HttpOnly; SameSite=Strict"},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_account_balance(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                site_strategy="generic",
                api_key_encrypted=None,
                auth_header_name="X-Auth-Token",
                auth_header_prefix="Bearer",
                account_monitors=[],
            ),
            SimpleNamespace(username="user@example.com", password_encrypted=encrypt_secret("pw")),
        )
    )

    assert result.error is None
    assert result.balance == 3.0
    assert result.quota_used == 1.0
    assert result.key_summaries == (
        {
            "id": "811",
            "name": "111",
            "group_id": "codex（特价分组-1）",
            "group_name": "codex（特价分组-1）",
        },
    )


def test_newapi_generic_fetch_group_rate_sends_management_headers(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str, headers: dict | None = None):
            if path == "api/pricing":
                assert self.headers.get("Authorization") == "Bearer token-123"
                assert self.headers.get("New-Api-User") == "789"
                assert headers is None
                return httpx.Response(
                    200,
                    json={"group_ratio": {"codex": 0.08}},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        GenericNewApiSiteStrategy().fetch_group_rate(
            NewApiStrategy(),
            SimpleNamespace(
                base_url="https://newapi.example.com",
                api_key_encrypted=encrypt_secret("Bearer token-123"),
                auth_header_name="X-Auth-Token",
                auth_header_prefix="Bearer",
                account_monitors=[SimpleNamespace(enabled=True, external_account_id="789", username=None)],
                site_strategy="yunjin",
            ),
            SimpleNamespace(external_group_id="codex", name="codex", enabled=True),
        )
    )

    assert result.error is None
    assert result.rate_multiplier == 0.08


def test_newapi_generic_account_balance_uses_management_headers(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str, params: dict | None = None, headers: dict | None = None):
            self.requests.append(("GET", path, params))
            target = path
            if target.startswith("https://"):
                target = target.split("https://newapi.example.com/", 1)[-1]
            if path == "api/token/":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "items": [
                                {"id": 11, "name": "prod-key"},
                            ],
                            "total": 1,
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
            if target == "api/account/123":
                assert headers == {"Authorization": "Bearer token-123", "New-Api-User": "123"}
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
                auth_header_name="X-Auth-Token",
                auth_header_prefix="Bearer",
                account_monitors=[SimpleNamespace(enabled=True, external_account_id="123", username=None)],
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


def test_newapi_channel_catalog_uses_login_user_id_when_account_id_missing(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/ratio_sync/channels":
                assert self.headers == {
                    "Cookie": "session=session-token-123",
                    "New-Api-User": "647",
                }
                return httpx.Response(
                    200,
                    json={"success": True, "data": [{"id": 11, "name": "prod-channel"}]},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/channel/":
                assert self.headers["New-Api-User"] == "647"
                return httpx.Response(
                    200,
                    json={"success": True, "data": [{"id": 11, "name": "prod-channel"}]},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path == "api/user/login?turnstile=":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "display_name": "2696775653@qq.com",
                            "group": "default",
                            "id": 647,
                            "role": 1,
                            "status": 1,
                            "username": "2696775653@qq.com",
                        },
                        "message": "",
                        "success": True,
                    },
                    headers={"Set-Cookie": "session=session-token-123; Path=/; HttpOnly; SameSite=Strict"},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            if path == "api/ratio_sync/fetch":
                assert self.headers["New-Api-User"] == "647"
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"11": {"gpt-4o": 1.0}}},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_channel_catalog(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                site_strategy="generic",
                api_key_encrypted=encrypt_secret("Bearer token-123"),
                auth_header_name="Authorization",
                auth_header_prefix="Bearer",
                account_monitors=[
                    SimpleNamespace(
                        enabled=True,
                        external_account_id="2696775653@qq.com",
                        username="2696775653@qq.com",
                        password_encrypted=encrypt_secret("pw"),
                    ),
                ],
            )
        )
    )

    assert result is not None
    assert result[0].external_channel_id == "11"


def test_newapi_channel_catalog_works_without_platform_access_token(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/ratio_sync/channels":
                assert self.headers == {
                    "Cookie": "session=session-token-123",
                    "New-Api-User": "647",
                }
                return httpx.Response(
                    200,
                    json={"success": True, "data": [{"id": 11, "name": "prod-channel"}]},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/channel/":
                assert self.headers["New-Api-User"] == "647"
                return httpx.Response(
                    200,
                    json={"success": True, "data": [{"id": 11, "name": "prod-channel"}]},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path == "api/user/login?turnstile=":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "",
                        "data": {"id": 647, "username": "user@example.com"},
                    },
                    headers={"Set-Cookie": "session=session-token-123; Path=/; HttpOnly; SameSite=Strict"},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            if path == "api/ratio_sync/fetch":
                assert self.headers["New-Api-User"] == "647"
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"11": {"gpt-4o": 1.0}}},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_channel_catalog(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                site_strategy="generic",
                api_key_encrypted=None,
                auth_header_name="Authorization",
                auth_header_prefix="Bearer",
                account_monitors=[
                    SimpleNamespace(
                        enabled=True,
                        external_account_id="user@example.com",
                        username="user@example.com",
                        password_encrypted=encrypt_secret("pw"),
                    ),
                ],
            )
        )
    )

    assert result is not None
    assert result[0].external_channel_id == "11"


def test_newapi_channel_catalog_falls_back_when_platform_token_invalid(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})
            self.retry_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/ratio_sync/channels":
                if self.retry_count == 0:
                    self.retry_count += 1
                    assert self.headers == {
                        "Authorization": "Bearer invalid-token-123",
                        "Cookie": "session=session-token-123",
                        "New-Api-User": "647",
                    }
                    return httpx.Response(
                        401,
                        text="Unauthorized, invalid access token",
                        request=httpx.Request("GET", f"{self.base_url}{path}"),
                    )
                assert self.headers == {
                    "Cookie": "session=session-token-123",
                    "New-Api-User": "647",
                }
                return httpx.Response(
                    200,
                    json={"success": True, "data": [{"id": 11, "name": "prod-channel"}]},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            if path == "api/channel/":
                assert self.headers["New-Api-User"] == "647"
                return httpx.Response(
                    200,
                    json={"success": True, "data": [{"id": 11, "name": "prod-channel"}]},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path == "api/user/login?turnstile=":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "",
                        "data": {
                            "id": 647,
                            "username": "user@example.com",
                            "access_token": "invalid-token-123",
                        },
                    },
                    headers={"Set-Cookie": "session=session-token-123; Path=/; HttpOnly; SameSite=Strict"},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            if path == "api/ratio_sync/fetch":
                assert self.headers == {
                    "Cookie": "session=session-token-123",
                    "New-Api-User": "647",
                }
                return httpx.Response(
                    200,
                    json={"success": True, "data": {"11": {"gpt-4o": 1.0}}},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_channel_catalog(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                site_strategy="generic",
                api_key_encrypted=encrypt_secret("Bearer invalid-token-123"),
                auth_header_name="Authorization",
                auth_header_prefix="Bearer",
                account_monitors=[
                    SimpleNamespace(
                        enabled=True,
                        external_account_id="user@example.com",
                        username="user@example.com",
                        password_encrypted=encrypt_secret("pw"),
                    ),
                ],
            )
        )
    )

    assert result is not None
    assert result[0].external_channel_id == "11"


def test_newapi_channel_catalog_skips_when_all_login_accounts_lack_privileges(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str):
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/ratio_sync/channels":
                assert self.headers["New-Api-User"] in {"686", "647"}
                return httpx.Response(
                    200,
                    json={"success": False, "message": "Unauthorized, insufficient privileges"},
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path == "api/user/login?turnstile=":
                user_id = 686 if json["username"] == "first@example.com" else 647
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "",
                        "data": {"id": user_id, "username": json["username"]},
                    },
                    headers={"Set-Cookie": f"session=session-token-{user_id}; Path=/; HttpOnly; SameSite=Strict"},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_channel_catalog(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                site_strategy="generic",
                api_key_encrypted=None,
                auth_header_name="Authorization",
                auth_header_prefix="Bearer",
                account_monitors=[
                    SimpleNamespace(
                        enabled=True,
                        external_account_id="first@example.com",
                        username="first@example.com",
                        password_encrypted=encrypt_secret("pw"),
                    ),
                    SimpleNamespace(
                        enabled=True,
                        external_account_id="second@example.com",
                        username="second@example.com",
                        password_encrypted=encrypt_secret("pw"),
                    ),
                ],
            )
        )
    )

    assert result is None


def test_generic_newapi_group_catalog_uses_login_session(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.base_url = str(kwargs.get("base_url") or "")
            self.headers = dict(kwargs.get("headers") or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path: str, headers: dict | None = None):
            if path == "login":
                return httpx.Response(200, text="ok", request=httpx.Request("GET", f"{self.base_url}{path}"))
            if path == "api/user/self/groups":
                assert headers is None
                assert self.headers["Cookie"] == "session=session-token-123"
                assert self.headers["New-Api-User"] == "647"
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "",
                        "data": {
                            "codex": {
                                "desc": "Codex group",
                                "ratio": 0.08,
                                "rpm_limit": 120,
                            },
                        },
                    },
                    request=httpx.Request("GET", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

        async def post(self, path: str, json: dict):
            if path == "api/user/login?turnstile=":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "",
                        "data": {"id": 647, "username": "user@example.com"},
                    },
                    headers={"Set-Cookie": "session=session-token-123; Path=/; HttpOnly; SameSite=Strict"},
                    request=httpx.Request("POST", f"{self.base_url}{path}"),
                )
            raise AssertionError(path)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", StubAsyncClient)

    result = asyncio.run(
        NewApiStrategy().fetch_group_catalog(
            SimpleNamespace(
                base_url="https://newapi.example.com",
                site_strategy="generic",
                api_key_encrypted=None,
                auth_header_name="Authorization",
                auth_header_prefix="Bearer",
                account_monitors=[
                    SimpleNamespace(
                        enabled=True,
                        username="user@example.com",
                        password_encrypted=encrypt_secret("pw"),
                    ),
                ],
            )
        )
    )

    assert result is not None
    assert result[0].external_group_id == "codex"
    assert result[0].description == "Codex group"
    assert result[0].rate_multiplier == 0.08
    assert result[0].rpm_limit == 120


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

