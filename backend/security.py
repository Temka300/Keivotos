"""Host and browser-origin checks for the local HTTP API."""

from __future__ import annotations

from urllib.parse import urlsplit


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _host_and_port(value: str, scheme: str) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(value if "://" in value else f"//{value}")
        host = (parsed.hostname or "").casefold()
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return None
    if not host:
        return None
    return host, port


def validate_local_browser_request(
    *,
    host_header: str,
    scheme: str,
    origin_header: str | None,
    fetch_site_header: str | None = None,
    lan_host: str | None = None,
) -> tuple[int, str] | None:
    """Reject inactive hosts and browser requests from another origin."""
    allowed_hosts = LOOPBACK_HOSTS | ({lan_host.casefold()} if lan_host else set())
    request_origin = _host_and_port(host_header, scheme)
    if request_origin is None or request_origin[0] not in allowed_hosts:
        detail = (
            "Keivotos accepts requests only through its active local addresses"
            if lan_host
            else "Keivotos accepts requests only through the local loopback address"
        )
        return 400, detail

    # Foreign subresources can omit Origin while still declaring that the
    # browser initiated them from another site.
    if fetch_site_header and fetch_site_header.casefold() not in {"same-origin", "none"}:
        return 403, "Cross-origin browser requests are not allowed"

    # Browsers omit Origin for ordinary navigation. Native tools and the bundled
    # frontend can also make same-machine requests without it.
    if not origin_header:
        return None

    try:
        parsed_origin = urlsplit(origin_header)
    except ValueError:
        return 403, "Cross-origin browser requests are not allowed"
    if parsed_origin.scheme not in {"http", "https"}:
        return 403, "Cross-origin browser requests are not allowed"

    browser_origin = _host_and_port(origin_header, parsed_origin.scheme)
    if browser_origin is None or browser_origin[0] not in allowed_hosts:
        return 403, "Cross-origin browser requests are not allowed"
    if parsed_origin.scheme != scheme or browser_origin != request_origin:
        return 403, "Cross-origin browser requests are not allowed"
    return None
