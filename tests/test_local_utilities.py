import random

import pytest

from nisha.local_utilities import LocalUtilities, calculate, convert


def test_safe_calculator_and_reject_python_execution():
    assert calculate("(8 + 4) / 3") == "4"
    with pytest.raises((SyntaxError, ValueError)):
        calculate("__import__('os').system('whoami')")


def test_common_unit_and_temperature_conversions():
    assert convert(5, "km", "miles") == "3.106856 mi"
    assert convert(0, "celsius", "fahrenheit") == "32 f"
    with pytest.raises(ValueError, match="different things"):
        convert(1, "kg", "km")


def test_local_utility_commands_are_explicit_and_deterministic(tmp_path):
    tools = LocalUtilities(tmp_path, random.Random(7))
    assert tools.handle("calculate 12 * 3") == "Result: 36"
    assert tools.handle("convert 1010 from binary to decimal") == "Conversion: 10"
    assert tools.handle("roll a die").startswith("You rolled ")
    assert "Choose rock, paper, or scissors" in tools.handle("rock paper scissors")
    assert "quick game" in tools.handle("I'm bored")
    assert tools.handle("tell me about unit conversion") is None


def test_qr_code_is_saved_as_local_svg(tmp_path):
    result = LocalUtilities(tmp_path).handle("create a QR code for https://example.org")
    path = tmp_path / result.split("File: ", 1)[1]
    assert result.startswith("Created a QR code")
    assert path.is_file() and "<svg" in path.read_text(encoding="utf-8")
