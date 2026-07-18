"""Laboratory Framework foundation (U6, catalog/governance slice).

Versioned immutable Laboratory Manifest contracts, a capability-declaration
model that is explicitly *not* a permission system, and a deterministic
in-process registry. This package contains **no execution surface**: nothing
here runs missions, loads plugins, spawns agents, or grants authority. The
existing OrbitMind mission spine (intake -> orchestration -> verification ->
evidence -> approval) remains the sole governed execution path.
"""
