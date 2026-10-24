"""Shared test setup: Hypothesis profile and fictional phone numbers."""

from hypothesis import settings

# Repeatable runs for the required-pbt hook (design.md, Testing Strategy).
settings.register_profile(
    "lifeline", max_examples=100, deadline=None, derandomize=True
)
settings.load_profile("lifeline")

# Reserved fictional numbers only: +1 617 555 0100 to +1 617 555 0199 (Req 26.6).
FICTIONAL_NUMBERS: tuple[str, ...] = tuple(
    f"+1617555{n:04d}" for n in range(100, 200)
)
