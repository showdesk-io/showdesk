"""The Postal domains service, through HTTP, with Postal's command mocked.

Only `subprocess.run` (the `docker exec … rails runner` boundary) is mocked:
requests go through a real server on a free port.

Run: cd deploy/postal-domains && python -m pytest -q -p no:django
"""

from __future__ import annotations

import contextlib
import json
import logging
import stat
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
OTHER_UUID = "0b9e4c7a-1d2e-4f3a-8b5c-6d7e8f9a0b1c"
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


def postal(*answers):
    """A `subprocess.run` answering, call after call, what `rails runner`
    prints (Postal's own log lines, then our result) or raising."""
    queue = list(answers)

    def run(argv, **kwargs):
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        payload, returncode = answer if isinstance(answer, tuple) else (answer, 0)
        output = kwargs["stdout"]
        output.write(b'{"level":"info","message":"booting"}\n')
        if payload is not None:
            output.write(f"SHOWDESK_RESULT {json.dumps(payload)}\n".encode())
        return subprocess.CompletedProcess(argv, returncode)

    return mock.patch("postal_domains.subprocess.run", side_effect=run)


@contextlib.contextmanager
def serving(env: dict[str, str]) -> Iterator[str]:
    """The service's URL, while it runs."""
    server = postal_domains.make_server(
        postal_domains.load_config(
            {
                "POSTAL_DOMAINS_TOKEN": TOKEN,
                "POSTAL_DOMAINS_ORGANIZATION": "showdesk",
                "POSTAL_DOMAINS_SERVER": "customers",
                "POSTAL_DOMAINS_LISTEN_PORT": "0",
                **env,
            }
        )
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def state_file(tmp_path) -> Path:
    return tmp_path / "state" / "created.json"


@pytest.fixture
def env(state_file) -> dict[str, str]:
    state_file.parent.mkdir()
    return {
        "POSTAL_DOMAINS_STATE_FILE": str(state_file),
        "POSTAL_DOMAINS_PROTECTED": "Showdesk.example, mail.instance.example",
    }


@pytest.fixture
def service(env) -> Iterator[str]:
    with serving(env) as url:
        yield url


@pytest.fixture
def ours(env, state_file) -> Iterator[str]:
    """The service, having created the domain UUID."""
    state_file.write_text(json.dumps([UUID]))
    with serving(env) as url:
        yield url


def call(
    url: str,
    method: str,
    body: dict | bytes | None = None,
    token: str | None = TOKEN,
) -> tuple[int, dict | None]:
    data = body if isinstance(body, bytes) else None
    if isinstance(body, dict):
        data = json.dumps(body).encode()
    request = urllib.request.Request(
        url, method=method, data=data, headers={"Content-Type": "application/json"}
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


def created(state_file: Path) -> list[str]:
    return json.loads(state_file.read_text())


def test_a_wrong_or_missing_token_runs_nothing(service) -> None:
    with postal() as run:
        assert call(f"{service}/domains", "POST", {"name": "acme.com"}, None)[0] == 401
        assert call(f"{service}/domains/{UUID}", "GET", token="x" * 40)[0] == 401
    run.assert_not_called()


def test_invalid_input_never_reaches_postal(service) -> None:
    with postal() as run:
        for name in ("acme.com; rm -rf /", "-acme.com", "localhost", "1.2.3.4"):
            status, body = call(f"{service}/domains", "POST", {"name": name})
            assert (status, body) == (400, {"error": "invalid_name"})
        assert call(f"{service}/domains", "POST", {"nom": "acme.com"})[0] == 400
        too_large = json.dumps({"name": "acme.com", "x": "y" * 5000}).encode()
        assert call(f"{service}/domains", "POST", too_large) == (
            413,
            {"error": "too_large"},
        )
        assert call(f"{service}/domains/acme.com", "GET")[0] == 404
        assert call(f"{service}/domains/{UUID}%0A", "GET")[0] == 404
        assert call(f"{service}/domains/../../etc", "DELETE")[0] == 404
        # A protected domain, or one of its subdomains: never created.
        for name in (
            "showdesk.example",
            "eu.SHOWDESK.example",
            "mail.instance.example",
        ):
            status, body = call(f"{service}/domains", "POST", {"name": name})
            assert (status, body) == (403, {"error": "protected"})
    run.assert_not_called()


def test_create_runs_the_script_in_postal_and_records_the_domain(
    service, state_file
) -> None:
    with postal({"status": 201, "domain": STATE}) as run:
        status, body = call(f"{service}/domains", "POST", {"name": "Acme.COM"})
    assert (status, body) == (201, STATE)
    args, kwargs = run.call_args
    assert args[0] == [
        "docker",
        "exec",
        "-i",
        "postal-web-1",
        # Killed in the container: killing `docker exec` would leave it running.
        "timeout",
        "-s",
        "KILL",
        "30",
        "bundle",
        "exec",
        "rails",
        "runner",
        "-",
        "create",
        "showdesk",
        "customers",
        "acme.com",
        "showdesk.example,mail.instance.example",
    ]
    assert kwargs["input"] == Path(postal_domains.SCRIPT_PATH).read_bytes()
    assert kwargs["timeout"] == 35
    assert not kwargs.get("shell")
    assert created(state_file) == [UUID]
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600


def test_protected_names_match_whole_labels_any_case(env, state_file) -> None:
    # Capitals and a trailing dot in the list; a lookalike name isn't protected.
    with serving({**env, "POSTAL_DOMAINS_PROTECTED": "Showdesk.Example."}) as url:
        with postal() as run:
            assert call(f"{url}/domains", "POST", {"name": "eu.showdesk.example"}) == (
                403,
                {"error": "protected"},
            )
        run.assert_not_called()
        with postal(
            {"status": 201, "domain": {**STATE, "name": "notshowdesk.example"}}
        ):
            status, _ = call(f"{url}/domains", "POST", {"name": "notshowdesk.example"})
    assert status == 201
    assert created(state_file) == [UUID]


def test_a_created_domain_it_cannot_record_is_deleted_at_once(
    service, state_file, caplog
) -> None:
    state_file.parent.chmod(0o500)  # The state file can't be written.
    try:
        with (
            caplog.at_level(logging.INFO, "postal_domains"),
            postal({"status": 201, "domain": STATE}, {"status": 204}) as run,
        ):
            assert call(f"{service}/domains", "POST", {"name": "acme.com"}) == (
                502,
                {"error": "postal_failed"},
            )
    finally:
        state_file.parent.chmod(0o700)
    assert [c.args[0][13:16] for c in run.call_args_list] == [
        ["create", "showdesk", "customers"],
        ["delete", "showdesk", "customers"],
    ]
    assert run.call_args_list[1].args[0][16] == UUID
    assert f"Could not write {state_file}" in caplog.text
    assert f"deleted {UUID}" in caplog.text
    assert not state_file.exists()


def test_a_second_instance_on_the_same_state_file_is_refused(service, env) -> None:
    config = postal_domains.load_config(
        {
            "POSTAL_DOMAINS_TOKEN": TOKEN,
            "POSTAL_DOMAINS_ORGANIZATION": "showdesk",
            "POSTAL_DOMAINS_SERVER": "customers",
            "POSTAL_DOMAINS_LISTEN_PORT": "0",
            **env,
        }
    )
    with pytest.raises(postal_domains.ConfigError, match="another instance"):
        postal_domains.make_server(config)


def test_only_the_domains_it_created_are_its_own(ours) -> None:
    service = ours
    # The server has the name: ours (a retry) is returned, anyone else's
    # (added by hand, or in the organization) is refused.
    with postal(
        {"status": 200, "domain": STATE},
        {"status": 200, "domain": {**STATE, "id": OTHER_UUID}},
        {"error": "exists"},
    ):
        assert call(f"{service}/domains", "POST", {"name": "acme.com"}) == (200, STATE)
        for _ in range(2):
            assert call(f"{service}/domains", "POST", {"name": "acme.com"}) == (
                409,
                {"error": "exists"},
            )
    # A uuid it didn't create is never shown, checked nor deleted.
    with postal() as run:
        for method, path in (("GET", ""), ("POST", "/check"), ("DELETE", "")):
            assert call(f"{service}/domains/{OTHER_UUID}{path}", method) == (
                404,
                {"error": "not_found"},
            )
    run.assert_not_called()


def test_check_and_delete_address_its_domain_by_uuid(ours, state_file) -> None:
    service = ours
    with postal(
        {"status": 200, "domain": STATE}, {"error": "protected"}, {"status": 204}
    ) as run:
        assert call(f"{service}/domains/{UUID}/check", "POST") == (200, STATE)
        # Its name is protected (checked by the script, on the stored name).
        assert call(f"{service}/domains/{UUID}", "GET") == (
            403,
            {"error": "protected"},
        )
        assert call(f"{service}/domains/{UUID}", "DELETE") == (204, None)
    assert [c.args[0][13:17] for c in run.call_args_list] == [
        ["check", "showdesk", "customers", UUID],
        ["show", "showdesk", "customers", UUID],
        ["delete", "showdesk", "customers", UUID],
    ]
    assert created(state_file) == []


def test_postal_failing_hanging_or_busy(env, state_file) -> None:
    state_file.write_text(json.dumps([UUID]))
    with serving({**env, "POSTAL_DOMAINS_CONCURRENCY": "1"}) as url:
        with postal(
            subprocess.TimeoutExpired(["docker"], 35),
            (None, 137),  # Killed by `timeout` in the container.
            {"error": "failed", "detail": "NoMethodError"},
        ):
            for _ in range(3):
                assert call(f"{url}/domains/{UUID}", "GET") == (
                    502,
                    {"error": "postal_failed"},
                )

        # The only slot is taken: the next call is turned away, not queued.
        release, entered = threading.Event(), threading.Event()

        def slow(argv, **kwargs):
            entered.set()
            release.wait(5)
            kwargs["stdout"].write(
                b"SHOWDESK_RESULT "
                + json.dumps({"status": 200, "domain": STATE}).encode()
            )
            return subprocess.CompletedProcess(argv, 0)

        with (
            mock.patch("postal_domains.subprocess.run", side_effect=slow),
            mock.patch("postal_domains.BUSY_WAIT_SECONDS", 0.1),
        ):
            first = threading.Thread(target=call, args=(f"{url}/domains/{UUID}", "GET"))
            first.start()
            assert entered.wait(5)
            assert call(f"{url}/domains/{UUID}", "GET") == (503, {"error": "busy"})
            release.set()
            first.join(5)


def test_a_bad_configuration_is_refused_at_startup(env, state_file) -> None:
    base = {
        "POSTAL_DOMAINS_TOKEN": TOKEN,
        "POSTAL_DOMAINS_ORGANIZATION": "showdesk",
        "POSTAL_DOMAINS_SERVER": "customers",
        **env,
    }
    for override in (
        {"POSTAL_DOMAINS_TOKEN": "short"},
        {"POSTAL_DOMAINS_SERVER": "-customers"},
        {"POSTAL_DOMAINS_PROTECTED": "showdesk.example,not a domain"},
        {"POSTAL_DOMAINS_TIMEOUT": "60"},  # Past the 40 s a call may take.
    ):
        with pytest.raises(postal_domains.ConfigError):
            postal_domains.load_config({**base, **override})
    state_file.write_text("not json")
    with pytest.raises(postal_domains.ConfigError):
        postal_domains.make_server(postal_domains.load_config(base))
