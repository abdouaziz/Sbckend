"""Numbers spelled out in French before speech synthesis."""
import pytest

from backend.services.numbers import numbers_to_french


@pytest.mark.parametrize("text, spoken", [
    ("am naa 3 xar", "am naa trois xar"),
    ("ci atum 2026", "ci atum deux mille vingt six"),
    ("15 mars 2026", "quinze mars deux mille vingt six"),
    ("71 ak 80 ak 81", "soixante et onze ak quatre vingts ak quatre vingt un"),
    ("10 000 dërëm", "dix mille dërëm"),
    ("1 500 000 fcfa", "un million cinq cent mille fcfa"),
    ("3,5 kilo", "trois virgule cinq kilo"),
    ("12,75", "douze virgule soixante quinze"),
    ("3,05", "trois virgule zéro cinq"),
    ("18 %", "dix huit pour cent"),
    ("2,5%", "deux virgule cinq pour cent"),
    ("1er janvier", "premier janvier"),
    ("1re fois", "première fois"),
    ("2e ak 21ème", "deuxième ak vingt et unième"),
    ("77 150 07 43", "soixante dix sept cent cinquante sept quarante trois"),
    ("1234567890123", "un deux trois quatre cinq six sept huit neuf zéro un deux trois"),
    ("amul benn limu", "amul benn limu"),
])
def test_numbers_are_spelled_out(text, spoken):
    assert numbers_to_french(text) == spoken


def test_no_digit_left():
    out = numbers_to_french("ndaje mi ci 12 fan ci weeru 3 atum 2024, 45,5 % ak 1er")
    assert not any(c.isdigit() for c in out)
