"""The `mailjet` sending domain provider: Mailjet's Email API v3.

A domain is registered as a domain sender (`*@<domain>`) of the account
whose keys Anymail sends with (`MAILJET_API_KEY`, `MAILJET_SECRET_KEY`):
Mailjet only sends from a sender of its own account, once it is validated.
Mailjet gives the records to publish in the domain's DNS entry: its
ownership token, which validates the sender, then SPF and DKIM. `check`
asks Mailjet to validate a sender that isn't yet, then to check the
entry's DKIM and SPF.

The keys travel in the basic auth header only: they are never logged nor put
in an error message, and Mailjet's own words are scrubbed of them.
"""

from __future__ import annotations

import base64
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

DEFAULT_API_URL = "https://api.mailjet.com"
TIMEOUT_SECONDS = 10
# Scanning the account's DNS entries for a domain: entries per page, and the
# most pages read, so that a huge account can't make a check endless.
DNS_PAGE_SIZE = 1000
DNS_MAX_PAGES = 10
# Each error text Mailjet gives is cut to this length.
MAX_ERROR_TEXT = 200

# Mailjet's sender ids and DNS ids are numbers; anything else must not reach
# a URL. A domain name only does when it looks like one.
_ID_RE = re.compile(r"^[0-9]{1,20}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")


class _HTTPError(SendingProviderError):
    """Mailjet answered with an error status. `detail` is its own message."""

    def __init__(self, message: str, status_code: int, detail: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class MailjetProvider:
    """Domain senders of one Mailjet account."""

    removal_needed = True

    def __init__(self) -> None:
        anymail = getattr(settings, "ANYMAIL", {}) or {}
        self.api_key = (anymail.get("MAILJET_API_KEY") or "").strip()
        self.secret_key = (anymail.get("MAILJET_SECRET_KEY") or "").strip()
        api_url = getattr(settings, "MAILJET_API_URL", "") or DEFAULT_API_URL
        self.api_url = f"{api_url.strip().rstrip('/')}/v3/REST"
        if not (self.api_key and self.secret_key):
            raise ImproperlyConfigured(
                "SENDING_DOMAIN_PROVIDER=mailjet needs MAILJET_API_KEY and "
                "MAILJET_SECRET_KEY."
            )

    def _scrub(self, text: str) -> str:
        """Mailjet's words, trimmed, without our keys should it echo them.

        The basic auth header's base64 of `key:secret` is masked too, first,
        as it doesn't contain the keys as they are.
        """
        basic = base64.b64encode(f"{self.api_key}:{self.secret_key}".encode()).decode()
        for secret in (basic, self.api_key, self.secret_key):
            text = text.replace(secret, "***")
        return text.strip()[:MAX_ERROR_TEXT]

    def _call(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        """One API call; any failure becomes a SendingProviderError."""
        try:
            response = requests.request(
                method,
                f"{self.api_url}{path}",
                auth=(self.api_key, self.secret_key),
                json=json,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            # The exception's text may hold the URL: only its type is logged.
            logger.warning("Mailjet %s %s failed: %s", method, path, type(exc).__name__)
            raise SendingProviderError("Mailjet could not be reached.") from None
        if response.status_code >= 400:
            detail = self._scrub(_error_message(response))
            logger.warning(
                "Mailjet %s %s answered %s: %s",
                method,
                path,
                response.status_code,
                detail,
            )
            # An HTTP failure shows admins its status only; Mailjet's words
            # stay in the log. What a check finds wrong (the validation, DKIM
            # and SPF texts, cleaned and trimmed) is shown to them.
            raise _HTTPError(
                f"The sending service answered {response.status_code}.",
                response.status_code,
                detail,
            )
        if response.status_code == 204 or not response.content:
            return {}
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            logger.warning(
                "Mailjet %s %s gave an answer that isn't a JSON object.", method, path
            )
            raise SendingProviderError("Mailjet gave an unreadable answer.")
        return body

    def _first(self, method: str, path: str, json: dict | None = None) -> dict:
        """The first result of a call, Mailjet wrapping them in `Data`."""
        data = self._call(method, path, json).get("Data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            logger.warning("Mailjet %s %s gave no result.", method, path)
            raise SendingProviderError("Mailjet gave an unreadable answer.")
        return data[0]

    def register(self, domain: str) -> RegisteredDomain:
        try:
            sender = self._first(
                "POST",
                "/sender",
                json={"Email": f"*@{domain}", "EmailType": "transactional"},
            )
        except _HTTPError as exc:
            if exc.status_code == 400 and "already exist" in exc.detail.lower():
                raise AlreadyRegisteredError(
                    f"{domain} is already registered with Mailjet."
                ) from None
            raise
        ref = _id(sender.get("ID"))
        if ref is None:
            logger.warning("Mailjet created a sender for %s without its id.", domain)
            raise SendingProviderError("Mailjet gave an unreadable answer.")
        # The sender exists now: failing here would lose its ref. Without its
        # entry, the records come with the first check.
        try:
            entry = self._dns_entry(sender, domain)
        except SendingProviderError as exc:
            logger.warning("Mailjet: no DNS entry read for %s yet: %s", domain, exc)
            entry = None
        return RegisteredDomain(ref=ref, records=_records(entry, domain))

    def _dns_entry(self, sender: dict, domain: str) -> dict | None:
        """The sender's DNS entry, or None if Mailjet has none for its domain.

        By the sender's DNSID when it has one; an inactive sender has none
        (-1), so then by domain name, then by scanning the account's entries.
        An entry read whose domain isn't this one is taken as not found.
        """
        dns_id = _id(sender.get("DNSID"))
        if dns_id is not None:
            entry = self._first("GET", f"/dns/{dns_id}")
            if _same_domain(entry.get("Domain"), domain):
                return entry
            logger.warning("Mailjet DNS entry %s isn't %s's.", dns_id, domain)
        if not _DOMAIN_RE.match(domain):
            return None
        try:
            entry = self._first("GET", f"/dns/{domain}")
        except _HTTPError as exc:
            if exc.status_code not in (400, 404):
                raise
        else:
            if _same_domain(entry.get("Domain"), domain):
                return entry
        for page in range(DNS_MAX_PAGES):
            query = f"Limit={DNS_PAGE_SIZE}&Offset={page * DNS_PAGE_SIZE}"
            data = self._call("GET", f"/dns?{query}").get("Data")
            if not isinstance(data, list):
                return None
            for entry in data:
                if isinstance(entry, dict) and _same_domain(
                    entry.get("Domain"), domain
                ):
                    return entry
            if len(data) < DNS_PAGE_SIZE:
                return None
        logger.warning("Mailjet: %s not among the first DNS entries scanned.", domain)
        return None

    def _sender_path(self, ref: str, action: str = "") -> str:
        """The path of one sender, from a ref that must be Mailjet's id."""
        if not _ID_RE.match(ref):
            raise SendingProviderError("This domain's Mailjet sender id is invalid.")
        return f"/sender/{ref}{action}"

    def check(self, ref: str) -> DomainCheck:
        path = self._sender_path(ref)
        try:
            sender = self._first("GET", path)
        except _HTTPError as exc:
            if exc.status_code == 404:
                return DomainCheck(CheckStatus.FAILED, "Mailjet no longer has it.")
            raise
        status = sender.get("Status")
        if status == "Deleted":
            return DomainCheck(CheckStatus.FAILED, "Mailjet deleted this sender.")
        if status not in ("Active", "Inactive"):
            logger.warning("Mailjet sender %s has the status %r.", ref, status)
            return DomainCheck(CheckStatus.UNKNOWN)
        domain = _sender_domain(sender)
        if domain is None:
            logger.warning("Mailjet sender %s isn't a domain sender.", ref)
            return DomainCheck(CheckStatus.UNKNOWN)

        errors: list[str] = []
        if status == "Inactive":
            errors = self._validate(ref)
            if not errors:
                sender = self._first("GET", path)
                if sender.get("Status") != "Active":
                    errors = ["Mailjet hasn't validated this domain yet."]
        active = not errors

        entry = self._dns_entry(sender, domain)
        if entry is None:
            return DomainCheck(
                CheckStatus.PENDING,
                " ".join([*errors, f"Mailjet has no DNS entry for {domain} yet."]),
            )
        records = _records(entry, domain) or None
        try:
            dns_errors = self._check_dns(entry)
        except SendingProviderError:
            if active:
                raise
            # Not validated anyway: what stops it is said already.
            dns_errors = []
        errors += dns_errors
        if active and not errors:
            return DomainCheck(CheckStatus.VERIFIED, "", records)
        return DomainCheck(CheckStatus.PENDING, " ".join(errors), records)

    def _validate(self, ref: str) -> list[str]:
        """Ask Mailjet to validate the sender: why it didn't, if it says."""
        try:
            result = self._first("POST", self._sender_path(ref, "/validate"))
        except _HTTPError as exc:
            if exc.status_code >= 500:
                raise
            return [exc.detail or "Mailjet couldn't validate this domain yet."]
        texts = _texts(result.get("Errors")) + _texts(result.get("GlobalError"))
        return [self._scrub(text) for text in texts]

    def _check_dns(self, entry: dict) -> list[str]:
        """Ask Mailjet to check the entry's DKIM and SPF: what isn't right."""
        dns_id = _id(entry.get("ID"))
        if dns_id is None:
            raise SendingProviderError("Mailjet gave an unreadable answer.")
        result = self._first("POST", f"/dns/{dns_id}/check")
        errors = []
        for name in ("DKIM", "SPF"):
            if result.get(f"{name}Status") == "OK":
                continue
            texts = _texts(result.get(f"{name}Errors")) or [
                f"Mailjet found it {result.get(f'{name}Status') or 'unchecked'}."
            ]
            errors.append(f"{name}: " + " ".join(self._scrub(t) for t in texts))
        return errors

    def remove(self, ref: str) -> None:
        """Delete the sender, unless Mailjet has it no more or deleted it."""
        path = self._sender_path(ref)
        if self._is_removed(path):
            return
        try:
            self._call("DELETE", path)
        except _HTTPError as exc:
            if exc.status_code == 404:  # Gone since.
                return
            # Mailjet may refuse to delete a sender it deleted meanwhile.
            if exc.status_code == 400 and self._is_removed(path):
                return
            raise

    def _is_removed(self, path: str) -> bool:
        """Whether Mailjet has no such sender, or a deleted one."""
        try:
            sender = self._first("GET", path)
        except _HTTPError as exc:
            if exc.status_code == 404:
                return True
            raise
        return sender.get("Status") == "Deleted"


def _error_message(response: requests.Response) -> str:
    """Mailjet's error text, from a body that may not be JSON."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    return " ".join(
        text
        for key in ("ErrorMessage", "ErrorInfo")
        if (text := body.get(key)) and isinstance(text, str)
    )


def _id(value: Any) -> str | None:
    """A Mailjet id as a string, or None for -1, 0 or anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and _ID_RE.match(value) and int(value) > 0:
        return value
    return None


def _texts(value: Any) -> list[str]:
    """The non-empty strings in an error field: a string, a list or a dict."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    return []


def _same_domain(name: Any, domain: str) -> bool:
    return isinstance(name, str) and name.strip().rstrip(".").lower() == domain


def _sender_domain(sender: dict) -> str | None:
    """The domain of a domain sender (`*@acme.com`)."""
    email = sender.get("Email")
    if not isinstance(email, str) or not email.startswith("*@"):
        return None
    return email[2:].strip().rstrip(".").lower() or None


def _records(entry: dict | None, domain: str) -> list[dict[str, Any]]:
    """Mailjet's records as [{type, name, value, merge?}], names fully qualified.

    In this order: the ownership token validating the sender, SPF (merged
    into an existing one), DKIM. A record Mailjet gives no value for is left
    out.
    """
    if not entry:
        return []
    wanted = [
        (entry.get("OwnerShipTokenRecordName"), entry.get("OwnerShipToken"), False),
        (domain, entry.get("SPFRecordValue"), True),
        (entry.get("DKIMRecordName"), entry.get("DKIMRecordValue"), False),
    ]
    records = []
    for name, value, merge in wanted:
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        record: dict[str, Any] = {
            "type": "TXT",
            "name": _qualified(name, domain),
            "value": value.strip(),
        }
        if merge:
            record["merge"] = True
        records.append(record)
    return records


def _qualified(name: str, domain: str) -> str:
    """A record name, fully qualified, from a relative or absolute one."""
    name = name.strip().rstrip(".").lower()
    if name in ("", "@") or name == domain:
        return domain
    if name.endswith(f".{domain}"):
        return name
    return f"{name}.{domain}"
