"""Numbers written in digits, spelled out in French words before speech synthesis.

The TTS models were trained on text without digits: in their vocabulary digits are
punctuation, so "2026" is not pronounced. Words are French, as Wolof and Pulaar
speakers commonly say numbers in French. Kept free of heavy imports so it can be
tested alone.
"""
import re

from num2words import num2words

# Above this, digits are read one by one (identifiers, phone numbers glued together).
MAX_CARDINAL = 10**12

# "10 000" or "1 500 000" (spaces, no-break spaces); not "77 150 07 43" (a phone number).
_GROUPED = re.compile(r"(?<![\d,.])\d{1,3}(?:[   ]\d{3})+(?![   ]?\d)")
_PERCENT = re.compile(r"(\d+(?:[,.]\d+)?)[   ]?%")
_ORDINAL = re.compile(r"\b(\d+)(ère|ere|re|er|ème|eme|e)\b")
_DECIMAL = re.compile(r"(\d+)[,.](\d+)")
_INTEGER = re.compile(r"\d+")


def _words(text: str) -> str:
    # Hyphens are punctuation for the models: they could make pauses inside a number.
    return text.replace("-", " ")


def _cardinal(digits: str) -> str:
    value = int(digits)
    if value >= MAX_CARDINAL:
        return " ".join(_words(num2words(int(d), lang="fr")) for d in digits)
    return _words(num2words(value, lang="fr"))


def _decimal(integer: str, fraction: str) -> str:
    # "3,05" → "trois virgule zéro cinq": leading zeros of the fraction are spoken.
    zeros = len(fraction) - len(fraction.lstrip("0"))
    rest = fraction.lstrip("0")
    spoken = ["zéro"] * zeros + ([_cardinal(rest)] if rest else [])
    return f"{_cardinal(integer)} virgule {' '.join(spoken)}"


def _ordinal(match: re.Match) -> str:
    value, suffix = int(match.group(1)), match.group(2)
    if value == 1:
        return "première" if suffix in ("re", "ère", "ere") else "premier"
    return _words(num2words(value, lang="fr", to="ordinal"))


def _number(text: str) -> str:
    match = _DECIMAL.fullmatch(text)
    return _decimal(*match.groups()) if match else _cardinal(text)


def numbers_to_french(text: str) -> str:
    """Spell out every number of `text` in French words."""
    text = _GROUPED.sub(lambda m: re.sub(r"[   ]", "", m.group()), text)
    text = _PERCENT.sub(lambda m: f"{_number(m.group(1))} pour cent", text)
    text = _ORDINAL.sub(_ordinal, text)
    text = _DECIMAL.sub(lambda m: _decimal(m.group(1), m.group(2)), text)
    return _INTEGER.sub(lambda m: _cardinal(m.group()), text)
