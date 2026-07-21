"""Operation Admission v0 — deterministic, non-executing admission policy (U7.4).

Operation Admission answers exactly one bounded question **before** anything runs:

    "May this proposed operation enter OrbitMind's controlled execution pipeline?"

It produces a deterministic admission decision (``admitted`` / ``denied`` /
``approval_required``) and confers nothing by itself. This package is the **pure
domain**: frozen contracts and a total, side-effect-free policy. It never runs a
tool, agent, provider, command, worktree, network call, or real-world action, it
reads no clock, and it does **not** import :mod:`orbitmind.authority` — Authority
evidence reaches the policy only as an already-distilled :class:`AuthorityFinding`
supplied by the orchestration bridge.
"""

from __future__ import annotations
