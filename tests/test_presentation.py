import pytest

from nisha.ui.presentation import uses_results


@pytest.mark.parametrize(
    "text",
    [
        "Hi",
        "Hey NISHA, how are you?",
        "How are you doing today?",
        "Tell me about yourself",
        "what are you doing?",
        "I am tired",
        "NISHA, just thinking",
        "My favorite color is green",
        "I enjoy robotics",
        "Don't disturb me",
        "open Claude",
        "open YouTube and search Dr Bro",
    ],
)
def test_dialogue_and_action_receipts_stay_at_orb(text):
    assert not uses_results(text, previous=True)


@pytest.mark.parametrize(
    "text",
    [
        "Explain photosynthesis",
        "Who is Dr Bro?",
        "Hey Nisha, tell me about Saturn",
        "Write an email to my supplier about delayed components",
        "I am the customer, write them an email to send the components soon",
        "Write code for a timer",
        "Write about robotics in Notepad",
        "Show me images of Saturn",
        "Compare these processors",
    ],
)
def test_information_and_artifacts_use_glass(text):
    assert uses_results(text)


@pytest.mark.parametrize("text", ["Make it shorter", "Continue", "Revise the greeting", "Send it"])
def test_result_followups_keep_presentation_context(text):
    assert uses_results(text, previous=True)
    assert not uses_results(text, previous=False)
