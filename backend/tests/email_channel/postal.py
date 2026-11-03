"""Signing and posting mails as Postal's inbound webhook does."""

import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.test import Client

POSTAL_URL = "/anymail/postal/inbound/"


def new_postal_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_key_setting(key: rsa.RSAPrivateKey) -> str:
    """The public key as Postal shows it: the PEM body, without its frame."""
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return "".join(pem.decode().strip().splitlines()[1:-1])


def postal_payload(
    raw: bytes,
    *,
    rcpt_to: str = "acme-abc@in.example.com",
    mail_from: str = "customer@example.org",
) -> bytes:
    """The JSON body Postal posts for a mail, in "raw message, base64" mode."""
    return json.dumps(
        {
            "id": 1,
            "rcpt_to": rcpt_to,
            "mail_from": mail_from,
            "message": base64.b64encode(raw).decode(),
            "base64": True,
            "size": len(raw),
        }
    ).encode()


def post_to_postal(body: bytes, key: rsa.RSAPrivateKey):
    """Post ``body`` to the webhook, signed with ``key`` as Postal signs."""
    signature = key.sign(body, padding.PKCS1v15(), hashes.SHA1())
    # CSRF checks on, as for a real provider: the view must be exempt.
    return Client(enforce_csrf_checks=True).post(
        POSTAL_URL,
        data=body,
        content_type="application/json",
        headers={"X-Postal-Signature": base64.b64encode(signature).decode()},
    )
