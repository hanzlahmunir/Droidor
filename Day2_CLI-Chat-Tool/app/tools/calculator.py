"""A safe arithmetic evaluator.

WHY NOT eval(): the expression string is written by the LLM, which in turn can
be influenced by anything in the conversation -- including text fetched from a
web page. Passing that to eval() is remote code execution:

    __import__('os').system('rm -rf /')

is a perfectly valid Python expression. So we parse the string into an AST and
walk it, allowing ONLY arithmetic node types. Anything else -- names, calls,
attribute access, subscripts, comprehensions -- raises before evaluation.
This is an allowlist, not a blocklist: unknown node types are rejected by
default, so new Python syntax cannot silently open a hole.
"""

import ast
import operator
from typing import Any

# Allowlisted operators. Note the absence of anything that can touch the
# filesystem, network, or interpreter state -- these are pure number->number.
_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Guard against 2**999999999, which is not an error -- Python will happily try
# to allocate it and hang the CLI with no exception to catch. A denial of
# service, triggered by a single tool call.
_MAX_EXPONENT = 1000

# Same class of problem for the input itself: a megabyte-long expression costs
# real parse time. Legitimate calculator input is far below this.
_MAX_EXPRESSION_LENGTH = 500


class CalculatorError(ValueError):
    """Raised for any rejected or unevaluable expression."""


def _evaluate_node(node: ast.AST) -> float:
    """Recursively evaluate one allowlisted AST node."""
    # Numeric literal, e.g. `3` or `2.5`.
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            # bool is a subclass of int, so `True + 1` would otherwise work.
            # Rejecting it keeps the tool's contract strictly numeric.
            raise CalculatorError(f"Only numbers are allowed, got: {node.value!r}")
        return node.value

    # Binary operation, e.g. `2 + 3`.
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BIN_OPS:
            raise CalculatorError(f"Unsupported operator: {op_type.__name__}")

        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)

        if op_type is ast.Pow and abs(right) > _MAX_EXPONENT:
            raise CalculatorError(
                f"Exponent too large (max {_MAX_EXPONENT}); refusing to evaluate."
            )

        try:
            return _BIN_OPS[op_type](left, right)
        except ZeroDivisionError:
            raise CalculatorError("Division by zero.") from None
        except OverflowError:
            raise CalculatorError("Result too large to represent.") from None

    # Unary operation, e.g. `-5`.
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise CalculatorError(f"Unsupported unary operator: {op_type.__name__}")
        return _UNARY_OPS[op_type](_evaluate_node(node.operand))

    # Anything else (Name, Call, Attribute, Subscript, ...) is rejected here.
    raise CalculatorError(f"Unsupported expression element: {type(node).__name__}")


def calculate(expression: str) -> float:
    """Evaluate an arithmetic expression, raising CalculatorError if unsafe.

    Callers in tools/__init__.py convert the exception into an error string for
    the model; this function itself never returns an error sentinel, so the
    distinction between "computed 0.0" and "failed" is never ambiguous.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise CalculatorError("Expression must be a non-empty string.")

    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise CalculatorError(
            f"Expression too long (max {_MAX_EXPRESSION_LENGTH} characters)."
        )

    try:
        # mode="eval" accepts a single expression and rejects statements,
        # so `import os` fails at parse time rather than in our walker.
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"Could not parse expression: {exc.msg}") from None

    result = _evaluate_node(tree.body)

    # inf/nan are real float values that would propagate silently into the
    # conversation as "inf". Surfacing them as an error is more useful.
    if result != result or result in (float("inf"), float("-inf")):
        raise CalculatorError("Result is not a finite number.")

    return result
