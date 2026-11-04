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

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.organizations import dns_verification

from .providers import CheckStatus, DomainCheck, RegisteredDomain


class ManualProvider:
    """DNS records built from the settings, checked with our own resolver."""

    def __init__(self) -> None:
        self.spf_include = settings.SENDING_DOMAIN_SPF_INCLUDE.strip().lower()
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

        errors = []
        spf_error = self._spf_error(domain, spf)
        if spf_error:
            errors.append(spf_error)
        operator_keys = {record for record in operator_dkim if "p=" in record}
        if not operator_keys.intersection(dkim):
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
        if not spf_records or include not in spf_records[0].lower().split():
            return f"SPF: add {include} to the SPF record of {domain}."
        return ""

    def remove(self, ref: str) -> None:
        return None
