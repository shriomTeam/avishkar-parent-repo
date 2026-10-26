"""Product readiness is distinct from entitlement and role permissions."""

from clinic_core.features import load_features


def test_built_products_and_upcoming_stubs_are_declared_explicitly():
    features = load_features()
    built = {"blueprints", "reactivation", "voice_receptionist"}
    upcoming = {"command_center", "lead_response", "photos", "reviews", "scribe"}
    assert all(features[key].available for key in built & features.keys())
    assert all(not features[key].available for key in upcoming & features.keys())
    assert all(not features[key].trial_eligible for key in upcoming & features.keys())
