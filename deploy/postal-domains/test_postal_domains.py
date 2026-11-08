"""The Postal domains service, through HTTP, with Postal's command mocked.

Only `subprocess.run` (the `docker exec … rails runner` boundary) is mocked:
requests go through a real server on a free port.

Run: cd deploy/postal-domains && python -m pytest -q -p no:django
"""

from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

import postal_domains

TOKEN = "t" * 40
UUID = "6f1c3c1e-2b1a-4b5e-9a57-0c3b1f1e2d3a"
STATE = {
    "id": UUID,
    "name": "acme.com",
    "records": [
        {
            "kind": "spf",
            "type": "TXT",
            "name": "acme.com",
            "value": "v=spf1 include:spf.postal.example.com ~all",
        },
        {
            "kind": "dkim",
            "type": "TXT",
            "name": "postal-abcdef._domainkey.acme.com",
            "value": "v=DKIM1; t=s; h=sha256; p=MIGf;",
        },
    ],
    "status": {"checked_at": None, "dkim": None},
}


def postal_output(payload: dict, returncode: int = 0) -> subprocess.CompletedProcess:
    """What `rails runner` prints: Postal's own log lines, then our result."""
    stdout = (
        '{"level":"info","message":"booting"}\n'
        f"SHOWDESK_RESULT {json.dumps(payload)}\n"
    )
    return subprocess.CompletedProcess([], returncode, stdout.encode(), b"")


@pytest.fixture
def service() -> Iterator[str]:
    config = postal_domains.load_config(
        {
            "POSTAL_DOMAINS_TOKEN": TOKEN,
            "POSTAL_DOMAINS_ORGANIZATION": "showdesk",
            "POSTAL_DOMAINS_SERVER": "customers",
            "POSTAL_DOMAINS_LISTEN_PORT": "0",
        }
    )
    server = postal_domains.make_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def call(
    url: str, method: str, body: dict | None = None, token: str | None = TOKEN
) -> tuple[int, dict | None]:
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else None


def test_a_wrong_or_missing_token_runs_nothing(service) -> None:
    with mock.patch("postal_domains.subprocess.run") as run:
        assert call(f"{service}/domains", "POST", {"name": "acme.com"}, None)[0] == 401
        assert call(f"{service}/domains/{UUID}", "GET", token="x" * 40)[0] == 401
    run.assert_not_called()


def test_invalid_input_never_reaches_postal(service) -> None:
    with mock.patch("postal_domains.subprocess.run") as run:
        for name in ("acme.com; rm -rf /", "-acme.com", "localhost", "1.2.3.4"):
            status, body = call(f"{service}/domains", "POST", {"name": name})
            assert (status, body) == (400, {"error": "invalid_name"})
        assert call(f"{service}/domains", "POST", {"nom": "acme.com"})[0] == 400
        assert call(f"{service}/domains/acme.com", "GET")[0] == 404
        assert call(f"{service}/domains/../../etc", "DELETE")[0] == 404
    run.assert_not_called()


def test_create_runs_the_script_in_postal_and_returns_its_state(service) -> None:
    with mock.patch(
        "postal_domains.subprocess.run",
        return_value=postal_output({"status": 201, "domain": STATE}),
    ) as run:
        status, body = call(f"{service}/domains", "POST", {"name": "Acme.COM"})
    assert (status, body) == (201, STATE)
    args, kwargs = run.call_args
    assert args[0] == [
        "docker",
        "exec",
        "-i",
        "postal-web-1",
        "bundle",
        "exec",
        "rails",
        "runner",
        "-",
        "create",
        "showdesk",
        "customers",
        "acme.com",
    ]
    assert kwargs["input"] == Path(postal_domains.SCRIPT_PATH).read_bytes()
    assert kwargs["timeout"] == 45
    assert not kwargs.get("shell")


def test_an_existing_domain_is_returned_as_it_is(service) -> None:
    with mock.patch(
        "postal_domains.subprocess.run",
        return_value=postal_output({"status": 200, "domain": STATE}),
    ):
        assert call(f"{service}/domains", "POST", {"name": "acme.com"}) == (200, STATE)


def test_check_and_delete_address_the_domain_by_uuid(service) -> None:
    with mock.patch(
        "postal_domains.subprocess.run",
        side_effect=[
            postal_output({"status": 200, "domain": STATE}),
            postal_output({"error": "not_found"}),
        ],
    ) as run:
        assert call(f"{service}/domains/{UUID}/check", "POST") == (200, STATE)
        assert call(f"{service}/domains/{UUID}", "DELETE") == (
            404,
            {"error": "not_found"},
        )
    assert [c.args[0][9:] for c in run.call_args_list] == [
        ["check", "showdesk", "customers", UUID],
        ["delete", "showdesk", "customers", UUID],
    ]


def test_postal_failing_or_hanging_is_a_502(service) -> None:
    with mock.patch(
        "postal_domains.subprocess.run",
        side_effect=[
            subprocess.TimeoutExpired(["docker"], 45),
            subprocess.CompletedProcess([], 1, b"Traceback...", b"boom"),
        ],
    ):
        assert call(f"{service}/domains/{UUID}", "GET") == (
            502,
            {"error": "postal_failed"},
        )
        assert call(f"{service}/domains/{UUID}", "GET") == (
            502,
            {"error": "postal_failed"},
        )


def test_a_short_token_is_refused_at_startup() -> None:
    with pytest.raises(postal_domains.ConfigError):
        postal_domains.load_config(
            {
                "POSTAL_DOMAINS_TOKEN": "short",
                "POSTAL_DOMAINS_ORGANIZATION": "showdesk",
                "POSTAL_DOMAINS_SERVER": "customers",
            }
        )
