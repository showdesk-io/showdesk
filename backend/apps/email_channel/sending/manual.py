"""The `manual` sending domain provider.

The operator runs a sending service (Postal, OpenDKIM, Haraka...) that relays
for any domain and signs every one with a single DKIM key, published once at
`<selector>._domainkey.<INBOUND_EMAIL_DOMAIN>`. A customer domain then needs:

- its SPF record to include the service's (`include:<SENDING_DOMAIN_SPF_INCLUDE>`);
- a CNAME `<selector>._domainkey.<domain>` to the operator's key, which is
  checkable: following it must give that key.

Showdesk can't register anything there, so `register` only says what to
publish, `check` reads the DNS, and `remove` has nothing to undo.
"""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.organizations import dns_verification

from .providers import CheckStatus, DomainCheck, RegisteredDomain

logger = logging.getLogger(__name__)

# SPF's `all` mechanism, with any qualifier: nothing after it is evaluated.
_SPF_ALL = {"all", "+all", "-all", "~all", "?all"}
# A DKIM record's public key; empty means the key is revoked (RFC 6376 §3.6.1).
_DKIM_KEY_RE = re.compile(r"(?:^|;)p=([^;]+)")


class ManualProvider:
    """DNS records built from the settings, checked with our own resolver."""

    def __init__(self) -> None:
        self.spf_include = (
            settings.SENDING_DOMAIN_SPF_INCLUDE.strip().lower().rstrip(".")
        )
        self.selector = settings.SENDING_DOMAIN_DKIM_SELECTOR.strip().lower()
        self.inbound_domain = settings.INBOUND_EMAIL_DOMAIN
        if not (self.spf_include and self.selector and self.inbound_domain):
            raise ImproperlyConfigured(
                "SENDING_DOMAIN_PROVIDER=manual needs SENDING_DOMAIN_SPF_INCLUDE, "
                "SENDING_DOMAIN_DKIM_SELECTOR and INBOUND_EMAIL_DOMAIN."
            )

    def _dkim_name(self, domain: str) -> str:
        return f"{self.selector}._domainkey.{domain}"

    def register(self, domain: str) -> RegisteredDomain:
        # The domain itself is the ref: there is nothing provider-side.
        return RegisteredDomain(
            ref=domain,
            records=[
                {
                    "type": "TXT",
                    "name": domain,
                    "value": f"v=spf1 include:{self.spf_include} ~all",
                    # One SPF record per domain: add the include to an
                    # existing one rather than publishing a second.
                    "merge": True,
                },
                {
                    "type": "CNAME",
                    "name": self._dkim_name(domain),
                    "value": self._dkim_name(self.inbound_domain),
                },
            ],
        )

    def check(self, ref: str) -> DomainCheck:
        domain = ref
        spf = dns_verification.lookup_txt(domain)
        dkim = dns_verification.lookup_txt(self._dkim_name(domain))
        operator_dkim = dns_verification.lookup_txt(
            self._dkim_name(self.inbound_domain)
        )
        if spf is None or dkim is None or operator_dkim is None:
            return DomainCheck(CheckStatus.UNKNOWN)

        operator_keys = {key for key in map(_dkim_key, operator_dkim) if key}
        if not operator_keys:
            # The operator's setup is broken, not the customer's: say nothing
            # to the customer, and don't fail their domain for it.
            logger.warning(
                "Manual sending provider: no usable DKIM key at %s.",
                self._dkim_name(self.inbound_domain),
            )
            return DomainCheck(CheckStatus.UNKNOWN)

        errors = []
        spf_error = self._spf_error(domain, spf)
        if spf_error:
            errors.append(spf_error)
        if not operator_keys.intersection(map(_dkim_key, dkim)):
            errors.append(
                f"DKIM: {self._dkim_name(domain)} must be a CNAME to "
                f"{self._dkim_name(self.inbound_domain)}."
            )
        if errors:
            return DomainCheck(CheckStatus.PENDING, " ".join(errors))
        return DomainCheck(CheckStatus.VERIFIED, "")

    def _spf_error(self, domain: str, records: list[str]) -> str:
        """Why the domain's SPF doesn't let the service send, or ""."""
        spf_records = [r for r in records if r.lower().split()[:1] == ["v=spf1"]]
        include = f"include:{self.spf_include}"
        if len(spf_records) > 1:
            # Receivers treat several SPF records as an error (RFC 7208 §4.5).
            return f"SPF: {domain} has several SPF records; merge them into one."
        if not spf_records or not _spf_includes(spf_records[0], self.spf_include):
            return f"SPF: add {include} to the SPF record of {domain}."
        return ""

    def remove(self, ref: str) -> None:
        return None


def _dkim_key(record: str) -> str:
    """A DKIM record's key, whitespace removed; "" if it has none."""
    compact = re.sub(r"\s+", "", record)
    match = _DKIM_KEY_RE.search(compact)
    return match.group(1) if match else ""


def _spf_includes(record: str, include: str) -> bool:
    """Whether the SPF record includes `include` before its `all` mechanism."""
    for token in record.lower().split()[1:]:
        if token in _SPF_ALL:
            return False
        if token.lstrip("+").rstrip(".") == f"include:{include}":
            return True
    return False
