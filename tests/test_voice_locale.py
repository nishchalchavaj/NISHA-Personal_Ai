from types import SimpleNamespace

from nisha.voice import WindowsSpeech


def test_indian_english_voice_is_preferred_when_installed():
    voices = [
        SimpleNamespace(name="Microsoft Zira", id="en-US", languages=["en-US"]),
        SimpleNamespace(name="Indian English Female", id="en-IN", languages=["en-IN"]),
    ]
    assert WindowsSpeech(voice_locale="en-IN").choose_voice(voices) == "en-IN"
    assert WindowsSpeech(voice_locale="en-GB").choose_voice(voices) == "en-US"
