import pytest
from pydantic import ValidationError


def test_private_voice_tool_override_is_rejected_in_production():
    from clinic_voice_receptionist.config import VoiceSettings

    with pytest.raises(ValidationError, match="Private tool hosts"):
        VoiceSettings(_env_file=None, APP_ENV="production", tool_allow_private_hosts=True)
    assert VoiceSettings(_env_file=None, APP_ENV="dev", tool_allow_private_hosts=True).tool_allow_private_hosts
