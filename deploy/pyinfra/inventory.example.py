"""Example pyinfra inventory for a single Showdesk host.

Copy to inventory.py (git-ignored) and adapt:

    cp deploy/pyinfra/inventory.example.py deploy/pyinfra/inventory.py
    pyinfra deploy/pyinfra/inventory.py deploy/pyinfra/bootstrap.py

The first run usually connects as root; afterwards you may set
permit_root_login = "no" and connect as the deploy user with sudo.
"""

hosts = [
    (
        "203.0.113.10",  # your server
        {
            "ssh_user": "root",
            "deploy_user": "deploy",
            "deploy_authorized_keys": [
                # Your own key, and the key used by your CI deploy job.
                "ssh-ed25519 AAAA... admin@example.com",
                "ssh-ed25519 AAAA... ci-deploy",
            ],
            "app_dir": "/opt/showdesk",
            # Restrict SSH to known networks if you can.
            "ssh_allow_cidrs": ["0.0.0.0/0", "::/0"],
            # None (open), a list of CIDRs, or "cloudflare" when the host sits
            # behind the Cloudflare proxy.
            "http_allow_cidrs": None,
            "permit_root_login": "prohibit-password",
        },
    ),
]
