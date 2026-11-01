"""CORS for the widget, which runs on customers' sites."""

import re

WIDGET_ROUTE = re.compile(r"^/api/v1/(tickets|videos)/widget_[a-z_]+/$")


def allow_widget_routes(sender, request, **kwargs) -> bool:
    """Let any origin call the widget's routes.

    They authenticate with the widget's token and session, never a cookie: a page
    gains nothing from the browser's credentials, and the token is public anyway.
    """
    return bool(WIDGET_ROUTE.match(request.path_info))
