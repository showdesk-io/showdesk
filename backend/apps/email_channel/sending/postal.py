"""The `postal` sending domain provider: a server of a self-hosted Postal (v3).

Postal has no API to manage domains, so the operator runs the Postal domains
service (`deploy/postal-domains/`) on the Postal host, which adds, checks and
deletes the domains of one Postal server (`POSTAL_DOMAINS_API_URL`, with the
bearer token `POSTAL_DOMAINS_API_TOKEN`). A domain is created there already
verified (Showdesk proves the ownership itself) and gets its own DKIM key.

The records: SPF (Postal's include, merged), the domain's DKIM TXT, and the
return-path CNAME Postal's envelope sender uses. `check` has Postal check
them (Postal only signs with the domain's key once it found it, and only
uses the return path then), then reads the SPF and DKIM in the DNS itself.

What Postal does was read from its source (3.3): see
docs/plans/2026-11-08-postal-sending-provider-plan.md. The token travels in
the Authorization header only: it is never logged nor put in an error.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.organizations import dns_verification

from .manual import spf_record_error
from .providers import CheckStatus, DomainCheck, RegisteredDomain, SendingProviderError

logger = logging.getLogger(__name__)

# A Rails boot in Postal's container, plus Postal's own DNS check.
TIMEOUT_SECONDS = 60

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN_RE = re.compile(rf"^(?=.{{1,253}}$)(?:{_LABEL}\.)+{_LABEL}$")
_KINDS = ("spf", "dkim", "return_path")


class _HTTPError(SendingProviderError):
    """The service answered with an error status, and its error code if any."""

    def __init__(self, message: str, status_code: int, code: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code

    @property
    def not_found(self) -> bool:
        """The service says Postal has no such domain: not a 404 of a proxy
        in front of it, which says nothing about the domain."""
        return self.status_code == 404 and self.code == "not_found"


class PostalProvider:
    """The domains of one Postal server, through the Postal domains service."""

    removal_needed = True

    def __init__(self) -> None:
        url = (getattr(settings, "POSTAL_DOMAINS_API_URL", "") or "").strip()
        self.api_url = url.rstrip("/")
        self.token = (getattr(settings, "POSTAL_DOMAINS_API_TOKEN", "") or "").strip()
        if not (self.api_url and self.token):
            raise ImproperlyConfigured(
                "SENDING_DOMAIN_PROVIDER=postal needs POSTAL_DOMAINS_API_URL and "
                "POSTAL_DOMAINS_API_TOKEN."
            )

    def _call(self, method: str, path: str, json: dict | None = None) -> dict | None:
        """One call; any failure becomes a SendingProviderError."""
        try:
            response = requests.request(
                method,
                f"{self.api_url}{path}",
                headers={"Authorization": f"Bearer {self.token}"},
                json=json,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            # The exception's text may hold anything: only its type is logged.
            logger.warning(
                "Postal domains %s %s failed: %s", method, path, type(exc).__name__
            )
            raise SendingProviderError(
                "The sending service could not be reached."
            ) from None
        if response.status_code >= 400:
            logger.warning(
                "Postal domains %s %s answered %s: %s",
                method,
                path,
                response.status_code,
                response.text[:200].replace(self.token, "***"),
            )
            raise _HTTPError(
                f"The sending service answered {response.status_code}.",
                response.status_code,
                _error_code(response),
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            logger.warning("Postal domains %s %s: not a JSON object.", method, path)
            raise SendingProviderError("The sending service gave an unreadable answer.")
        return body

    def _domain(self, method: str, path: str, json: dict | None = None) -> dict:
        """A domain the service returns, with its id checked."""
        body = self._call(method, path, json)
        if not body or not _UUID_RE.match(str(body.get("id", ""))):
            logger.warning("Postal domains %s %s: no domain id.", method, path)
            raise SendingProviderError("The sending service gave an unreadable answer.")
        return body

    def _path(self, ref: str, action: str = "") -> str:
        if not _UUID_RE.match(ref):
            raise SendingProviderError("This domain's Postal id is invalid.")
        return f"/domains/{ref}{action}"

    def register(self, domain: str) -> RegisteredDomain:
        if not _DOMAIN_RE.match(domain):
            raise SendingProviderError("This domain name can't be sent to Postal.")
        # 201 created, 200 one the server already had: ours either way (the
        # server is Showdesk's only).
        body = self._domain("POST", "/domains", json={"name": domain})
        records = _records(body, domain)
        if not records:
            raise SendingProviderError("The sending service gave an unreadable answer.")
        return RegisteredDomain(ref=body["id"], records=records)

    def check(self, ref: str) -> DomainCheck:
        path = self._path(ref, "/check")
        try:
            body = self._domain("POST", path)
        except _HTTPError as exc:
            if exc.not_found:
                return DomainCheck(
                    CheckStatus.FAILED, "The sending service no longer has this domain."
                )
            raise
        domain = str(body.get("name", "")).strip().rstrip(".").lower()
        expected = _by_kind(body, domain)
        spf, dkim = expected.get("spf"), expected.get("dkim")
        if not (_DOMAIN_RE.match(domain) and spf and dkim):
            logger.warning("Postal domain %s: no SPF or DKIM record given.", ref)
            return DomainCheck(CheckStatus.UNKNOWN)
        records = _records(body, domain)

        spf_found = dns_verification.lookup_txt(domain)
        dkim_found = dns_verification.lookup_txt(dkim["name"])
        if spf_found is None or dkim_found is None:
            return DomainCheck(CheckStatus.UNKNOWN, "", records)

        status = body.get("status") if isinstance(body.get("status"), dict) else {}
        errors = []
        include = _spf_include(spf["value"])
        spf_error = spf_record_error(domain, spf_found, include)
        if spf_error:
            errors.append(spf_error)
        if [_compact(r) for r in dkim_found] != [_compact(dkim["value"])]:
            errors.append(
                f"DKIM: publish the TXT record {dkim['name']} exactly as shown."
            )
        elif status.get("dkim") != "OK":
            # Postal signs with the domain's key only once it found it.
            errors.append(
                "DKIM: the sending service hasn't seen the record yet"
                + _postal_error(status.get("dkim_error"))
            )
        if "return_path" in expected and status.get("return_path") != "OK":
            errors.append(
                "Return path: "
                + (
                    _text(status.get("return_path_error"))
                    or f"publish the CNAME record {expected['return_path']['name']}."
                )
            )
        if errors:
            return DomainCheck(CheckStatus.PENDING, " ".join(errors), records)
        return DomainCheck(CheckStatus.VERIFIED, "", records)

    def remove(self, ref: str) -> None:
        try:
            self._call("DELETE", self._path(ref))
        except _HTTPError as exc:
            if not exc.not_found:  # Else gone already.
                raise


def _error_code(response: requests.Response) -> str:
    """The service's `error` code, from a body that may not be its JSON."""
    try:
        body = response.json()
    except ValueError:
        return ""
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else ""


def _text(value: Any) -> str:
    return value.strip()[:200] if isinstance(value, str) else ""


def _postal_error(value: Any) -> str:
    text = _text(value)
    return f" ({text})." if text else "."


def _qualified(name: Any, domain: str) -> str:
    name = str(name).strip().rstrip(".").lower()
    if name in ("", "@"):
        return domain
    return name


def _by_kind(body: dict, domain: str) -> dict[str, dict[str, Any]]:
    """The service's records by kind, each with a type, a name and a value."""
    found: dict[str, dict[str, Any]] = {}
    records = body.get("records")
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict) or record.get("kind") not in _KINDS:
            continue
        value = record.get("value")
        if not (isinstance(value, str) and value.strip()):
            continue
        found.setdefault(
            record["kind"],
            {
                "type": "CNAME" if record["kind"] == "return_path" else "TXT",
                "name": _qualified(record.get("name"), domain),
                "value": value.strip().rstrip(".")
                if record["kind"] == "return_path"
                else value.strip(),
            },
        )
    return found


def _records(body: dict, domain: str) -> list[dict[str, Any]]:
    """The records to publish: SPF (merged into an existing one), DKIM, return path."""
    expected = _by_kind(body, domain)
    records = []
    for kind in _KINDS:
        if kind in expected:
            record = dict(expected[kind])
            if kind == "spf":
                record["merge"] = True
            records.append(record)
    return records


def _compact(record: str) -> str:
    """A DKIM record without whitespace nor a final `;`, as Postal compares it."""
    return re.sub(r"\s+", "", record).rstrip(";")


def _spf_include(value: str) -> str:
    """The include of the SPF record the service asks for."""
    for token in value.lower().split():
        if token.startswith("include:"):
            return token.removeprefix("include:").rstrip(".")
    return ""
