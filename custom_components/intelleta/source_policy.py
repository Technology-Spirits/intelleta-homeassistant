"""Which source a cube's readings come from, and when to change our mind. Card 95.

Readings come from the cube over the home network. When that cannot be reached
we fall back to our cloud rather than going blank.

⛔ THE HARD PART IS NOT FALLING BACK. IT IS NOT FLAPPING.

A naive version switches source on every missed reading and switches back on the
next one. The customer then sees numbers jumping between two slightly different
values, timestamps going backwards, and history with a seam in it — and every one
of those looks like a broken product rather than a network having a bad minute.

So three rules, all of them here rather than scattered through the coordinator:

  1. It takes several consecutive local failures to fall back, never one.
  2. Having fallen back, we wait before trying local again — and keep waiting
     longer if it keeps failing, rather than hammering a network that is
     evidently unwell.
  3. ⛔ A READING NEVER OVERWRITES A NEWER ONE. The timestamp decides which is
     fresher, never which arrived last. This is the rule that makes the switch
     invisible instead of visible.

⛔ THE CUBE IS THE TRUTH. Owner ruling 2026-08-25: where a local reading and a
cloud reading disagree, the cube wins — the cloud copy is a record of what the
cube said, and a copy never outranks the original. Rule 3 is where that ruling
becomes code: a cloud reading is accepted only when it is genuinely newer, so it
can fill a gap but never contradict the cube about the present.

No Home Assistant imports: this is a decision, and a decision is worth testing
on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Source(str, Enum):
    LOCAL = "local"
    """The cube itself, over the customer's own network."""

    CLOUD = "cloud"
    """Our copy of what the cube said. Used only when the cube cannot be reached."""


# How many consecutive local failures before falling back.
#
# ⚠ NOT ONE, AND NOT TEN. One means a single dropped packet moves the customer
# onto a different source, with a visible jump — the flapping this module exists
# to prevent. Ten means a genuinely unreachable cube leaves the numbers frozen
# for minutes while everything looks fine. Three consecutive misses is a link
# that is actually unwell rather than one that blinked.
LOCAL_FAILURES_BEFORE_FALLBACK = 3

# How long to stay on the cloud before trying the cube again, and the ceiling on
# that wait.
#
# ⚠ IT BACKS OFF. A cube that is off, or on a network segment that is down,
# should not be probed every thirty seconds for hours — but a cube that was
# rebooting should be found again quickly. Doubling from half a minute to a
# ceiling of ten does both.
RETRY_LOCAL_AFTER_S = 30
RETRY_LOCAL_MAX_S = 600


@dataclass(frozen=True)
class SourceState:
    """Where readings are coming from, and what we know about why."""

    active: Source = Source.LOCAL
    consecutive_failures: int = 0
    next_local_attempt_at: float | None = None
    """When it is worth trying the cube again. None means "right now"."""
    backoff_s: int = RETRY_LOCAL_AFTER_S

    @property
    def using_fallback(self) -> bool:
        """⚠ Worth surfacing to the customer as a diagnostic, not an alarm. The
        difference between "my air is fine" and "I am looking at a copy because
        something on my network is broken" is worth being able to see."""
        return self.active is Source.CLOUD


def on_local_success(state: SourceState) -> SourceState:
    """The cube answered. Everything resets."""
    return SourceState(
        active=Source.LOCAL,
        consecutive_failures=0,
        next_local_attempt_at=None,
        backoff_s=RETRY_LOCAL_AFTER_S,
    )


def on_local_failure(state: SourceState, now: float) -> SourceState:
    """The cube did not answer. Fall back only once it has failed enough times."""
    failures = state.consecutive_failures + 1

    if failures < LOCAL_FAILURES_BEFORE_FALLBACK and state.active is Source.LOCAL:
        # Not yet. Stay local and keep counting — a blink is not an outage.
        return replace(state, consecutive_failures=failures)

    # Already on the cloud, or just crossed the threshold. Either way, wait
    # longer before the next attempt than we did last time.
    backoff = state.backoff_s if state.active is Source.CLOUD else RETRY_LOCAL_AFTER_S
    if state.active is Source.CLOUD:
        backoff = min(backoff * 2, RETRY_LOCAL_MAX_S)

    return SourceState(
        active=Source.CLOUD,
        consecutive_failures=failures,
        next_local_attempt_at=now + backoff,
        backoff_s=backoff,
    )


def should_try_local(state: SourceState, now: float) -> bool:
    """Is it worth reaching for the cube right now?

    Always yes while we are still on the local path — that is simply the normal
    poll. On the cloud, only once the wait has elapsed.
    """
    if state.active is Source.LOCAL:
        return True
    if state.next_local_attempt_at is None:
        return True
    return now >= state.next_local_attempt_at


def accept_reading(
    current_timestamp: int | None,
    incoming_timestamp: int | None,
    incoming_source: Source,
) -> bool:
    """Should this reading replace what we are already showing?

    ⛔ THE TIMESTAMP DECIDES, NEVER THE ARRIVAL ORDER. A cloud reading is a
    record of something the cube said earlier; when the local path recovers, the
    cloud's in-flight copy of an older moment must not land on top of the fresh
    one and make the numbers jump backwards. That backwards jump is exactly what
    a customer reads as a broken product.

    Equal timestamps are refused too: the same moment carries no new
    information, and swapping the visible source for nothing is a flicker with
    no upside.
    """
    if incoming_timestamp is None:
        # ⛔ NOTHING TRUSTWORTHY TO ORDER BY. A reading we cannot place in time
        # cannot be shown to be newer, so it is not accepted — the device
        # contract forbids publishing before time sync for the same reason.
        return False

    if current_timestamp is None:
        # Nothing on screen yet. Anything with a real timestamp is an improvement.
        return True

    if incoming_timestamp > current_timestamp:
        return True

    # ⚠ A LOCAL READING NEVER LOSES TO ITSELF ON A TIE, and it does not need to:
    # refusing an equal-or-older reading from either source is the same rule,
    # applied without caring which source it came from. Special-casing LOCAL to
    # win ties would let a stale local read overwrite a fresher cloud one during
    # recovery — the very inversion this is meant to prevent.
    _ = incoming_source
    return False
