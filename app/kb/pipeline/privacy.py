"""Remove personal data from internal text before it is embedded.

Internal sources (tickets, and later technician notes or SOPs) contain text
people typed. Anything stored in the knowledge base can be shown to every
caller the source's scope allows, so personal data is removed first, not
filtered later (data minimisation).

Removed: email addresses, phone numbers (Sri Lankan and international
formats), Sri Lankan NIC numbers, and the full names of known staff when a
list of names is given. Vehicle registration plates are not personal data
here (they identify company vehicles) and are kept.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Pattern

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
# +94 77 123 4567, 0771234567, 077-123-4567, 011 2345678, +44 20 7946 0958
_PHONE = re.compile(r"(?<![\w-])(\+\d{1,3}[\s-]?)?(\(?0?\d{2,3}\)?[\s-]?)\d{3}[\s-]?\d{4}(?![\w-])")
# Old NIC: 9 digits + V/X; new NIC: 12 digits.
_NIC = re.compile(r"\b(\d{9}[VvXx]|\d{12})\b")


class Redactor:
    """Compiled once per run: the staff-name pattern covers every name at once."""

    def __init__(self, names: Iterable[str] = ()) -> None:
        unique = sorted({n.strip() for n in names if n and len(n.strip()) >= 5}, key=len, reverse=True)
        self._names: Optional[Pattern[str]] = (
            re.compile(r"\b(" + "|".join(re.escape(n) for n in unique) + r")\b", re.IGNORECASE)
            if unique else None
        )

    def __call__(self, text: str) -> str:
        text = _EMAIL.sub("[email removed]", text)
        text = _NIC.sub("[ID number removed]", text)
        text = _PHONE.sub("[phone removed]", text)
        if self._names is not None:
            text = self._names.sub("[name removed]", text)
        return text


def redact(text: str, names: Iterable[str] = ()) -> str:
    """`text` with personal data replaced by neutral placeholders (one-off use)."""
    return Redactor(names)(text)
