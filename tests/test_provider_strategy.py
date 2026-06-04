from types import SimpleNamespace

import httpx

from app.services.provider_strategy import YunjinNewApiSiteStrategy


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
