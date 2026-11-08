# Boundary tests (slot — off until filled)

Tests here pin **behaviour at the system's edges**, not its internals: end-to-end calls through
the public interface, and property-based invariants (for example with
[Hypothesis](https://hypothesis.readthedocs.io/)) that any correct implementation must satisfy.

They are the contract a rewrite has to meet. Unit tests may be deleted along with the module they
test; a boundary test may only change when the behaviour it pins is meant to change — and that
change belongs in an ADR.

Empty by default: pytest collects nothing here until a project adds a `test_*.py`. Load tests do
not belong in every stamp; add them here only if this project needs them.
