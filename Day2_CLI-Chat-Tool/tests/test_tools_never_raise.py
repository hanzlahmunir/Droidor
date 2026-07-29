"""The brief's rule: tool errors must not crash the chat.

run_tool() is the single choke point where that rule is enforced, so these
tests assert the invariant directly: whatever goes in, a string comes out.
"""

from app.tools import TOOL_SCHEMAS, run_tool


class FakeConfig:
    tavily_api_key = None


def test_every_schema_has_a_handler():
    """A schema with no dispatch entry would look available and always fail."""
    for schema in TOOL_SCHEMAS:
        name = schema["function"]["name"]
        result = run_tool(name, {}, FakeConfig())
        # Missing args is fine here; an unknown-tool message is not.
        assert "unknown tool" not in result.lower(), f"{name} has no handler"


def test_unknown_tool_name_returns_guidance():
    """The model sometimes invents tool names; tell it what actually exists."""
    result = run_tool("definitely_not_a_tool", {}, FakeConfig())
    assert "unknown tool" in result.lower()
    assert "calculator" in result  # lists the real ones


def test_calculator_attack_becomes_an_error_string():
    result = run_tool(
        "calculator", {"expression": '__import__("os").system("x")'}, FakeConfig()
    )
    assert isinstance(result, str)
    assert result.startswith("Error:")


def test_blocked_url_becomes_an_error_string():
    result = run_tool("fetch_url", {"url": "http://169.254.169.254/"}, FakeConfig())
    assert isinstance(result, str)
    assert result.startswith("Error:")


def test_missing_arguments_do_not_raise():
    for name in ("calculator", "web_search", "fetch_url"):
        result = run_tool(name, {}, FakeConfig())
        assert isinstance(result, str)
        assert result.startswith("Error:")


def test_wrong_argument_types_do_not_raise():
    """The model can emit a number where a string is expected."""
    for name, args in [
        ("calculator", {"expression": 123}),
        ("fetch_url", {"url": ["not", "a", "string"]}),
        ("web_search", {"query": None}),
    ]:
        result = run_tool(name, args, FakeConfig())
        assert isinstance(result, str)
        assert result.startswith("Error:")
