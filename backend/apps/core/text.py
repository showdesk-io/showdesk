"""Small text helpers shared across apps."""

import re

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def one_line(value) -> str:
    """``value`` as one line of text, without the control characters Postgres refuses.

    Folding and tabs become single spaces; other control characters, such as NUL,
    go away. A mail header can't hold a line break either (a widget title can).
    """
    return _CONTROL_CHARACTERS.sub("", " ".join(str(value or "").split()))
