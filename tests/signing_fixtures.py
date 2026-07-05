"""Shared test-only signing fixture material.

The value below is deterministic, low-entropy, and used only to exercise
configured signing code paths in tests. It is not a credential.
"""

from __future__ import annotations

TEST_ONLY_EVIDENCE_SIGNING_MATERIAL = "orbitmind-test-fixture-signing-material-v1"
