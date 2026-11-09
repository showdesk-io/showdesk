"""Manage the sending domains of one Postal server over HTTP, for Showdesk.

Postal (v3) has no API to manage domains. This service runs on the Postal
host and does what Postal's web UI does, through Postal's own models: each
call runs `postal_domains.rb` in Postal's web container
(`docker exec -i <container> timeout -s KILL <n> bundle exec rails runner -
<action> ...`, the script on stdin), which prints one `SHOWDESK_RESULT <json>`
line.

    POST   /domains               {"name": "acme.com"} -> 201 created, 200 one
                                  it created before; 409 anyone else's
    GET    /domains/<uuid>        -> 200, the domain's records and Postal's DNS status
    POST   /domains/<uuid>/check  -> 200, after Postal checked its DNS
    DELETE /domains/<uuid>        -> 204; 404 when Postal has no such domain

It only ever shows, checks or deletes the domains it created (their uuids are
kept in POSTAL_DOMAINS_STATE_FILE), and never touches a protected one
(POSTAL_DOMAINS_PROTECTED). Every request needs `Authorization: Bearer
<POSTAL_DOMAINS_TOKEN>`. Python's standard library only. See README.md.
"""

from __future__ import annotations

import contextlib
import fcntl
import hmac
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
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
# Of Postal's output, only the end is read (the result line comes last).
MAX_OUTPUT_BYTES = 1024 * 1024
DEFAULT_STATE_FILE = "/var/lib/postal-domains/created.json"

# One call's deadline, at most 40 s (Showdesk waits 60 per call, and enabling
# a domain makes two within gunicorn's 120 s): a free slot within
# BUSY_WAIT_SECONDS, else 503; the command killed in the container after
# POSTAL_DOMAINS_TIMEOUT (MAX_TIMEOUT_SECONDS at most); `docker exec` itself
# killed KILL_GRACE_SECONDS later, should the container not answer.
BUSY_WAIT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 30.0
KILL_GRACE_SECONDS = 5.0
# A client that sends its request slowly is dropped after this long.
SOCKET_TIMEOUT_SECONDS = 15

# Showdesk's own rule for a domain: labels of 1-63 [a-z0-9-] with no hyphen
# at either end, at least two, a non-numeric last one, 253 characters at most.
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
# All of them used with fullmatch: `$` would let a final newline through.
_DOMAIN_RE = re.compile(rf"(?=.{{1,253}}\Z)(?:{_LABEL}\.)+(?![0-9]+\Z){_LABEL}")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_PERMALINK_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_CONTAINER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_DOMAIN_PATH_RE = re.compile(r"/domains/([^/]+)(/check)?")

# What the script's errors become.
_SCRIPT_ERRORS = {"not_found": 404, "protected": 403, "exists": 409, "rejected": 422}


class ConfigError(Exception):
    """The environment doesn't configure the service properly."""


@dataclass(frozen=True)
class Config:
    token: str
    organization: str
    server: str
    state_file: str = DEFAULT_STATE_FILE
    protected: tuple[str, ...] = ()
    container: str = "postal-web-1"
    docker: str = "docker"
    timeout: float = MAX_TIMEOUT_SECONDS
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
    if not (_PERMALINK_RE.fullmatch(organization) and _PERMALINK_RE.fullmatch(server)):
        raise ConfigError(
            "POSTAL_DOMAINS_ORGANIZATION and POSTAL_DOMAINS_SERVER must be the "
            "permalinks of the Postal organization and server."
        )
    container = env.get("POSTAL_DOMAINS_CONTAINER", "").strip() or "postal-web-1"
    if not _CONTAINER_RE.fullmatch(container):
        raise ConfigError("POSTAL_DOMAINS_CONTAINER isn't a container name.")
    protected = tuple(
        dict.fromkeys(
            name.strip().rstrip(".").lower()
            for name in env.get("POSTAL_DOMAINS_PROTECTED", "").split(",")
            if name.strip()
        )
    )
    if not all(_DOMAIN_RE.fullmatch(name) for name in protected):
        raise ConfigError(
            "POSTAL_DOMAINS_PROTECTED must be domain names, comma-separated."
        )
    try:
        timeout = float(env.get("POSTAL_DOMAINS_TIMEOUT") or MAX_TIMEOUT_SECONDS)
        port = int(env.get("POSTAL_DOMAINS_LISTEN_PORT") or 8089)
        concurrency = int(env.get("POSTAL_DOMAINS_CONCURRENCY") or 2)
    except ValueError as exc:
        raise ConfigError(f"Invalid number: {exc}") from None
    if not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        raise ConfigError(
            f"POSTAL_DOMAINS_TIMEOUT must be at most {MAX_TIMEOUT_SECONDS:g} seconds."
        )
    if concurrency < 1 or not 0 <= port <= 65535:
        raise ConfigError("Invalid port or concurrency.")
    return Config(
        token=token,
        organization=organization,
        server=server,
        state_file=env.get("POSTAL_DOMAINS_STATE_FILE", "").strip()
        or DEFAULT_STATE_FILE,
        protected=protected,
        container=container,
        docker=env.get("POSTAL_DOMAINS_DOCKER", "").strip() or "docker",
        timeout=timeout,
        host=env.get("POSTAL_DOMAINS_LISTEN_HOST", "").strip() or "127.0.0.1",
        port=port,
        concurrency=concurrency,
    )


def is_protected(name: str, protected: tuple[str, ...]) -> bool:
    """Whether a (lower-case) name is a protected domain or one of its subdomains."""
    return any(name == entry or name.endswith(f".{entry}") for entry in protected)


class CreatedDomains:
    """The uuids of the domains this service created, kept in a JSON file.

    Only those are shown, checked or deleted: a domain added to the server
    otherwise (by hand, before Showdesk) is never Showdesk's to delete. The
    file is replaced atomically on every change, mode 600. One instance only
    uses it: an exclusive lock on `<file>.lock`, held while it runs.
    """

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()
        self.lock_fd = self._lock_file()
        try:
            self.uuids = self._load()
        except BaseException:
            self.close()
            raise

    def _lock_file(self) -> int:
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise ConfigError(f"Can't open {lock_path}: {exc}") from None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise ConfigError(
                f"{lock_path} is locked: another instance uses this state file."
            ) from None
        return fd

    def close(self) -> None:
        """Release the lock."""
        if self.lock_fd >= 0:
            os.close(self.lock_fd)
            self.lock_fd = -1

    def _load(self) -> frozenset[str]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return frozenset()
        except OSError as exc:
            raise ConfigError(f"Can't read {self.path}: {exc}") from None
        try:
            value = json.loads(raw)
        except ValueError:
            value = None
        if not (
            isinstance(value, list)
            and all(isinstance(u, str) and _UUID_RE.fullmatch(u) for u in value)
        ):
            raise ConfigError(f"{self.path} isn't a JSON list of domain uuids.")
        return frozenset(value)

    def __contains__(self, uuid: str) -> bool:
        with self.lock:
            return uuid in self.uuids

    def add(self, uuid: str) -> None:
        with self.lock:
            if uuid not in self.uuids:
                self._write(self.uuids | {uuid})

    def discard(self, uuid: str) -> None:
        with self.lock:
            if uuid in self.uuids:
                self._write(self.uuids - {uuid})

    def _write(self, uuids: frozenset[str]) -> None:
        # mkstemp creates the file mode 600; replacing is atomic.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".created-")
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(sorted(uuids), file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        self.uuids = uuids
        # The rename itself, on disk.
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class Postal:
    """Runs the script's actions in Postal's web container."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.script = SCRIPT_PATH.read_bytes()
        self.created = CreatedDomains(config.state_file)
        # Each call boots Rails: bound how many run at once.
        self.slots = threading.BoundedSemaphore(config.concurrency)

    def run(self, action: str, arg: str) -> tuple[int, dict[str, Any] | None]:
        """(HTTP status, body) for one action on a checked name or uuid."""
        if action == "create":
            if is_protected(arg, self.config.protected):
                return 403, {"error": "protected"}
        elif arg not in self.created:
            return 404, {"error": "not_found"}
        if not self.slots.acquire(timeout=BUSY_WAIT_SECONDS):
            return 503, {"error": "busy"}
        try:
            status, body = self._run(action, arg)
            return self._record(action, arg, status, body)
        finally:
            self.slots.release()

    def _record(
        self, action: str, arg: str, status: int, body: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any] | None]:
        """Keep the state file in step with what Postal answered."""
        try:
            if action == "create" and status == 201:
                self.created.add(body["id"])
            elif (
                action == "create" and status == 200 and body["id"] not in self.created
            ):
                logger.warning(
                    "%s is already on the Postal server, not added by this service.",
                    arg,
                )
                return 409, {"error": "exists"}
            elif action == "delete" and status in (204, 404):
                self.created.discard(arg)
        except OSError as exc:
            logger.error("Could not write %s: %s", self.created.path, exc)
            if action == "create" and status == 201:
                self._undo_create(arg, body["id"])
            if action == "create":
                return 502, {"error": "postal_failed"}
        return status, body

    def _undo_create(self, name: str, uuid: str) -> None:
        """Delete a domain just created but not recorded: unrecorded, it would
        never be ours again, and enabling it a 409 from then on."""
        status, _ = self._run("delete", uuid)
        if status in (204, 404):
            logger.warning("Unrecorded %s: deleted %s from Postal.", name, uuid)
        else:
            logger.error(
                "Unrecorded %s (%s) could not be deleted from Postal: delete it "
                "there, or add its uuid to %s (README, Recovery).",
                name,
                uuid,
                self.created.path,
            )

    def _run(self, action: str, arg: str) -> tuple[int, dict[str, Any] | None]:
        config = self.config
        argv = [
            config.docker,
            "exec",
            "-i",
            config.container,
            # Killed in the container: killing `docker exec` would leave the
            # command running there. Postal's image is Debian's: coreutils.
            "timeout",
            "-s",
            "KILL",
            f"{config.timeout:g}",
            "bundle",
            "exec",
            "rails",
            "runner",
            "-",
            action,
            config.organization,
            config.server,
            arg,
            ",".join(config.protected),
        ]
        # The output goes to a file, of which only the end is read.
        with tempfile.TemporaryFile() as output:
            try:
                completed = subprocess.run(
                    argv,
                    input=self.script,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=config.timeout + KILL_GRACE_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                logger.error("Postal %s %s: docker exec didn't return.", action, arg)
                return 502, {"error": "postal_failed"}
            except OSError as exc:
                logger.error("Postal %s %s could not run: %s", action, arg, exc)
                return 502, {"error": "postal_failed"}
            stdout = _end_of(output)

        result = _result(stdout)
        if result is None:
            logger.error(
                "Postal %s %s gave no result (exit %s%s): %s",
                action,
                arg,
                completed.returncode,
                f", killed after {config.timeout:g}s"
                if completed.returncode in (124, 137)
                else "",
                stdout.decode("utf-8", errors="replace")[-1000:],
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
        domain = result.get("domain")
        if (
            status in (200, 201)
            and isinstance(domain, dict)
            and _UUID_RE.fullmatch(str(domain.get("id", "")))
        ):
            return status, domain
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


def _end_of(output: Any) -> bytes:
    """The last MAX_OUTPUT_BYTES of a file."""
    size = output.seek(0, os.SEEK_END)
    output.seek(max(0, size - MAX_OUTPUT_BYTES))
    return output.read(MAX_OUTPUT_BYTES)


def make_server(config: Config) -> ThreadingHTTPServer:
    """The HTTP server, not started."""
    postal = Postal(config)

    class Handler(BaseHTTPRequestHandler):
        server_version = "postal-domains"
        sys_version = ""
        timeout = SOCKET_TIMEOUT_SECONDS

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
                if self._length() > MAX_BODY_BYTES:
                    self.close_connection = True
                    self._send(413, {"error": "too_large"})
                    return
                name = self._name()
                if name is None:
                    self._send(400, {"error": "invalid_body"})
                elif not _DOMAIN_RE.fullmatch(name):
                    self._send(400, {"error": "invalid_name"})
                else:
                    self._send(*postal.run("create", name))
                return
            match = _DOMAIN_PATH_RE.fullmatch(path)
            if not match or not _UUID_RE.fullmatch(match.group(1)):
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

        def _length(self) -> int:
            """The body's Content-Length, -1 if unreadable."""
            try:
                return int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return -1

        def _name(self) -> str | None:
            """The `name` of a JSON body, lower-cased, or None if unreadable."""
            length = self._length()
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

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def server_close(self) -> None:
            super().server_close()
            postal.created.close()

    try:
        return Server((config.host, config.port), Handler)
    except BaseException:
        postal.created.close()
        raise


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    try:
        config = load_config(dict(os.environ))
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2
    try:
        server = make_server(config)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2
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
