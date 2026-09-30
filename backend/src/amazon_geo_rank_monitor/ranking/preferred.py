from collections.abc import Iterable


def preferred_observations(observations: Iterable[dict]) -> list[dict]:
    """One successful observation per run/ASIN/geo; strict supersedes managed.

    Callers provide persistence order, so equal verification levels keep the
    first record. `ok` is retained for legacy observations. Raw input is untouched.
    """
    selected: dict[tuple, dict] = {}
    for observation in observations:
        if observation.get("status") not in {"success_found", "success_not_found", "ok"}:
            continue
        key = (observation.get("run_id"), observation["asin"], observation["geo_profile_id"])
        current = selected.get(key)
        if current is None or (
            observation["verification_level"] == "strict"
            and current["verification_level"] != "strict"
        ):
            selected[key] = observation
    return list(selected.values())
