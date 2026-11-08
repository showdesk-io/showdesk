# Postal domains service

Lets Showdesk (`SENDING_DOMAIN_PROVIDER=postal`) add, check and remove its
customers' sending domains in **one server** of a self-hosted
[Postal](https://github.com/postalserver/postal) v3. Postal has no API for
domains: this small service runs on the Postal host and does what Postal's web
UI does, through Postal's own models. Each call runs `postal_domains.rb` in
Postal's web container:

```
docker exec -i postal-web-1 timeout -s KILL 30 bundle exec rails runner - <action> <organization> <server> <name|uuid> <protected>
```

(the script on stdin, never a shell; the name or uuid checked first). One call
boots Rails, a few seconds; at most `POSTAL_DOMAINS_CONCURRENCY` run at once.
Python 3.11+ standard library only. Written against Postal 3.3.

**Time limits.** A call takes 40 s at most, so that Showdesk (which waits 60 s
per call, and makes two when a domain is enabled) stays within gunicorn's
120 s: a free slot within 5 s, else 503 `busy`; the command is killed **in the
container** after `POSTAL_DOMAINS_TIMEOUT` (30 s at most) by `timeout -s KILL`
(GNU coreutils, part of Postal's Debian-based image: `ruby:3.4-slim-bookworm`
in 3.3.7), since killing `docker exec` alone would leave Rails running there;
`docker exec` itself is killed 5 s later if it hasn't returned. Only the last
1 MB of Postal's output is read.

**Only its own domains.** The service keeps the uuids of the domains it created
in `POSTAL_DOMAINS_STATE_FILE`, and only ever shows, checks or deletes those
(any other uuid is a 404): a domain added to the server by hand is never
Showdesk's, nor deleted by it. Keep that file (a volume, below): without it, the
service no longer knows its domains (Showdesk's checks fail them, and enabling
them again is a 409).

## API

Every request needs `Authorization: Bearer <POSTAL_DOMAINS_TOKEN>` (else 401).

| Request | Answer |
|---|---|
| `POST /domains` `{"name": "acme.com"}` | 201 created; 200 if this service created it before (a retry); 409 `exists` if the server or its organization has it otherwise |
| `GET /domains/<uuid>` | 200, as stored |
| `POST /domains/<uuid>/check` | 200, once Postal has checked the domain's DNS (`check_dns`) |
| `DELETE /domains/<uuid>` | 204 |

A domain is:

```json
{
  "id": "6f1c3c1e-…",
  "name": "acme.com",
  "records": [
    {"kind": "spf", "type": "TXT", "name": "acme.com", "value": "v=spf1 include:spf.postal.example.com ~all"},
    {"kind": "dkim", "type": "TXT", "name": "postal-abcdef._domainkey.acme.com", "value": "v=DKIM1; t=s; h=sha256; p=…;"},
    {"kind": "return_path", "type": "CNAME", "name": "psrp.acme.com", "value": "rp.postal.example.com"}
  ],
  "status": {"checked_at": "2026-11-08T10:00:00Z", "dkim": "OK", "dkim_error": null,
             "spf": "OK", "spf_error": null, "return_path": "Missing", "return_path_error": "…"}
}
```

Errors are `{"error": <code>}`: 400 `invalid_body` / `invalid_name`, 403
`protected` (a name in `POSTAL_DOMAINS_PROTECTED`, or one of their
subdomains), 404 `not_found` (also for a path that isn't a uuid, or a domain
this service didn't create), 409 `exists`, 413 `too_large` (a body over 4 KB),
422 `rejected` (with Postal's `detail`), 502 `postal_failed` (Postal failed,
timed out or isn't configured: see the service's log), 503 `busy`.

Domains are created `outgoing` only, and already **verified**: Showdesk proves
the ownership itself (its own `_showdesk` TXT record), so Postal's verification
record isn't asked for. Postal only accepts a `From` on a verified domain of the
server (or of its organization), and only signs with a domain's own DKIM key
once it checked that key's record OK: Showdesk's checks call
`POST /domains/<uuid>/check`, which also starts Postal's own hourly re-check.

## Configuration

| Variable | Default | |
|---|---|---|
| `POSTAL_DOMAINS_TOKEN` | (required) | At least 32 characters, e.g. `openssl rand -hex 32`. The same value is Showdesk's `POSTAL_DOMAINS_API_TOKEN`. |
| `POSTAL_DOMAINS_ORGANIZATION` | (required) | The permalink of the Postal organization. |
| `POSTAL_DOMAINS_SERVER` | (required) | The permalink of the server (in that organization) whose domains Showdesk manages. |
| `POSTAL_DOMAINS_STATE_FILE` | `/var/lib/postal-domains/created.json` | The uuids of the domains it created (JSON, mode 600, replaced atomically). Its directory must exist and be writable by the service. |
| `POSTAL_DOMAINS_PROTECTED` | empty | Domains never created, shown, checked nor deleted, nor their subdomains (comma-separated, any case). List the domain of Showdesk's `DEFAULT_FROM_EMAIL` and its `INBOUND_EMAIL_DOMAIN`, and any other domain of yours on this Postal. |
| `POSTAL_DOMAINS_CONTAINER` | `postal-web-1` | Postal's web container. |
| `POSTAL_DOMAINS_DOCKER` | `docker` | The Docker CLI. |
| `POSTAL_DOMAINS_TIMEOUT` | `30` | Seconds Postal's command may run before it is killed, 30 at most. |
| `POSTAL_DOMAINS_LISTEN_HOST`, `POSTAL_DOMAINS_LISTEN_PORT` | `127.0.0.1`, `8089` | Where it listens. |
| `POSTAL_DOMAINS_CONCURRENCY` | `2` | Calls run at once (each boots Rails). |

The service can run any command in Postal's containers (it has the Docker
socket): treat it as root on the host, keep it on `127.0.0.1`, and reach it
only through the reverse proxy, over HTTPS.

## Running it

Copy this directory to the Postal host, e.g. `/opt/postal-domains`, and put the
variables in `/opt/postal-domains/env` (mode 600).

**As a compose service** next to Postal's (`/opt/postal/install`, project
`postal`), in a `docker-compose.override.yml` or a compose file of its own:

```yaml
services:
  showdesk-domains:
    build: /opt/postal-domains
    network_mode: host
    env_file: /opt/postal-domains/env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/postal-domains:/var/lib/postal-domains
    restart: unless-stopped
```

(`mkdir -m 700 /var/lib/postal-domains` first.)

**Or as a systemd unit** (Python 3.11+ on the host, a user in the `docker`
group: that is root-equivalent too, as anyone in it can start a privileged
container), `/etc/systemd/system/postal-domains.service`:

```ini
[Unit]
Description=Postal domains service for Showdesk
After=docker.service
Requires=docker.service

[Service]
User=postal-domains
StateDirectory=postal-domains
StateDirectoryMode=0700
EnvironmentFile=/opt/postal-domains/env
ExecStart=/usr/bin/python3 -u /opt/postal-domains/postal_domains.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then, in the Caddyfile in front of Postal (`/opt/postal/config/Caddyfile` with
postalserver/install):

```
postal.example.com {
  handle_path /showdesk-domains/* {
    reverse_proxy 127.0.0.1:8089
  }
  handle {
    reverse_proxy 127.0.0.1:5000
  }
}
```

and on Showdesk: `SENDING_DOMAIN_PROVIDER=postal`,
`POSTAL_DOMAINS_API_URL=https://postal.example.com/showdesk-domains`,
`POSTAL_DOMAINS_API_TOKEN=<the token>`. Check it from the Showdesk host:

```
curl -s -H "Authorization: Bearer $TOKEN" https://postal.example.com/showdesk-domains/domains/00000000-0000-0000-0000-000000000000
# {"error": "not_found"} once Postal answered (a few seconds)
```

## On the Postal side

- One server for Showdesk, in `Live` mode. The service only manages the
  domains it created there: a domain already on the server (or its
  organization) is refused (409), and so is enabling sending from it in
  Showdesk ("already registered with the sending service"), until you remove
  it from Postal.
- `dns.spf_include`, `dns.return_path_domain`, `dns.custom_return_path_prefix`
  and `dns.dkim_identifier` in `postal.yml` are what customers are asked to
  publish: set them before customers do. A DKIM key regenerated in Postal's UI
  changes the record they must publish (their domains go back to pending).
- Showdesk sends its own mail (`EMAIL_BACKEND=anymail.backends.postal.EmailBackend`,
  `ANYMAIL_POSTAL_API_URL`, `ANYMAIL_POSTAL_API_KEY`: an API credential of
  **this** server) from `DEFAULT_FROM_EMAIL` and from `INBOUND_EMAIL_DOMAIN`:
  add both domains to the server (or its organization) yourself, verified, with
  their SPF, DKIM and return path published, and list them in
  `POSTAL_DOMAINS_PROTECTED`. Showdesk never manages them.
- The host itself: a PTR record matching Postal's `smtp_hostname`, the SPF
  record of `dns.spf_include` listing the host's addresses, Postal's own DKIM
  key published (`postal default-dkim-record`) and the return path domain set
  up as in Postal's documentation.

## Tests

```
cd deploy/postal-domains && python -m pytest -q -p no:django
```

Only `subprocess.run` is mocked; requests go through a real server.
