"""Manage the sending domains of one Postal server over HTTP, for Showdesk.

Postal (v3) has no API to manage domains. This service runs on the Postal
host and does what Postal's web UI does, through Postal's own models: each
call runs `postal_domains.rb` in Postal's web container
(`docker exec -i <container> bundle exec rails runner - <action> ...`, the
script on stdin), which prints one `SHOWDESK_RESULT <json>` line.

    POST   /domains               {"name": "acme.com"} -> 201 created, 200 existing
    GET    /domains/<uuid>        -> 200, the domain's records and Postal's DNS status
    POST   /domains/<uuid>/check  -> 200, after Postal checked its DNS
    DELETE /domains/<uuid>        -> 204; 404 when Postal has no such domain

Every request needs `Authorization: Bearer <POSTAL_DOMAINS_TOKEN>`. Python's
standard library only. See README.md.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

logger = logging.getLogger("postal_domains")

SCRIPT_PATH = Path(__file__).with_name("postal_domains.rb")
RESULT_PREFIX = "SHOWDESK_RESULT "
MIN_TOKEN_LENGTH = 32
MAX_BODY_BYTES = 4096

# Showdesk's own rule for a domain: labels of 1-63 [a-z0-9-] with no hyphen
# at either end, at least two, a non-numeric last one, 253 characters at most.
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN_RE = re.compile(rf"^(?=.{{1,253}}$)(?:{_LABEL}\.)+(?![0-9]+$){_LABEL}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_PERMALINK_RE = re.compile(r"^[a-z0-9-]{1,64}$")
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DOMAIN_PATH_RE = re.compile(r"^/domains/([^/]+)(/check)?$")

# What the script's errors become.
_SCRIPT_ERRORS = {"not_found": 404, "rejected": 422}


class ConfigError(Exception):
    """The environment doesn't configure the service properly."""


@dataclass(frozen=True)
class Config:
    token: str
    organization: str
    server: str
    container: str = "postal-web-1"
    docker: str = "docker"
    timeout: float = 45.0
    host: str = "127.0.0.1"
    port: int = 8089
    concurrency: int = 2


def load_config(env: dict[str, str]) -> Config:
    """The configuration from environment variables. ConfigError if invalid."""
    token = env.get("POSTAL_DOMAINS_TOKEN", "").strip()
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(
            f"POSTAL_DOMAINS_TOKEN must be at least {MIN_TOKEN_LENGTH} characters."
        )
    organization = env.get("POSTAL_DOMAINS_ORGANIZATION", "").strip()
    server = env.get("POSTAL_DOMAINS_SERVER", "").strip()
    if not (_PERMALINK_RE.match(organization) and _PERMALINK_RE.match(server)):
        raise ConfigError(
            "POSTAL_DOMAINS_ORGANIZATION and POSTAL_DOMAINS_SERVER must be the "
            "permalinks of the Postal organization and server."
        )
    container = env.get("POSTAL_DOMAINS_CONTAINER", "").strip() or "postal-web-1"
    if not _CONTAINER_RE.match(container):
        raise ConfigError("POSTAL_DOMAINS_CONTAINER isn't a container name.")
    try:
        timeout = float(env.get("POSTAL_DOMAINS_TIMEOUT") or 45)
        port = int(env.get("POSTAL_DOMAINS_LISTEN_PORT") or 8089)
        concurrency = int(env.get("POSTAL_DOMAINS_CONCURRENCY") or 2)
    except ValueError as exc:
        raise ConfigError(f"Invalid number: {exc}") from None
    if timeout <= 0 or concurrency < 1 or not 0 <= port <= 65535:
        raise ConfigError("Invalid timeout, port or concurrency.")
    return Config(
        token=token,
        organization=organization,
        server=server,
        container=container,
        docker=env.get("POSTAL_DOMAINS_DOCKER", "").strip() or "docker",
        timeout=timeout,
        host=env.get("POSTAL_DOMAINS_LISTEN_HOST", "").strip() or "127.0.0.1",
        port=port,
        concurrency=concurrency,
    )


class Postal:
    """Runs the script's actions in Postal's web container."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.script = SCRIPT_PATH.read_bytes()
        # Each call boots Rails: bound how many run at once.
        self.slots = threading.BoundedSemaphore(config.concurrency)

    def run(self, action: str, arg: str) -> tuple[int, dict[str, Any] | None]:
        """(HTTP status, body) for one action on a checked name or uuid."""
        if not self.slots.acquire(timeout=self.config.timeout):
            return 503, {"error": "busy"}
        try:
            return self._run(action, arg)
        finally:
            self.slots.release()

    def _run(self, action: str, arg: str) -> tuple[int, dict[str, Any] | None]:
        config = self.config
        argv = [
            config.docker,
            "exec",
            "-i",
            config.container,
            "bundle",
            "exec",
            "rails",
            "runner",
            "-",
            action,
            config.organization,
            config.server,
            arg,
        ]
        try:
            completed = subprocess.run(
                argv,
                input=self.script,
                capture_output=True,
                timeout=config.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.error(
                "Postal %s %s timed out after %ss.", action, arg, config.timeout
            )
            return 502, {"error": "postal_failed"}
        except OSError as exc:
            logger.error("Postal %s %s could not run: %s", action, arg, exc)
            return 502, {"error": "postal_failed"}

        result = _result(completed.stdout)
        if result is None:
            logger.error(
                "Postal %s %s gave no result (exit %s): %s",
                action,
                arg,
                completed.returncode,
                _tail(completed.stderr or completed.stdout),
            )
            return 502, {"error": "postal_failed"}
        error = result.get("error")
        if error in _SCRIPT_ERRORS:
            body: dict[str, Any] = {"error": error}
            if error == "rejected":
                body["detail"] = str(result.get("detail", ""))[:300]
            return _SCRIPT_ERRORS[error], body
        if error:
            # Misconfiguration (no such server) or a Ruby exception: logged.
            logger.error("Postal %s %s failed: %s", action, arg, result)
            return 502, {"error": "postal_failed"}
        status = result.get("status")
        if status == 204:
            return 204, None
        if status in (200, 201) and isinstance(result.get("domain"), dict):
            return status, result["domain"]
        logger.error("Postal %s %s gave an unexpected result: %s", action, arg, result)
        return 502, {"error": "postal_failed"}


def _result(stdout: bytes) -> dict[str, Any] | None:
    """The script's result: the last SHOWDESK_RESULT line, Postal's logs aside."""
    for line in reversed(stdout.decode("utf-8", errors="replace").splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                value = json.loads(line[len(RESULT_PREFIX) :])
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None


def _tail(output: bytes) -> str:
    return output.decode("utf-8", errors="replace")[-1000:]


def make_server(config: Config) -> ThreadingHTTPServer:
    """The HTTP server, not started."""
    postal = Postal(config)

    class Handler(BaseHTTPRequestHandler):
        server_version = "postal-domains"
        sys_version = ""

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_DELETE(self) -> None:
            self._handle("DELETE")

        def _handle(self, method: str) -> None:
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            path = self.path.split("?", 1)[0]
            if method == "POST" and path == "/domains":
                name = self._name()
                if name is None:
                    self._send(400, {"error": "invalid_body"})
                elif not _DOMAIN_RE.match(name):
                    self._send(400, {"error": "invalid_name"})
                else:
                    self._send(*postal.run("create", name))
                return
            match = _DOMAIN_PATH_RE.match(path)
            if not match or not _UUID_RE.match(match.group(1)):
                self._send(404, {"error": "not_found"})
                return
            uuid, check = match.group(1), bool(match.group(2))
            action = {
                ("GET", False): "show",
                ("POST", True): "check",
                ("DELETE", False): "delete",
            }.get((method, check))
            if action is None:
                self._send(405, {"error": "method_not_allowed"})
                return
            self._send(*postal.run(action, uuid))

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            scheme, _, token = header.partition(" ")
            return scheme.lower() == "bearer" and hmac.compare_digest(
                token.strip().encode(), config.token.encode()
            )

        def _name(self) -> str | None:
            """The `name` of a JSON body, lower-cased, or None if unreadable."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            if not 0 < length <= MAX_BODY_BYTES:
                return None
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                return None
            name = body.get("name") if isinstance(body, dict) else None
            if not isinstance(name, str):
                return None
            return name.strip().rstrip(".").lower()

        def _send(self, status: int, body: dict[str, Any] | None) -> None:
            data = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            if body is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            # The request line and status only: never a header.
            logger.info("%s %s", self.address_string(), format % args)

    server = ThreadingHTTPServer((config.host, config.port), Handler)
    server.daemon_threads = True
    return server


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    try:
        config = load_config(dict(os.environ))
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2
    server = make_server(config)
    logger.info(
        "Managing the domains of Postal server %s/%s on %s:%s.",
        config.organization,
        config.server,
        config.host,
        server.server_address[1],
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
