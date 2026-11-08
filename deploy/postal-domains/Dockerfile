# The Postal domains service, for running it as a compose service next to
# Postal (see README.md). It needs the Docker socket to reach Postal's web
# container, so it runs as root: never expose it but through the reverse proxy.
FROM python:3.13-alpine

RUN apk add --no-cache docker-cli \
  && mkdir -p -m 700 /var/lib/postal-domains

WORKDIR /app
COPY postal_domains.py postal_domains.rb ./

# The uuids of the domains it created: keep them across rebuilds (a volume).
VOLUME /var/lib/postal-domains

CMD ["python", "-u", "postal_domains.py"]
