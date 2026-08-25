"""Per-member tolerance, and why it is not an aggregate (FR-031, FR-031a)."""

from ticket_dataset_generator.planning.tolerance import attribute, check

REQUESTED = {
    "category": {
        "billing": 0.25,
        "technical": 0.25,
        "account": 0.20,
        "shipping": 0.15,
        "product": 0.10,
        "other": 0.05,
    },
    "priority": {"normal": 1.0},
    "channel": {"email": 1.0},
    "resolution_status": {"resolved": 1.0},
}


def _achieved(**category_overrides) -> dict:
    achieved = {dim: dict(dist) for dim, dist in REQUESTED.items()}
    achieved["category"].update(category_overrides)
    return achieved


def test_an_exact_match_passes() -> None:
    assert check(REQUESTED, REQUESTED, 2.0) == []


def test_drift_inside_the_tolerance_passes() -> None:
    assert check(REQUESTED, _achieved(billing=0.261, technical=0.239), 2.0) == []


def test_the_worst_member_decides() -> None:
    # shipping is 2.4pp light while everything else is tight; the dimension fails.
    breaches = check(REQUESTED, _achieved(shipping=0.126, billing=0.262, technical=0.262), 2.0)
    assert [b.member for b in breaches] == ["shipping"]


def test_a_failure_names_the_member_and_its_drift() -> None:
    breach = check(REQUESTED, _achieved(shipping=0.126, billing=0.262, technical=0.262), 2.0)[0]
    assert breach.dimension == "category"
    assert breach.member == "shipping"
    assert round(breach.drift_pp, 2) == 2.40
    assert "shipping" in breach.describe()
    assert "2.40pp" in breach.describe()


def test_an_aggregate_passing_distribution_can_still_fail_per_member() -> None:
    # The reason the requirement is per member: averaged over six categories this drift is well
    # under 2pp, while shipping is 5pp light. Someone slicing the corpus by shipping cares.
    achieved = _achieved(shipping=0.10, billing=0.30)
    mean_drift_pp = (
        sum(abs(achieved["category"][m] - REQUESTED["category"][m]) for m in REQUESTED["category"])
        / len(REQUESTED["category"])
        * 100
    )
    assert mean_drift_pp < 2.0, "the aggregate would pass"
    assert [b.member for b in check(REQUESTED, achieved, 2.0)] == ["billing", "shipping"]


def test_a_member_missing_from_the_corpus_entirely_is_a_breach() -> None:
    achieved = _achieved()
    del achieved["category"]["other"]
    achieved["category"]["billing"] = 0.30
    breaches = {b.member for b in check(REQUESTED, achieved, 2.0)}
    assert "other" in breaches


def test_every_dimension_is_checked() -> None:
    achieved = {dim: dict(dist) for dim, dist in REQUESTED.items()}
    achieved["channel"] = {"email": 0.9, "chat": 0.1}
    assert {b.dimension for b in check(REQUESTED, achieved, 2.0)} == {"channel"}


def test_a_widened_tolerance_absorbs_the_drift() -> None:
    assert check(REQUESTED, _achieved(shipping=0.10, billing=0.30), 10.0) == []


# --- attribution (FR-031a) -------------------------------------------------------------------


def test_apportionment_error_is_separated_from_discard_drift() -> None:
    # Requested to assigned is what apportionment could not represent; assigned to achieved is
    # what discards took away. The two call for entirely different responses.
    assigned = {dim: dict(dist) for dim, dist in REQUESTED.items()}
    achieved = _achieved(shipping=0.10)
    attribution = attribute(REQUESTED, assigned, achieved)
    # Apportionment was exact here, so all the drift belongs to discards.
    assert attribution["category"]["shipping"] == 0.0


def test_apportionment_error_shows_when_it_exists() -> None:
    assigned = {dim: dict(dist) for dim, dist in REQUESTED.items()}
    assigned["category"]["shipping"] = 0.14  # a small corpus could not represent 0.15
    attribution = attribute(REQUESTED, assigned, REQUESTED)
    assert round(attribution["category"]["shipping"], 2) == -1.0
