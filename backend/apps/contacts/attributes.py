"""Validation of custom attribute values against their definitions."""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.dateparse import parse_date, parse_datetime

logger = logging.getLogger(__name__)

_STRING_MAX = 1000
_url_validator = URLValidator(schemes=["http", "https"])


class _Invalid(Exception):
    pass


def _coerce(type_: str, value: Any, options: Any) -> Any:
    if type_ == "string":
        if isinstance(value, (dict, list)):
            raise _Invalid
        return str(value)[:_STRING_MAX]
    if type_ == "number":
        if isinstance(value, bool):
            raise _Invalid
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise _Invalid from exc
        if not math.isfinite(number):
            raise _Invalid
        return int(number) if number.is_integer() else number
    if type_ == "boolean":
        if not isinstance(value, bool):
            raise _Invalid
        return value
    if type_ == "date":
        if isinstance(value, (dict, list)):
            raise _Invalid
        if isinstance(value, date):
            return value.isoformat()[:10]
        text = str(value)
        try:
            parsed = parse_datetime(text) or parse_date(text)
        except ValueError as exc:
            raise _Invalid from exc
        if parsed is None:
            raise _Invalid
        return parsed.isoformat()[:10]
    if type_ == "enum":
        # Containers and booleans can only compare equal to an option by
        # accident (``True == 1``), and comparing deep containers can overflow
        # the stack. ``options`` is a free-form JSONField: trust no shape.
        if isinstance(value, (dict, list, bool)):
            raise _Invalid
        if not isinstance(options, list) or value not in options:
            raise _Invalid
        return value
    if type_ == "url":
        if isinstance(value, (dict, list)):
            raise _Invalid
        try:
            _url_validator(str(value))
        except ValidationError as exc:
            raise _Invalid from exc
        return str(value)
    raise _Invalid


def _is_storable(value: Any) -> bool:
    """Tell whether Postgres accepts ``value`` inside a ``jsonb`` column.

    ``jsonb`` rejects NUL characters and lone surrogates, both of which
    survive JSON parsing.
    """
    if not isinstance(value, str):
        return True
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def clean_attributes(definitions, values: Any) -> dict[str, Any]:
    """Return the subset of ``values`` that matches active ``definitions``.

    Unknown keys, archived definitions and values of the wrong type are
    dropped (and logged) instead of raising, so a host app sending extra
    traits never breaks the widget. ``None`` clears a value, and anything
    but a ``dict`` cleans to nothing.
    """
    if not isinstance(values, dict):
        return {}
    by_key = {d.key: d for d in definitions if not d.is_archived}
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        definition = by_key.get(key)
        if definition is None:
            logger.info("Dropping unknown attribute %r", key)
            continue
        if value is None:
            cleaned[key] = None
            continue
        try:
            coerced = _coerce(definition.type, value, definition.options)
        except _Invalid:
            logger.info("Dropping invalid value for attribute %r", key)
            continue
        if not _is_storable(coerced):
            logger.info("Dropping unstorable value for attribute %r", key)
            continue
        cleaned[key] = coerced
    return cleaned
