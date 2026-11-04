"""The `scaleway_tem` sending domain provider: Scaleway Transactional Email.

Domains are created in the project `SCW_TEM_PROJECT_ID` without autoconfig
(the customer's DNS zone isn't at Scaleway), and TEM gives the records to
publish: SPF, DKIM, and the MX and DMARC it recommends. TEM checks them
itself; `check` asks it for an immediate check and reads the outcome.

The secret key travels in the `X-Auth-Token` header only: it is never logged
nor put in an error message.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .providers import CheckStatus, DomainCheck, RegisteredDomain, SendingProviderError

logger = logging.getLogger(__name__)

API_URL = "https://api.scaleway.com/transactional-email/v1alpha1"
TIMEOUT_SECONDS = 10

# The records TEM gives, in the order they are shown, with their DNS type.
RECORD_TYPES = {"spf": "TXT", "dkim": "TXT", "mx": "MX", "dmarc": "TXT"}

_PENDING = {"unchecked", "pending", "autoconfiguring", "invalid"}
_FAILED = {"locked", "revoked"}


class _HTTPError(SendingProviderError):
    """TEM answered with an error status."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class ScalewayTEMProvider:
    """Domains registered in one Scaleway project through the TEM API."""

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
            return response.json()
        except ValueError:
            raise SendingProviderError(
                "Scaleway Transactional Email gave an unreadable answer."
            ) from None

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
                raise SendingProviderError(
                    f"{domain} is already registered with Scaleway Transactional Email."
                ) from None
            raise
        return RegisteredDomain(ref=created["id"], records=_records(created, domain))

    def check(self, ref: str) -> DomainCheck:
        found = self._call("GET", f"/{ref}")
        if found.get("status") not in _FAILED:
            found = self._call("POST", f"/{ref}/check", json={})
        status = found.get("status")
        if status == "checked":
            check_status = CheckStatus.VERIFIED
        elif status in _FAILED:
            check_status = CheckStatus.FAILED
        elif status in _PENDING:
            check_status = CheckStatus.PENDING
        else:
            # TEM's own "unknown", or a status this code doesn't know.
            return DomainCheck(CheckStatus.UNKNOWN)
        error = "" if check_status == CheckStatus.VERIFIED else found.get("last_error")
        return DomainCheck(
            check_status,
            error or "",
            _records(found, found.get("name", "")) or None,
        )

    def remove(self, ref: str) -> None:
        try:
            self._call("POST", f"/{ref}/revoke", json={})
        except _HTTPError as exc:
            if exc.status_code != 404:
                raise


def _records(found: dict[str, Any], domain: str) -> list[dict[str, str]]:
    """TEM's records as [{type, name, value}], names fully qualified."""
    records = found.get("records") or {}
    result = []
    for key, record_type in RECORD_TYPES.items():
        record = records.get(key)
        if not record or not record.get("value"):
            continue
        result.append(
            {
                "type": record_type,
                "name": _qualified(record.get("name", ""), domain),
                "value": record["value"],
            }
        )
    return result


def _qualified(name: str, domain: str) -> str:
    """TEM gives names relative to the domain ("", "_dmarc"), or sometimes not."""
    name = name.strip().rstrip(".").lower()
    if name in ("", "@") or name == domain:
        return domain
    if name.endswith(f".{domain}"):
        return name
    return f"{name}.{domain}"
