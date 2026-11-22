"""Deterministic, offline utility plugins with bounded input and no eval()."""

import ast
import operator
import random
import re
from pathlib import Path
from uuid import uuid4

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_UNITS = {
    "mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1.0),
    "km": ("length", 1000.0), "in": ("length", 0.0254), "ft": ("length", 0.3048),
    "mi": ("length", 1609.344), "g": ("mass", 0.001), "kg": ("mass", 1.0),
    "lb": ("mass", 0.45359237), "oz": ("mass", 0.028349523125),
    "ml": ("volume", 0.001), "l": ("volume", 1.0), "cup": ("volume", 0.2365882365),
    "s": ("time", 1.0), "min": ("time", 60.0), "h": ("time", 3600.0),
    "day": ("time", 86400.0), "m/s": ("speed", 1.0), "km/h": ("speed", 1/3.6),
    "mph": ("speed", 0.44704),
}
_ALIASES = {"meter":"m", "meters":"m", "metre":"m", "metres":"m", "kilometer":"km", "kilometers":"km", "kilometre":"km", "kilometres":"km", "mile":"mi", "miles":"mi", "foot":"ft", "feet":"ft", "inch":"in", "inches":"in", "gram":"g", "grams":"g", "kilogram":"kg", "kilograms":"kg", "pound":"lb", "pounds":"lb", "ounce":"oz", "ounces":"oz", "liter":"l", "litre":"l", "liters":"l", "litres":"l", "milliliter":"ml", "millilitre":"ml", "minutes":"min", "minute":"min", "hours":"h", "hour":"h", "seconds":"s", "second":"s", "days":"day", "mph":"mph", "celsius":"c", "fahrenheit":"f", "kelvin":"k"}
TOOL_INSTRUCTIONS = (
    "calculate 12 * 3 | convert 5 km to miles | convert 0 celsius to fahrenheit | "
    "convert 1010 from binary to decimal | create a QR code for https://example.org | "
    "roll a die | pick a random number between 1 and 20 | rock paper scissors rock | I'm bored"
)


def _number(node, depth=0):
    if depth > 12:
        raise ValueError("Expression is too complex.")
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        value = node.value
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        value = _UNARY[type(node.op)](_number(node.operand, depth + 1))
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _number(node.left, depth + 1), _number(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("Exponents must be between -12 and 12.")
        value = _BINOPS[type(node.op)](left, right)
    else:
        raise ValueError("Use numbers and +, -, *, /, //, %, or ** only.")
    if abs(value) > 1e100:
        raise ValueError("The result is too large.")
    return value


def calculate(expression):
    expression = expression.replace("×", "*").replace("÷", "/").strip()
    if not expression or len(expression) > 120:
        raise ValueError("Enter a calculation under 120 characters.")
    tree = ast.parse(expression, mode="eval")
    result = _number(tree.body)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


def _unit(text):
    value = _ALIASES.get(text.casefold(), text.casefold())
    return value


def convert(amount, source, destination):
    source, destination = _unit(source), _unit(destination)
    if source in {"c", "f", "k"} and destination in {"c", "f", "k"}:
        celsius = amount if source == "c" else (amount - 32) * 5/9 if source == "f" else amount - 273.15
        result = celsius if destination == "c" else celsius * 9/5 + 32 if destination == "f" else celsius + 273.15
    else:
        if source not in _UNITS or destination not in _UNITS:
            raise ValueError("That unit isn't supported for offline conversion.")
        family, factor = _UNITS[source]
        other_family, other_factor = _UNITS[destination]
        if family != other_family:
            raise ValueError("Those units measure different things.")
        result = amount * factor / other_factor
    return f"{result:.8g} {destination}"


class LocalUtilities:
    """Small plugin registry. Handlers are exact, local and side-effect bounded."""

    def __init__(self, workspace, rng=None):
        self.workspace = Path(workspace)
        self.rng = rng or random.SystemRandom()

    def handle(self, text):
        value = text.strip().strip(".!?")
        if value.casefold() in {"show local utilities", "what offline tools can you use", "show available local tools"}:
            return "Available offline utilities:\n" + TOOL_INSTRUCTIONS
        match = re.fullmatch(r"(?:please )?(?:make|create|generate) (?:a )?(?:qr|qr code) for (.{1,2048})", value, re.IGNORECASE)
        if match:
            content = match[1].strip()
            if not content or any(ord(char) < 32 for char in content):
                return "QR content must be plain text or a URL without control characters."
            try:
                import segno

                self.workspace.mkdir(parents=True, exist_ok=True)
                path = self.workspace / f"nisha-qr-{uuid4().hex[:10]}.svg"
                segno.make(content, error="m").save(path, kind="svg", scale=6, border=2)
                return f"Created a QR code image.\nFile: {path}"
            except (ImportError, ValueError, OSError):
                return "I couldn't create the QR image. Check the local QR-code dependency and workspace folder."
        match = re.fullmatch(r"(?:please )?(?:calculate|compute)\s+(.{1,120})", value, re.IGNORECASE)
        if match:
            try:
                return "Result: " + calculate(match[1])
            except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
                return f"I couldn't calculate that safely: {exc}"
        match = re.fullmatch(r"(?:please )?convert\s+(-?\d+(?:\.\d+)?)\s+([a-zA-Z/]+)\s+to\s+([a-zA-Z/]+)", value, re.IGNORECASE)
        if match:
            try:
                return "Conversion: " + convert(float(match[1]), match[2], match[3])
            except ValueError as exc:
                return f"I couldn't convert that: {exc}"
        match = re.fullmatch(r"(?:convert )?(-?\d+(?:\.\d+)?)\s+from\s+(binary|hex|hexadecimal|decimal)\s+to\s+(binary|hex|hexadecimal|decimal)", value, re.IGNORECASE)
        if match:
            try:
                number, source, dest = match.groups()
                source = source.casefold()
                dest = dest.casefold()
                base = 2 if source == "binary" else 16 if source in {"hex", "hexadecimal"} else 10
                target = 2 if dest == "binary" else 16 if dest in {"hex", "hexadecimal"} else 10
                integer = int(number, base)
                answer = format(integer, "b") if target == 2 else format(integer, "x") if target == 16 else str(integer)
                return f"Conversion: {answer}"
            except ValueError:
                return "I couldn't convert that: the number doesn't match its stated base."
        match = re.fullmatch(r"(?:please )?(?:roll|throw) (?:a |one )?(?:die|dice)", value, re.IGNORECASE)
        if match:
            return f"You rolled {self.rng.randint(1, 6)}."
        match = re.fullmatch(r"(?:please )?(?:play )?rock paper scissors(?: (rock|paper|scissors))?", value, re.IGNORECASE)
        if match:
            user = (match[1] or "").casefold()
            if not user:
                return "Choose rock, paper, or scissors."
            computer = self.rng.choice(("rock", "paper", "scissors"))
            result = "draw" if user == computer else "you win" if (user, computer) in {("rock","scissors"),("paper","rock"),("scissors","paper")} else "I win"
            return f"You chose {user}; I chose {computer}. {result.capitalize()}!"
        if value.casefold() in {"i'm bored", "im bored", "i am bored", "entertain me"}:
            return "Try a quick game: say ‘rock paper scissors rock’, ask me for a random number, or ask for a fun fact."
        match = re.fullmatch(r"(?:pick|choose) (?:a )?random number between (-?\d+) and (-?\d+)", value, re.IGNORECASE)
        if match:
            low, high = int(match[1]), int(match[2])
            if low > high or high - low > 10**9:
                return "Give me an increasing range no wider than one billion."
            return f"Random number: {self.rng.randint(low, high)}"
        return None
