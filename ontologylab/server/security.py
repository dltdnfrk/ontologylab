"""Local-only hardening for the ontologylab web layer.

The server binds to loopback and has no auth by design (single local user).
That leaves two browser-reachable attack paths, because a web page the user
visits can still issue requests to ``127.0.0.1``:

* **DNS rebinding** — an attacker domain rebinds to 127.0.0.1, becomes
  same-origin, and reads the whole knowledge graph. Defeated by pinning the
  ``Host`` header to a loopback name: the browser still sends the attacker's
  hostname, so a rebound request is rejected before it reaches a handler.
* **Cross-site request forgery** — a page at ``evil.com`` POSTs to a local
  mutating endpoint (``/api/collect`` can pull local files into the KG). The
  browser labels such a request cross-site; we reject state-changing methods
  that are not same-origin, while still allowing non-browser clients (curl,
  the CLI, MCP) that send neither ``Origin`` nor ``Sec-Fetch-Site``.

Both checks are pure functions here so they can be unit-tested without a live
server; ``app.py`` wraps them in a single middleware.
"""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

# Extra hostnames (beyond loopback) that the Host-header guard should accept,
# as a comma-separated env var. Loopback is always trusted; this exists for the
# reverse-proxy case (the app fronted on a custom hostname) and for tests,
# which drive the ASGI app under the synthetic host "testserver".
_ALLOWED_HOSTS_ENV = "ONTOLOGYLAB_ALLOWED_HOSTS"

# Methods that never mutate state: exempt from the CSRF (cross-site) check.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# ``Sec-Fetch-Site`` values a browser sends for requests we trust: the local
# UI's own calls ("same-origin") and direct navigation / address-bar hits
# ("none"). "same-site" and "cross-site" are refused for mutations.
_TRUSTED_FETCH_SITES = frozenset({"same-origin", "none"})


def hostname_from_host_header(value: str | None) -> str | None:
    """Extract the bare hostname from a ``Host`` header, dropping any port.

    Handles bracketed IPv6 literals (``[::1]:8765``) and the common
    ``host:port`` form. Returns ``None`` for an empty/malformed header.
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith("["):  # [::1] or [::1]:8765
        end = value.find("]")
        if end == -1:
            return None
        return value[1:end]
    # Bare "host" (0 colons) or "host:port" (exactly 1 colon). More than one
    # colon without brackets is an unbracketed IPv6 literal — malformed as a
    # Host header, so treat it as untrusted.
    if value.count(":") == 0:
        return value
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return None


def is_local_hostname(hostname: str | None) -> bool:
    """True iff ``hostname`` is ``localhost`` or a loopback IP literal."""
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def host_header_is_local(host_header: str | None) -> bool:
    """True iff the ``Host`` header names loopback (blocks DNS rebinding)."""
    return is_local_hostname(hostname_from_host_header(host_header))


def extra_allowed_hosts() -> frozenset[str]:
    """Lowercased extra hostnames trusted via ``ONTOLOGYLAB_ALLOWED_HOSTS``.

    Empty unless configured. Read per call so tests and reverse-proxy setups
    can set it without rebuilding the app.
    """
    raw = os.environ.get(_ALLOWED_HOSTS_ENV, "")
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def host_header_is_trusted(host_header: str | None) -> bool:
    """True iff ``Host`` is loopback or an explicitly allowlisted hostname.

    Loopback is always trusted; anything else must be named in
    ``ONTOLOGYLAB_ALLOWED_HOSTS``. This is the check the middleware runs.
    """
    if host_header_is_local(host_header):
        return True
    hostname = hostname_from_host_header(host_header)
    return hostname is not None and hostname.lower() in extra_allowed_hosts()


def is_cross_site_state_change(
    method: str,
    sec_fetch_site: str | None,
    origin: str | None,
) -> bool:
    """Decide whether a state-changing request looks cross-site (a CSRF risk).

    Returns ``True`` only when the request should be refused. The logic favors
    not breaking legitimate non-browser callers:

    * Safe (read-only) methods are never cross-site risks.
    * If the browser sent ``Sec-Fetch-Site`` (all current browsers do), trust
      only ``same-origin`` / ``none``; refuse ``same-site`` / ``cross-site``.
    * Otherwise, if only ``Origin`` is present, refuse it when its host is not
      loopback.
    * With neither header (curl, the CLI, MCP clients), allow — these are not
      browsers and carry no ambient cookies to forge against.
    """
    if method.upper() in SAFE_METHODS:
        return False
    if sec_fetch_site is not None:
        return sec_fetch_site.lower() not in _TRUSTED_FETCH_SITES
    if origin is not None:
        return not is_local_hostname(urlparse(origin).hostname)
    return False
