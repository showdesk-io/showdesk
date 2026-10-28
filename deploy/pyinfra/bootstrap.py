"""pyinfra deploy: prepare a bare Ubuntu host to run Showdesk with Docker Compose.

Usage:
    pyinfra deploy/pyinfra/inventory.py deploy/pyinfra/bootstrap.py

Idempotent -- safe to re-run. It only prepares the host; the application
itself (compose file, .env, images) is shipped by the deploy step
(see deploy/README.md), never by this script.

Steps:
1. System update, base packages, unattended security upgrades, UTC
2. Docker Engine + compose plugin (official apt repository)
3. Deploy user (docker group, SSH keys) + application directory
4. SSH hardening (keys only)
5. Firewall: UFW for SSH, DOCKER-USER chain for published HTTP(S) ports
6. fail2ban

Host data (see inventory.example.py):
    deploy_user             str        default "deploy"
    deploy_authorized_keys  list[str]  public keys allowed to log in as deploy_user
    app_dir                 str        default "/opt/showdesk"
    ssh_allow_cidrs         list[str]  default ["0.0.0.0/0", "::/0"]
    http_allow_cidrs        list[str] | "cloudflare" | None
                                       restrict ports 80/443; None = open to all
    permit_root_login       str        sshd PermitRootLogin, default "prohibit-password"
"""

from io import StringIO

from pyinfra import host
from pyinfra.operations import apt, files, server, systemd

DEPLOY_USER = host.data.get("deploy_user", "deploy")
DEPLOY_KEYS = host.data.get("deploy_authorized_keys", [])
APP_DIR = host.data.get("app_dir", "/opt/showdesk")
SSH_ALLOW = host.data.get("ssh_allow_cidrs", ["0.0.0.0/0", "::/0"])
HTTP_ALLOW = host.data.get("http_allow_cidrs")
PERMIT_ROOT_LOGIN = host.data.get("permit_root_login", "prohibit-password")

# ---------------------------------------------------------------------------
# 1. System
# ---------------------------------------------------------------------------
apt.packages(
    name="Remove unused mail server",
    packages=["postfix"],
    present=False,
    purge=True,
)

apt.update(name="Update apt cache", cache_time=3600)
apt.upgrade(name="Upgrade packages", auto_remove=True)

apt.packages(
    name="Install base packages",
    packages=[
        "ca-certificates",
        "curl",
        "gnupg",
        "ufw",
        "fail2ban",
        "unattended-upgrades",
        "iptables",
    ],
)

server.shell(
    name="Set timezone to UTC",
    commands=[
        "timedatectl set-timezone UTC || ln -sf /usr/share/zoneinfo/UTC /etc/localtime"
    ],
)

files.put(
    name="Enable unattended security upgrades",
    src=StringIO(
        'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n'
    ),
    dest="/etc/apt/apt.conf.d/20auto-upgrades",
)

# ---------------------------------------------------------------------------
# 2. Docker (official repository)
# ---------------------------------------------------------------------------
files.directory(name="Create apt keyrings dir", path="/etc/apt/keyrings", mode="755")

files.download(
    name="Download Docker apt key",
    src="https://download.docker.com/linux/ubuntu/gpg",
    dest="/etc/apt/keyrings/docker.asc",
    mode="644",
)

server.shell(
    name="Add Docker apt repository",
    commands=[
        ". /etc/os-release && echo "
        '"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] '
        'https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" '
        "> /etc/apt/sources.list.d/docker.list",
    ],
)

apt.update(name="Update apt cache (Docker repo)")

apt.packages(
    name="Install Docker Engine + compose plugin",
    packages=[
        "docker-ce",
        "docker-ce-cli",
        "containerd.io",
        "docker-buildx-plugin",
        "docker-compose-plugin",
    ],
)

docker_daemon = files.put(
    name="Configure Docker daemon (log rotation)",
    src=StringIO(
        '{\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "20m", "max-file": "5"}\n}\n'
    ),
    dest="/etc/docker/daemon.json",
)

systemd.service(
    name="Enable and start Docker", service="docker", running=True, enabled=True
)

systemd.service(
    name="Restart Docker after daemon.json change",
    service="docker",
    restarted=True,
    _if=docker_daemon.did_change,
)

# ---------------------------------------------------------------------------
# 3. Deploy user + application directory
# ---------------------------------------------------------------------------
server.user(
    name=f"Create {DEPLOY_USER} user",
    user=DEPLOY_USER,
    shell="/bin/bash",
    groups=["docker"],
    create_home=True,
    public_keys=DEPLOY_KEYS,
    delete_keys=True,
)

files.directory(
    name="Create application directory",
    path=APP_DIR,
    user=DEPLOY_USER,
    group=DEPLOY_USER,
    mode="750",
)

files.directory(
    name="Create TLS certificates directory",
    path=f"{APP_DIR}/certs",
    user=DEPLOY_USER,
    group=DEPLOY_USER,
    mode="700",
)

# ---------------------------------------------------------------------------
# 4. SSH hardening
# ---------------------------------------------------------------------------
# Recent Ubuntu releases use socket activation (ssh.service is inactive
# between connections), hence try-reload-or-restart.
sshd = files.put(
    name="Harden sshd",
    src=StringIO(
        "PasswordAuthentication no\n"
        "KbdInteractiveAuthentication no\n"
        f"PermitRootLogin {PERMIT_ROOT_LOGIN}\n"
    ),
    dest="/etc/ssh/sshd_config.d/10-showdesk.conf",
)

server.shell(
    name="Validate and reload sshd",
    commands=["sshd -t && systemctl try-reload-or-restart ssh.service"],
    _if=sshd.did_change,
)

# ---------------------------------------------------------------------------
# 5. Firewall
# ---------------------------------------------------------------------------
# UFW guards host services (SSH). Ports published by Docker bypass UFW, so
# HTTP(S) filtering lives in the DOCKER-USER chain, rebuilt at boot by a
# oneshot unit ordered after docker.service.
server.shell(
    name="UFW default policies",
    commands=["ufw default deny incoming", "ufw default allow outgoing"],
)

for cidr in SSH_ALLOW:
    server.shell(
        name=f"UFW allow SSH from {cidr}",
        commands=[f"ufw allow from {cidr} to any port 22 proto tcp"],
    )

server.shell(name="Enable UFW", commands=["ufw --force enable"])

if HTTP_ALLOW == "cloudflare":
    cidr_source = "{ curl -fsS https://www.cloudflare.com/ips-v4; echo; curl -fsS https://www.cloudflare.com/ips-v6; }"
elif HTTP_ALLOW:
    cidr_source = "printf '%s\\n' " + " ".join(HTTP_ALLOW)
else:
    cidr_source = None

if cidr_source:
    firewall_script = f"""#!/bin/sh
# Managed by pyinfra (deploy/pyinfra/bootstrap.py). Restricts ports 80/443
# published by Docker to an allow-list of source CIDRs.
set -eu
CIDRS=$({cidr_source} | grep -v '^$')
for ipt in iptables ip6tables; do
  $ipt -N DOCKER-USER 2>/dev/null || true
  $ipt -F DOCKER-USER
  $ipt -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
  for cidr in $CIDRS; do
    case "$cidr" in
      *:*) [ "$ipt" = ip6tables ] || continue ;;
      *) [ "$ipt" = iptables ] || continue ;;
    esac
    $ipt -A DOCKER-USER -p tcp -m multiport --dports 80,443 -s "$cidr" -j RETURN
  done
  $ipt -A DOCKER-USER -p tcp -m multiport --dports 80,443 -j DROP
  $ipt -A DOCKER-USER -j RETURN
done
"""
    files.put(
        name="Install HTTP(S) allow-list script",
        src=StringIO(firewall_script),
        dest="/usr/local/sbin/showdesk-http-firewall",
        mode="755",
    )
    files.put(
        name="Install HTTP(S) allow-list unit",
        src=StringIO(
            "[Unit]\n"
            "Description=Showdesk HTTP(S) source allow-list (DOCKER-USER)\n"
            "After=docker.service network-online.target\n"
            "Wants=network-online.target\n"
            "Requires=docker.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/usr/local/sbin/showdesk-http-firewall\n"
            "RemainAfterExit=yes\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        ),
        dest="/etc/systemd/system/showdesk-http-firewall.service",
    )
    systemd.service(
        name="Enable and apply HTTP(S) allow-list",
        service="showdesk-http-firewall",
        enabled=True,
        restarted=True,
        daemon_reload=True,
    )
else:
    systemd.service(
        name="Disable HTTP(S) allow-list (open to all)",
        service="showdesk-http-firewall",
        enabled=False,
        running=False,
        _ignore_errors=True,
    )

# ---------------------------------------------------------------------------
# 6. fail2ban
# ---------------------------------------------------------------------------
files.put(
    name="fail2ban sshd jail",
    src=StringIO(
        "[sshd]\nenabled = true\nbackend = systemd\nmaxretry = 5\nbantime = 1h\n"
    ),
    dest="/etc/fail2ban/jail.d/sshd.local",
)

systemd.service(
    name="Enable fail2ban",
    service="fail2ban",
    running=True,
    enabled=True,
    restarted=True,
)
