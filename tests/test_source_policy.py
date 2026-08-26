"""Card 95 — falling back to the cloud without flapping.

⛔ THE HARD PART IS NOT FALLING BACK. A naive version switches source on every
missed reading and back on the next one, and the customer sees numbers jumping
between two slightly different values, timestamps going backwards, and history
with a seam in it. Every one of those reads as a broken product rather than as a
network having a bad minute.

So these tests are mostly about NOT switching.
"""

from __future__ import annotations

from conftest import load

policy = load("source_policy")
Source = policy.Source
SourceState = policy.SourceState
on_local_success = policy.on_local_success
on_local_failure = policy.on_local_failure
should_try_local = policy.should_try_local
accept_reading = policy.accept_reading
THRESHOLD = policy.LOCAL_FAILURES_BEFORE_FALLBACK
RETRY_AFTER = policy.RETRY_LOCAL_AFTER_S
RETRY_MAX = policy.RETRY_LOCAL_MAX_S


def fail_n(times, state=None, now=1000.0):
    state = state or SourceState()
    for _ in range(times):
        state = on_local_failure(state, now)
    return state


# ── not flapping ────────────────────────────────────────────────────────────


def test_a_single_missed_reading_does_not_move_the_customer_anywhere():
    """⛔ THE ONE THAT MATTERS MOST. One dropped packet must not produce a
    visible jump between two sources."""
    state = on_local_failure(SourceState(), now=1000.0)

    assert state.active is Source.LOCAL
    assert not state.using_fallback


def test_it_takes_several_consecutive_failures_to_fall_back():
    state = fail_n(THRESHOLD - 1)
    assert state.active is Source.LOCAL, "still blinking, not yet unwell"

    state = on_local_failure(state, now=1000.0)
    assert state.active is Source.CLOUD
    assert state.using_fallback


def test_one_success_anywhere_in_the_run_resets_the_count():
    """A link that misses, recovers, misses again is not a link that is down."""
    state = fail_n(THRESHOLD - 1)
    state = on_local_success(state)
    assert state.consecutive_failures == 0

    state = fail_n(THRESHOLD - 1, state)
    assert state.active is Source.LOCAL, "the earlier misses must not still count"


def test_the_cube_coming_back_returns_everything_to_normal():
    state = fail_n(THRESHOLD)
    assert state.using_fallback

    state = on_local_success(state)
    assert state.active is Source.LOCAL
    assert state.next_local_attempt_at is None
    assert state.backoff_s == RETRY_AFTER, "the next outage starts patient again"


# ── not hammering a network that is unwell ──────────────────────────────────


def test_while_local_is_working_we_simply_keep_polling_it():
    assert should_try_local(SourceState(), now=0.0) is True


def test_after_falling_back_it_waits_before_trying_the_cube_again():
    state = fail_n(THRESHOLD, now=1000.0)

    assert should_try_local(state, now=1000.0) is False
    assert should_try_local(state, now=1000.0 + RETRY_AFTER - 1) is False
    assert should_try_local(state, now=1000.0 + RETRY_AFTER) is True


def test_the_wait_grows_while_it_keeps_failing():
    """⚠ A cube that is switched off should not be probed every thirty seconds
    for hours — but one that was rebooting should be found again quickly."""
    state = fail_n(THRESHOLD, now=1000.0)
    first = state.backoff_s

    state = on_local_failure(state, now=2000.0)
    assert state.backoff_s > first

    state = on_local_failure(state, now=3000.0)
    assert state.backoff_s > first * 2


def test_the_wait_has_a_ceiling():
    state = fail_n(THRESHOLD, now=1000.0)
    for i in range(40):
        state = on_local_failure(state, now=2000.0 + i)

    assert state.backoff_s == RETRY_MAX, "backoff must not grow without limit"


def test_a_flapping_link_does_not_produce_flapping_readings():
    """The scenario the card names: a deliberately unreliable local endpoint.
    Two misses then a hit, over and over, must never reach the cloud at all."""
    state = SourceState()
    now = 0.0
    for _ in range(20):
        state = on_local_failure(state, now)
        state = on_local_failure(state, now + 1)
        state = on_local_success(state)
        now += 10

    assert state.active is Source.LOCAL
    assert not state.using_fallback


# ── never going backwards ───────────────────────────────────────────────────


def test_a_newer_reading_is_accepted_from_either_source():
    assert accept_reading(100, 101, Source.LOCAL) is True
    assert accept_reading(100, 101, Source.CLOUD) is True


def test_an_older_cloud_reading_never_lands_on_top_of_a_fresher_local_one():
    """⛔ THE RULE THAT MAKES THE SWITCH INVISIBLE. When local recovers, the
    cloud's in-flight copy of an older moment must not overwrite the fresh one
    and make the numbers jump backwards. That jump is what a customer reads as
    a broken product."""
    assert accept_reading(200, 150, Source.CLOUD) is False


def test_an_older_local_reading_is_refused_just_the_same():
    """⚠ Special-casing local to win would let a stale local read overwrite a
    fresher cloud one during recovery — the very inversion this prevents. The
    timestamp decides, and it does not care where the reading came from."""
    assert accept_reading(200, 150, Source.LOCAL) is False


def test_the_same_moment_twice_changes_nothing():
    """No new information, and swapping the visible source for nothing is a
    flicker with no upside."""
    assert accept_reading(200, 200, Source.CLOUD) is False
    assert accept_reading(200, 200, Source.LOCAL) is False


def test_the_first_reading_of_all_is_accepted():
    assert accept_reading(None, 100, Source.LOCAL) is True
    assert accept_reading(None, 100, Source.CLOUD) is True


def test_a_reading_that_cannot_be_placed_in_time_is_refused():
    """⛔ It cannot be shown to be newer, so it cannot be allowed to replace
    something that can. The device contract forbids publishing before time sync
    for the same reason."""
    assert accept_reading(100, None, Source.LOCAL) is False
    assert accept_reading(None, None, Source.CLOUD) is False


def test_the_customer_can_be_told_which_source_is_live():
    """⚠ A diagnostic, not an alarm. The difference between "my air is fine" and
    "I am looking at a copy because something on my network is broken"."""
    assert SourceState().using_fallback is False
    assert fail_n(THRESHOLD).using_fallback is True
