# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-authored HTML (email templates) → safe HTML.

CKEditor writes reasonably clean output, but we shouldn't trust it —
a compromised owner account could plant ``<script>``,
``onerror=…``, or ``javascript:`` URLs that execute for the next
admin to preview a template. Bleach strips everything outside the
allowed tag/attribute set and rewrites any non-http(s)/mailto URL
out of the document.

Jinja placeholders (``{{ ... }}`` / ``{% ... %}``) are preserved —
Bleach treats them as text, so template syntax survives the sanitise.
Variable *content* is separately escaped at render time by the Jinja
env (``autoescape=True``), so the defence is layered.
"""
from __future__ import annotations

import bleach

ALLOWED_TAGS = frozenset(
    [
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "li",
        "ol",
        "p",
        "pre",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    ]
)

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "th": ["align"],
    "td": ["align"],
}

ALLOWED_PROTOCOLS = frozenset(["http", "https", "mailto"])


def sanitise_template_body(html: str) -> str:
    """Strip dangerous tags / attributes / protocols from an owner-
    authored email template body. Safe input passes through unchanged
    (aside from whitespace normalisation that bleach does inside
    attributes — typical CKEditor output round-trips)."""
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
