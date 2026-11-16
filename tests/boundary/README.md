# Boundary tests

Tests here pin **behaviour at the system's edges**, not its internals: end-to-end calls through
the public interface, and property-based invariants (for example with
[Hypothesis](https://hypothesis.readthedocs.io/)) that any correct implementation must satisfy.

They are the contract a rewrite has to meet. Unit tests may be deleted along with the module they
test; a boundary test may only change when the behaviour it pins is meant to change — and that
change belongs in an ADR.

What is here:

- `test_provider_contract.py`: the contract every vendor adapter must meet (ADR 0023). A new or
  swapped vendor is done when it passes; the engine's stages and records do not change for it.

Load tests do not belong in every stamp; add them here only if this project needs them.
