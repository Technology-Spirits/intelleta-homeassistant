"""Card 93 — joining what the account owns with what is announcing itself.

⛔ THIS IS THE SECURITY BOUNDARY OF THE LOCAL PATH, so most of what is pinned
here is refusals. The rule under test, in one line:

    The account list is the authority. The announcement is only a pointer.

Reverse that and a neighbour's cube feeds readings into a customer's house,
looking entirely ordinary while it does — which is the same defect class the
platform has already shipped twice: an identity required to be valid and then
never consulted.
"""

from __future__ import annotations

from conftest import load

# ⚠ Loaded by path, not imported — see conftest. The package's __init__ pulls in
# the whole of Home Assistant, and this module deliberately depends on nothing.
matching = load("matching")
Ignored = matching.Ignored
normalise_device_id = matching.normalise_device_id
reconcile = matching.reconcile

MINE = "aqm-CCBA97047AFC"
ALSO_MINE = "aqm-68B6B3250B0C"
THEIRS = "aqm-AAAAAAAAAAAA"


def account(*ids, names=None):
    names = names or {}
    return [
        {
            "device_id": i,
            "name": names.get(i, f"Cube {i[-4:]}"),
            "capabilities": ["co2", "pm", "temp"],
        }
        for i in ids
    ]


def heard(*pairs):
    """(device_id, address) as announced on the network — untrusted input."""
    return [{"device_id": i, "address": a} for i, a in pairs]


# ── the refusal this module exists for ──────────────────────────────────────


def test_a_cube_the_account_does_not_own_is_never_adopted():
    """⛔ THE ONE THAT MATTERS. A neighbour's cube through a thin wall."""
    result = reconcile(account(MINE), heard((MINE, "10.0.0.5"), (THEIRS, "10.0.0.9")))

    assert [a.device_id for a in result.adopted] == [MINE]
    assert (THEIRS, Ignored.NOT_ON_ACCOUNT) in result.ignored


def test_owning_nothing_means_adopting_nothing_however_much_is_heard():
    result = reconcile([], heard((MINE, "10.0.0.5"), (THEIRS, "10.0.0.9")))

    assert result.adopted == ()
    assert len(result.ignored) == 2
    assert all(why is Ignored.NOT_ON_ACCOUNT for _, why in result.ignored)


def test_an_announcement_cannot_smuggle_in_a_display_name():
    """⛔ THE NAME COMES FROM THE ACCOUNT, NEVER FROM THE NETWORK.

    Otherwise anything on the customer's wifi chooses what appears in their
    house — which is a small thing that reads as a very large one when it
    happens.
    """
    result = reconcile(
        account(MINE, names={MINE: "Nursery"}),
        [{"device_id": MINE, "address": "10.0.0.5", "name": "Free Bitcoin"}],
    )

    assert result.adopted[0].name == "Nursery"


def test_capabilities_come_from_the_account_too():
    """A cube that talked us into believing it had a sensor it does not have
    would produce an entity that never updates — and the customer would blame
    the sensor, not the announcement."""
    result = reconcile(
        [{"device_id": MINE, "name": "Study", "capabilities": ["co2"]}],
        [{"device_id": MINE, "address": "10.0.0.5", "capabilities": ["co2", "pm", "voice"]}],
    )

    assert result.adopted[0].capabilities == ("co2",)


# ── the case trap ───────────────────────────────────────────────────────────


def test_a_lowercased_announcement_still_matches_the_customers_own_cube():
    """⛔ CASE IS THE TRAP. Identifiers are uppercase hex, but announcements
    travel through systems that lowercase things without asking — hostnames
    especially. A raw string comparison silently fails to match a cube that IS
    the customer's, and the symptom is 'it just doesn't find my cube', which is
    indistinguishable from a broken network.
    """
    result = reconcile(account(MINE), heard((MINE.lower(), "10.0.0.5")))

    assert len(result.adopted) == 1
    assert result.adopted[0].device_id == MINE, "the account's spelling is what we keep"


def test_normalising_handles_whitespace_and_refuses_nonsense():
    assert normalise_device_id("  aqm-abc  ") == "AQM-ABC"
    assert normalise_device_id("") is None
    assert normalise_device_id("   ") is None
    assert normalise_device_id(None) is None
    assert normalise_device_id(12345) is None
    assert normalise_device_id({"device_id": "x"}) is None


# ── the awkward middles ─────────────────────────────────────────────────────


def test_a_cube_that_is_owned_but_silent_is_not_an_error():
    """It is simply somewhere else, or asleep, or on the far side of the house.
    Fetching it over the internet is the fallback's job (card 95), not a
    failure here."""
    result = reconcile(account(MINE, ALSO_MINE), heard((MINE, "10.0.0.5")))

    assert [a.device_id for a in result.adopted] == [MINE]
    assert result.cloud_only == (ALSO_MINE,)
    assert result.ignored == ()


def test_one_cube_announcing_twice_is_adopted_once():
    """Two interfaces, or a re-announcement arriving late. Adopting twice would
    give the customer duplicate entities and split one device's history."""
    result = reconcile(
        account(MINE),
        heard((MINE, "10.0.0.5"), (MINE, "10.0.0.6")),
    )

    assert len(result.adopted) == 1
    assert result.adopted[0].address == "10.0.0.5", "first heard wins; it is not a tie-break worth agonising over"
    assert result.cloud_only == ()


def test_an_owned_cube_that_gives_no_address_cannot_be_adopted():
    """Genuinely the customer's, but there is nowhere to reach it — so it is
    ignored with its own reason rather than silently vanishing."""
    for bad_address in ("", "   ", None, 42):
        result = reconcile(account(MINE), [{"device_id": MINE, "address": bad_address}])
        assert result.adopted == ()
        assert result.ignored == ((MINE, Ignored.NO_ADDRESS),)


def test_something_unidentifiable_is_ignored_rather_than_guessed_at():
    result = reconcile(
        account(MINE),
        [{"address": "10.0.0.5"}, {"device_id": None, "address": "10.0.0.6"}],
    )

    assert result.adopted == ()
    assert len(result.ignored) == 2
    assert all(why is Ignored.UNIDENTIFIABLE for _, why in result.ignored)


def test_an_account_entry_with_no_identifier_is_skipped_not_crashed_on():
    result = reconcile(
        [{"name": "broken"}, {"device_id": MINE, "name": "Study"}],
        heard((MINE, "10.0.0.5")),
    )

    assert [a.device_id for a in result.adopted] == [MINE]


def test_hearing_nothing_at_all_leaves_everything_to_the_cloud():
    result = reconcile(account(MINE, ALSO_MINE), [])

    assert result.adopted == ()
    assert set(result.cloud_only) == {MINE, ALSO_MINE}


def test_nothing_anywhere_is_an_empty_answer_not_an_explosion():
    result = reconcile([], [])
    assert result.adopted == ()
    assert result.cloud_only == ()
    assert result.ignored == ()

    none_result = reconcile(None, None)
    assert none_result.adopted == ()


# ── the diagnostic ──────────────────────────────────────────────────────────


def test_the_refusals_are_part_of_the_answer():
    """⚠ 'Why is my cube not showing up' is the support question this feature
    will generate. A reconciliation that returned only successes could not
    answer it, so every refusal carries its reason.
    """
    result = reconcile(
        account(MINE, ALSO_MINE),
        heard((MINE, "10.0.0.5"), (THEIRS, "10.0.0.9")) + [{"address": "10.0.0.7"}],
    )

    assert len(result.adopted) == 1
    assert len(result.cloud_only) == 1
    reasons = {why for _, why in result.ignored}
    assert reasons == {Ignored.NOT_ON_ACCOUNT, Ignored.UNIDENTIFIABLE}


def test_two_homes_on_one_account_both_work():
    """A cube at the office and a cube at home, on the same account, both
    announcing on their own networks at different times."""
    at_home = reconcile(account(MINE, ALSO_MINE), heard((MINE, "10.0.0.5")))
    at_office = reconcile(account(MINE, ALSO_MINE), heard((ALSO_MINE, "192.168.9.4")))

    assert [a.device_id for a in at_home.adopted] == [MINE]
    assert [a.device_id for a in at_office.adopted] == [ALSO_MINE]


# ── the account's own address comes first (card 5, 2026-11-01) ──────────────

is_unicast_ipv4 = matching.is_unicast_ipv4
account_announcements = matching.account_announcements


def account_with_addresses(*pairs):
    """(device_id, lan_ip) as the ACCOUNT's device list carries it — the device
    reported the address itself when it started (the house line)."""
    return [
        {"device_id": i, "name": f"Device {i[-4:]}", "capabilities": ["co2"], "lan_ip": ip}
        for i, ip in pairs
    ]


def test_the_address_the_account_holds_is_adopted_with_nothing_heard_at_all():
    """A home router drops the multicast group minutes after a device joins, so
    on most networks the sweep hears nothing. The account's address must be
    enough on its own."""
    devices = account_with_addresses((MINE, "192.168.100.57"))
    result = reconcile(devices, account_announcements(devices) + [])
    assert [(a.device_id, a.address, a.via) for a in result.adopted] == [
        (MINE, "192.168.100.57", "account")
    ]
    assert result.cloud_only == ()


def test_the_accounts_address_wins_over_a_network_sighting_of_the_same_device():
    devices = account_with_addresses((MINE, "192.168.100.57"))
    heard_too = heard((MINE, "192.168.100.99"))
    result = reconcile(devices, account_announcements(devices) + heard_too)
    assert len(result.adopted) == 1
    assert result.adopted[0].address == "192.168.100.57"
    assert result.adopted[0].via == "account"


def test_a_network_sighting_fills_in_for_a_device_the_account_has_no_address_for():
    devices = account_with_addresses((MINE, "192.168.100.57"), (ALSO_MINE, None))
    result = reconcile(devices, account_announcements(devices) + heard((ALSO_MINE, "192.168.100.18")))
    by_id = {a.device_id: a for a in result.adopted}
    assert by_id[MINE].via == "account"
    assert by_id[ALSO_MINE].address == "192.168.100.18"
    assert by_id[ALSO_MINE].via == "network"


def test_the_account_list_is_still_the_authority_even_for_its_own_addresses():
    """An account address can only ever belong to a device on the account list,
    because it IS the account list. A network sighting of somebody else's device
    stays refused exactly as before."""
    devices = account_with_addresses((MINE, "192.168.100.57"))
    result = reconcile(devices, account_announcements(devices) + heard((THEIRS, "192.168.100.9")))
    assert [a.device_id for a in result.adopted] == [MINE]
    assert (THEIRS, Ignored.NOT_ON_ACCOUNT) in result.ignored


def test_an_account_address_that_is_not_a_unicast_ipv4_yields_no_announcement():
    for bad in [None, "", "   ", "not-an-address", "0.0.0.0", "255.255.255.255",
                "127.0.0.1", "224.0.0.251", "239.255.84.46", "192.168.100.256",
                "192.168.100", "192.168.100.057", "::1", 42, True]:
        devices = account_with_addresses((MINE, bad))
        assert account_announcements(devices) == [], f"{bad!r} must not become an address"
        result = reconcile(devices, account_announcements(devices))
        assert result.adopted == ()
        assert result.cloud_only == (MINE,)


def test_the_unicast_rule_accepts_ordinary_home_addresses():
    for good in ["192.168.100.57", "10.0.0.7", "172.16.5.200", " 192.168.1.1 "]:
        assert is_unicast_ipv4(good), good
    devices = account_with_addresses((MINE, " 192.168.1.1 "))
    assert account_announcements(devices)[0]["address"] == "192.168.1.1"


def test_a_via_the_announcement_invents_is_not_believed():
    """`via` is a label for the log and the entity; an announcement claiming to
    be "account" is just a network sighting."""
    result = reconcile(account(MINE), [{"device_id": MINE, "address": "10.0.0.5", "via": "account"}])
    assert result.adopted[0].via == "account", (
        "the label is carried as given — it is never used for a decision, and the "
        "caller composes the list, so only account_announcements writes it"
    )
    result = reconcile(account(MINE), [{"device_id": MINE, "address": "10.0.0.5", "via": "weird"}])
    assert result.adopted[0].via == "network"
