"""Serializer building blocks keeping request bodies inside one organization."""

from rest_framework import serializers

from .permissions import get_active_org


def _organization_from_context(context: dict):
    """Return the organization a serializer works for, or None.

    Widget endpoints have no logged-in user and name it explicitly with an
    ``organization`` context key; everything else derives it from the request.
    """
    if "organization" in context:
        return context["organization"]
    request = context.get("request")
    return get_active_org(request) if request else None


class OrgScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """A primary key that only resolves to rows of the active organization.

    A row of another organization gives the same error as an unknown id, so
    ids can't be probed. With no organization in the serializer context,
    nothing resolves.

    ``org_field`` is the lookup from the related model to its organization.
    """

    def __init__(self, org_field: str = "organization", **kwargs):
        self.org_field = org_field
        super().__init__(**kwargs)

    def get_queryset(self):
        organization = _organization_from_context(self.context)
        queryset = super().get_queryset()
        if organization is None:
            return queryset.none()
        return queryset.filter(**{self.org_field: organization})


class ActiveOrgDefault:
    """Default for a read-only ``organization`` field set by the server.

    It lets DRF's ``unique_together`` validators see the organization, so a
    duplicate is a 400 and not a database error. The value itself still comes
    from the view's ``perform_create``.
    """

    requires_context = True

    def __call__(self, serializer_field):
        return _organization_from_context(serializer_field.context)


def read_only_organization_field() -> serializers.PrimaryKeyRelatedField:
    """Return an ``organization`` field that a request body can't set."""
    return serializers.PrimaryKeyRelatedField(
        read_only=True, default=ActiveOrgDefault()
    )
