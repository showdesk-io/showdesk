"""Custom S3 storage backend for Showdesk.

In Docker environments, the S3 endpoint (e.g. http://minio:9000) is an
internal hostname that browsers cannot resolve. This storage backend
rewrites generated URLs to use a public-facing endpoint so that presigned
URLs work from the browser.

Configure via environment variables:
    S3_ENDPOINT_URL   = http://minio:9000        (internal, for backend operations)
    S3_PUBLIC_URL     = http://localhost:9000     (external, for browser access)

When S3_PUBLIC_URL is not set, URLs are returned unchanged (e.g. production
where the endpoint is already publicly reachable).
"""

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class PublicURLS3Storage(S3Boto3Storage):
    """S3 storage that rewrites internal Docker URLs to public URLs."""

    def url(self, name, parameters=None, expire=None, http_method=None):
        url = super().url(name, parameters, expire, http_method)

        public_url = getattr(settings, "S3_PUBLIC_URL", "")
        internal_url = getattr(settings, "S3_ENDPOINT_URL", "")

        if public_url and internal_url and public_url != internal_url:
            url = url.replace(internal_url, public_url, 1)

        return url
