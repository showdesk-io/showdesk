"""Filter building blocks keeping query strings inside one organization."""

from .permissions import get_active_org


def active_org_rows(model):
    """Return a filter ``queryset`` callable limited to the active organization.

    An id of another organization is then an invalid choice, like an unknown one.
    """

    def queryset(request):
        organization = get_active_org(request) if request else None
        if organization is None:
            return model.objects.none()
        return model.objects.filter(organization=organization)

    return queryset
