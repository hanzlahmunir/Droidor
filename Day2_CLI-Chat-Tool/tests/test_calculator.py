"""Calculator safety and correctness.

The security tests matter more than the arithmetic ones: the expression string
is written by the model, which can be influenced by fetched web pages, so this
is an untrusted-input boundary.
"""

import pytest

from app.tools.calculator import CalculatorError, calculate


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2+3", 5),
        ("10 / 4", 2.5),
        ("2**10", 1024),
        ("-5 + 3", -2),
        ("(2+3)*4", 20),
        ("7 % 3", 1),
        ("17 // 5", 3),
        ("2.5 * 4", 10.0),
    ],
)
def test_valid_arithmetic(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os").system("echo pwned")',  # RCE attempt
        'open("/etc/passwd").read()',  # file read
        "(1).__class__.__bases__",  # introspection escape
        "lambda: 1",  # callable construction
        "[i for i in range(10)]",  # comprehension
        "x + 1",  # name lookup
        '"a" * 100',  # string, not a number
        "True + 1",  # bool is an int subclass; still rejected
    ],
)
def test_code_execution_is_blocked(expression):
    """Every one of these is valid Python that eval() would happily run."""
    with pytest.raises(CalculatorError):
        calculate(expression)


def test_huge_exponent_is_refused():
    """2**999999999 does not raise -- it hangs while allocating. A DoS."""
    with pytest.raises(CalculatorError, match="Exponent too large"):
        calculate("2**999999999")


def test_division_by_zero_is_an_error_not_a_crash():
    with pytest.raises(CalculatorError, match="Division by zero"):
        calculate("1/0")


def test_overlong_expression_is_refused():
    with pytest.raises(CalculatorError, match="too long"):
        calculate("1+" * 400 + "1")


@pytest.mark.parametrize("expression", ["", "   ", None, 123])
def test_non_string_or_empty_input(expression):
    with pytest.raises(CalculatorError):
        calculate(expression)


def test_syntax_error_is_wrapped():
    """A parse failure must surface as CalculatorError, not SyntaxError."""
    with pytest.raises(CalculatorError, match="Could not parse"):
        calculate("2 +* 3")
