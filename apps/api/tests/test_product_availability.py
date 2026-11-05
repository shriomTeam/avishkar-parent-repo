"""Product readiness is distinct from entitlement and role permissions."""

from clinic_core.features import load_features


def test_built_products_and_upcoming_stubs_are_declared_explicitly():
    features = load_features()
    built = {"blueprints", "lead_response", "reactivation", "voice_receptionist"}
    upcoming = {"command_center", "photos", "reviews", "scribe"}
    assert all(features[key].available for key in built & features.keys())
    assert all(not features[key].available for key in upcoming & features.keys())
    assert all(not features[key].trial_eligible for key in upcoming & features.keys())
    # Available is not the same as switched on: a new workspace must not receive it by itself.
    assert not features["lead_response"].trial_eligible
