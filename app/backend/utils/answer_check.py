"""Conservative hints for final answers; never a confirmed grade or expression eval."""
from fractions import Fraction
import re


def normalized(value):
    text = value.strip().replace('$', '').replace('−', '-').replace('–', '-')
    text = re.sub(r'\\(?:text|mathrm)\{([^{}]*)\}', r'\1', text)
    text = re.sub(r'\\(?:,|;|!|quad|qquad)', '', text)
    text = re.sub(r'([0-9])\{,\}([0-9])', r'\1.\2', text)
    return re.sub(r'\s+', '', text).replace(',', '.')


def number(value):
    text = normalized(value)
    text = re.sub(r'^[a-zA-Z]=', '', text)
    text = re.sub(r'\\(?:d?frac)\{(-?\d+)\}\{(-?\d+)\}', r'\1/\2', text)
    if len(text) > 100 or not re.fullmatch(r'[+-]?\d+(?:\.\d+|/[+-]?\d+)?', text):
        return None
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def hint(expected, observed, state):
    if state != 'readable' or not expected.strip() or not observed.strip():
        return {'suggested_score': None, 'comparison': 'manual'}
    left, right = number(expected), number(observed)
    equal = left == right if left is not None and right is not None else normalized(expected) == normalized(observed)
    # A difference is a reason to ask the teacher, never an automatic zero.
    return {'suggested_score': 1 if equal else None, 'comparison': 'matches' if equal else 'manual'}
