"""DNS TXT lookups for domain verification.

Thin wrappers around `dns.resolver` so callers (verify endpoint, Celery
poller, services module) get a uniform "list of strings" view and never
need to handle resolver exceptions.

Tests should patch the public functions in this module rather than
reaching into `dns.resolver` directly. That way the boundary stays
stable if we ever swap the lib.
"""

from __future__ import annotations

import logging

import dns.exception
import dns.resolver

logger = logging.getLogger(__name__)

# Per-query timeout. Synchronous endpoints (POST /verify/) hold an HTTP
# worker for the duration, so this must stay small.
DEFAULT_TIMEOUT_SECONDS = 5.0


def lookup_txt(
    name: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> list[str] | None:
    """Return TXT record values for `name`, joined per record, or None if unsure.

    [] means the name has no TXT record (NXDOMAIN, NoAnswer). None means the
    lookup couldn't conclude (timeout, no nameserver answering, any other
    resolver error): callers that would undo something on a missing record
    must change nothing then. Each TXT record is decoded from its chunked
    binary representation into a single string (per RFC 1035 a TXT record
    can hold multiple <=255-byte strings concatenated). CNAMEs are followed.
    """
    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        answer = resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.Timeout, dns.resolver.NoNameservers) as exc:
        logger.warning("DNS lookup failed for %s: %s", name, exc)
        return None
    except dns.exception.DNSException as exc:  # pragma: no cover - defensive
        logger.warning("DNS lookup error for %s: %s", name, exc)
        return None

    records: list[str] = []
    for rdata in answer:
        # rdata.strings is a tuple of bytes objects.
        records.append(b"".join(rdata.strings).decode("utf-8", errors="replace"))
    return records


def query_txt_records(
    name: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> list[str]:
    """Return TXT record values for `name`; [] whenever none could be read.

    For the ownership challenge, where an inconclusive lookup is simply
    "not found yet". We never raise to the caller.
    """
    return lookup_txt(name, timeout=timeout) or []


def verify_domain_dns(domain_obj) -> bool:
    """Return True iff the org's TXT challenge is currently published.

    The expected record format is `showdesk-verification=<token>` placed
    on `_showdesk.<domain>`. Any other TXT records present at the same
    name are ignored.
    """
    if not domain_obj.verification_token:
        return False
    expected = domain_obj.txt_record_value
    records = query_txt_records(domain_obj.txt_record_name)
    return expected in records
