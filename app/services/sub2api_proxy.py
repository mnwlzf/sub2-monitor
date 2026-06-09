import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from app.core.config import Sub2APIDatabaseSettings
from app.services.sub2api_schedulable import normalize_base_url

logger = logging.getLogger(__name__)

SUPPORTED_PROXY_PROTOCOLS = {"http", "https", "socks5", "socks5h"}
SUB2API_PLATFORM_PROXY_SQL = """
SELECT
    a.id,
    p.protocol,
    p.host,
    p.port,
    p.username,
    p.password,
    CASE
        WHEN trim(trailing '/' FROM coalesce(a.credentials->>'base_url', '')) = trim(trailing '/' FROM %(base_url)s)
            THEN trim(trailing '/' FROM coalesce(a.credentials->>'base_url', ''))
        ELSE trim(trailing '/' FROM coalesce(a.extra->>'custom_base_url', ''))
    END AS matched_base_url
FROM accounts a
JOIN proxies p ON p.id = a.proxy_id
WHERE a.deleted_at IS NULL
  AND p.deleted_at IS NULL
  AND p.status = 'active'
  AND (
    trim(trailing '/' FROM coalesce(a.credentials->>'base_url', '')) = trim(trailing '/' FROM %(base_url)s)
    OR (
      coalesce(a.extra->>'custom_base_url_enabled', 'false') = 'true'
      AND trim(trailing '/' FROM coalesce(a.extra->>'custom_base_url', '')) = trim(trailing '/' FROM %(base_url)s)
    )
  )
ORDER BY a.id ASC
"""


@dataclass(frozen=True)
class Sub2APIAccountProxy:
    account_id: int
    proxy_url: str
    matched_base_url: str


def proxy_url_from_row(row: tuple[Any, ...]) -> str | None:
    protocol = str(row[0] or "").strip().lower()
    host = str(row[1] or "").strip()
    port = row[2]
    username = str(row[3] or "").strip()
    password = str(row[4] or "")
    if protocol not in SUPPORTED_PROXY_PROTOCOLS or not host or not port:
        return None

    auth = ""
    if username:
        auth = quote(username, safe="")
        if password:
            auth = f"{auth}:{quote(password, safe='')}"
        auth = f"{auth}@"
    return f"{protocol}://{auth}{host}:{int(port)}"


def masked_proxy_url(proxy_url: str | None) -> str | None:
    text = str(proxy_url or "").strip()
    if not text:
        return None
    parts = urlsplit(text)
    if not parts.scheme or not parts.hostname:
        return text

    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    auth = ""
    if parts.username:
        auth = quote(unquote(parts.username), safe="")
        if parts.password:
            auth = f"{auth}:<masked>"
        auth = f"{auth}@"
    return urlunsplit((parts.scheme, f"{auth}{host}{port}", parts.path, parts.query, parts.fragment))


def account_proxy_from_row(row: tuple[Any, ...]) -> Sub2APIAccountProxy | None:
    proxy_url = proxy_url_from_row(row[1:6])
    if not proxy_url:
        return None
    return Sub2APIAccountProxy(
        account_id=int(row[0]),
        proxy_url=proxy_url,
        matched_base_url=normalize_base_url(row[6]),
    )


def load_platform_proxy_urls(
    database: Sub2APIDatabaseSettings,
    base_url: str | None,
) -> list[str]:
    normalized_base_url = normalize_base_url(base_url)
    if not normalized_base_url or not database.is_configured:
        return []

    try:
        import psycopg
    except ImportError:
        logger.warning("sub2api account proxy skipped: psycopg is not installed")
        return []

    try:
        with psycopg.connect(
            database.postgresql_dsn(),
            connect_timeout=database.connect_timeout_seconds,
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cursor:
                cursor.execute(SUB2API_PLATFORM_PROXY_SQL, {"base_url": normalized_base_url})
                rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sub2api platform proxy lookup failed base_url=%s error=%s",
            normalized_base_url,
            exc,
        )
        return []

    proxies: list[str] = []
    for row in rows:
        proxy = account_proxy_from_row(row)
        if proxy is not None:
            proxies.append(proxy.proxy_url)
    return proxies
