"""The `scaleway_tem` sending domain provider: Scaleway Transactional Email.

Domains are created in the project `SCW_TEM_PROJECT_ID` without autoconfig
(the customer's DNS zone isn't at Scaleway), and TEM gives the records to
publish: SPF, DKIM, and the DMARC it recommends. TEM's MX is left out: it
points to a blackhole meant for send-only domains, and ours receive mail at
the support address. TEM checks the records itself; `check` reads the
outcome of its last check and asks for the next one.

The secret key travels in the `X-Auth-Token` header only: it is never logged
nor put in an error message.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .providers import (
    AlreadyRegisteredError,
    CheckStatus,
    DomainCheck,
    RegisteredDomain,
    SendingProviderError,
)

logger = logging.getLogger(__name__)

API_URL = "https://api.scaleway.com/transactional-email/v1alpha1"
TIMEOUT_SECONDS = 10

# The records shown, in this order, with their DNS type. `merge`: a domain
# has at most one such record, so the value goes into an existing one.
RECORD_TYPES = {"spf": "TXT", "dkim": "TXT", "dmarc": "TXT"}
MERGED_RECORDS = {"spf", "dmarc"}

# TEM's domain ids are UUIDs; anything else must not reach a URL.
_REF_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")

_PENDING = {"unchecked", "pending", "autoconfiguring", "invalid"}
_FAILED = {"locked", "revoked"}


class _HTTPError(SendingProviderError):
    """TEM answered with an error status."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class ScalewayTEMProvider:
    """Domains registered in one Scaleway project through the TEM API."""

    removal_needed = True

    def __init__(self) -> None:
        self.secret_key = settings.SCW_TEM_SECRET_KEY.strip()
        self.project_id = settings.SCW_TEM_PROJECT_ID.strip()
        self.region = settings.SCW_TEM_REGION.strip() or "fr-par"
        if not (self.secret_key and self.project_id):
            raise ImproperlyConfigured(
                "SENDING_DOMAIN_PROVIDER=scaleway_tem needs SCW_TEM_SECRET_KEY "
                "and SCW_TEM_PROJECT_ID."
            )

    def _call(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        """One API call; any failure becomes a SendingProviderError."""
        url = f"{API_URL}/regions/{self.region}/domains{path}"
        try:
            response = requests.request(
                method,
                url,
                headers={"X-Auth-Token": self.secret_key},
                json=json,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Scaleway TEM %s %s failed: %s", method, path, type(exc).__name__
            )
            raise SendingProviderError(
                "Scaleway Transactional Email could not be reached."
            ) from None
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            detail = body.get("message", "") if isinstance(body, dict) else ""
            logger.warning(
                "Scaleway TEM %s %s answered %s: %s",
                method,
                path,
                response.status_code,
                detail,
            )
            raise _HTTPError(
                f"Scaleway Transactional Email answered {response.status_code}"
                + (f": {detail}" if detail else "."),
                response.status_code,
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            logger.warning(
                "Scaleway TEM %s %s gave an answer that isn't a JSON object.",
                method,
                path,
            )
            raise SendingProviderError(
                "Scaleway Transactional Email gave an unreadable answer."
            )
        return body

    def _domain_path(self, ref: str, action: str = "") -> str:
        """The path of one domain, from a ref that must look like TEM's id."""
        if not _REF_RE.match(ref):
            raise SendingProviderError(
                "This domain's Scaleway Transactional Email id is invalid."
            )
        return f"/{ref}{action}"

    def register(self, domain: str) -> RegisteredDomain:
        try:
            created = self._call(
                "POST",
                "",
                json={
                    "project_id": self.project_id,
                    "domain_name": domain,
                    "autoconfig": False,
                },
            )
        except _HTTPError as exc:
            if exc.status_code == 409:
                raise AlreadyRegisteredError(
                    f"{domain} is already registered with Scaleway Transactional Email."
                ) from None
            raise
        ref = created.get("id")
        if not isinstance(ref, str) or not ref:
            logger.warning("Scaleway TEM created %s without giving its id.", domain)
            raise SendingProviderError(
                "Scaleway Transactional Email gave an unreadable answer."
            )
        return RegisteredDomain(ref=ref, records=_records(created, domain))

    def check(self, ref: str) -> DomainCheck:
        # The outcome is TEM's last real check. Asking for a new one answers
        # before it has run, so it only serves the next call.
        found = self._call("GET", self._domain_path(ref))
        status = found.get("status")
        if status not in _FAILED:
            try:
                self._call("POST", self._domain_path(ref, "/check"), json={})
            except SendingProviderError as exc:
                logger.warning(
                    "Scaleway TEM: could not ask for a check of %s: %s", ref, exc
                )
        if status == "checked":
            check_status = CheckStatus.VERIFIED
        elif status in _FAILED:
            check_status = CheckStatus.FAILED
        elif status in _PENDING:
            check_status = CheckStatus.PENDING
        else:
            # TEM's own "unknown", or a status this code doesn't know.
            return DomainCheck(CheckStatus.UNKNOWN)
        error = found.get("last_error")
        if check_status == CheckStatus.VERIFIED or not isinstance(error, str):
            error = ""
        name = found.get("name")
        records = _records(found, name) if isinstance(name, str) and name else []
        return DomainCheck(check_status, error, records or None)

    def remove(self, ref: str) -> None:
        try:
            self._call("POST", self._domain_path(ref, "/revoke"), json={})
        except _HTTPError as exc:
            # 404: already gone; 409: already revoked.
            if exc.status_code not in (404, 409):
                raise


def _records(found: dict[str, Any], domain: str) -> list[dict[str, Any]]:
    """TEM's records as [{type, name, value, merge?}], names fully qualified."""
    records = found.get("records")
    if not isinstance(records, dict):
        return []
    result = []
    for key, record_type in RECORD_TYPES.items():
        record = records.get(key)
        if not isinstance(record, dict):
            continue
        name, value = record.get("name"), record.get("value")
        # "" is the domain itself; no name at all can't be published.
        if not isinstance(name, str) or not isinstance(value, str) or not value:
            continue
        entry: dict[str, Any] = {
            "type": record_type,
            "name": _qualified(name, domain),
            "value": value,
        }
        if key in MERGED_RECORDS:
            entry["merge"] = True
        result.append(entry)
    return result


def _qualified(name: str, domain: str) -> str:
    """TEM gives names relative to the domain ("", "_dmarc"), or sometimes not."""
    name = name.strip().rstrip(".").lower()
    if name in ("", "@") or name == domain:
        return domain
    if name.endswith(f".{domain}"):
        return name
    return f"{name}.{domain}"
