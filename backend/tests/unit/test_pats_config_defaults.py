# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit tests pinning the ``PatsConfig`` defaults.

Phase 4 flipped ``enabled`` from ``False`` to ``True`` so fresh
deploys ship with PATs available. The other knobs (lifetime cap,
per-user cap, rate limit, audit sample rate, dormant warning) stay
where Phase 1 set them, but the test pins them too — a silent change
to any default would alter the behaviour of every deployment that
hasn't written a ``pats`` row yet, which is precisely the breakage
``app_settings`` defaults are designed to resist.
"""
from __future__ import annotations

from app.services.app_config import PatsConfig


def test_pats_enabled_defaults_to_true():
    """Phase 4 default. New deploys get PATs out of the box."""
    assert PatsConfig().enabled is True


def test_pats_other_defaults_pinned():
    cfg = PatsConfig()
    assert cfg.max_lifetime_days is None
    assert cfg.max_per_user == 50
    assert cfg.default_rate_limit_per_minute == 600
    assert cfg.use_audit_sample_rate == 0.02
    assert cfg.dormant_warning_days == 90
