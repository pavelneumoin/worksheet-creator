"""Exact checks for a narrow numeric exercise grammar. No eval, symbolic guesses or units.

Only standalone 'Вычислите <one formula>' questions qualify. Word problems, equations,
variables, rounding instructions and uncertain recognition are left for the teacher.
"""
from fractions import Fraction
from math import isqrt
import re

TOKEN = re.compile(r'\d+(?:[.,]\d+)?|\\(?:dfrac|frac|sqrt|cdot|times|div)|[+*/^():{}-]')
QUESTION = re.compile(r'\s*(?:Вычислите(?: значение выражения)?|Найдите значение выражения)[:\s]*'
                      r'\$([^$]+)\$[.\s]*(?:Ответ запишите несократимой дробью[.\s]*)?', re.I)


class Unsupported(ValueError):
    pass


class Parser:
    def __init__(self, text):
        text = text.replace(r'\left', '').replace(r'\right', '').replace(r'\,', '').replace('−', '-')
        text = re.sub(r'\s+', '', text)
        if len(text) > 500:
            raise Unsupported()
        self.tokens = TOKEN.findall(text)
        if ''.join(self.tokens) != text or len(self.tokens) > 150:
            raise Unsupported()
        self.index = 0

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else ''

    def take(self):
        token = self.peek()
        if not token:
            raise Unsupported()
        self.index += 1
        return token

    def group(self):
        if self.take() != '{':
            raise Unsupported()
        result = self.expression()
        if self.take() != '}':
            raise Unsupported()
        return result

    def primary(self):
        token = self.peek()
        if token in (r'\frac', r'\dfrac'):
            self.take()
            return self.group() / self.group()
        if token == r'\sqrt':
            self.take(); value = self.group()
            if value < 0:
                raise Unsupported()
            a,b = isqrt(value.numerator),isqrt(value.denominator)
            if a*a != value.numerator or b*b != value.denominator:
                raise Unsupported()
            return Fraction(a,b)
        if token == '{':
            return self.group()
        if token == '(':
            self.take(); value = self.expression()
            if self.take() != ')':
                raise Unsupported()
            return value
        if not re.fullmatch(r'\d+(?:[.,]\d+)?', token) or len(token) > 20:
            raise Unsupported()
        return Fraction(self.take().replace(',', '.'))

    def unary(self):
        if self.peek() in ('+', '-'):
            sign = self.take()
            return (-1 if sign == '-' else 1) * self.unary()
        value = self.primary()
        if self.peek() == '^':
            self.take(); power = self.unary()
            if power.denominator != 1 or abs(power) > 12:
                raise Unsupported()
            value **= int(power)
        if value.numerator.bit_length() + value.denominator.bit_length() > 4096:
            raise Unsupported()
        return value

    def term(self):
        value = self.unary()
        while self.peek() in ('*', '/', ':', r'\cdot', r'\times', r'\div'):
            op = self.take(); other = self.unary()
            value = value / other if op in ('/', ':', r'\div') else value * other
        return value

    def expression(self):
        value = self.term()
        while self.peek() in ('+', '-'):
            op = self.take(); other = self.term()
            value = value + other if op == '+' else value - other
        return value


def evaluate(text):
    parser = Parser(text)
    result = parser.expression()
    if parser.peek():
        raise Unsupported()
    return result


def check_numeric_answers(worksheet):
    if worksheet['subject'] != 'math':
        return worksheet
    for task in worksheet['tasks']:
        match = QUESTION.fullmatch(task['question'])
        if not match or task['note']:
            continue
        try:
            answer = evaluate(match[1])
        except (Unsupported, ZeroDivisionError, RecursionError, OverflowError):
            continue
        value = str(answer.numerator) if answer.denominator == 1 else rf'\frac{{{answer.numerator}}}{{{answer.denominator}}}'
        task['answer'] = '$' + value + '$'
        task['note'] = 'Ответ к этому числовому выражению проверен точным вычислением. Сверьте само условие с источником.'
    return worksheet
