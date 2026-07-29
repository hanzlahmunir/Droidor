"""The /tool command: invoke a tool with no model in the loop.

This exists because a real chat session showed the security guards were never
reached -- the model refused on its own, so `[tool]` never appeared and the AST
allowlist and SSRF check were never exercised. Right outcome, wrong reason: a
model refusal is a soft layer that can be prompted around, and it proves
nothing about the hard guard underneath.
"""

from app.cli import _run_tool_directly


class FakeConfig:
    tavily_api_key = None


def test_valid_call_returns_result(capsys):
    _run_tool_directly('/tool calculator {"expression": "2+2"}', FakeConfig())
    out = capsys.readouterr().out
    assert "2+2 = 4" in out


def test_code_execution_attempt_is_blocked(capsys):
    _run_tool_directly(
        '/tool calculator {"expression": "__import__(\'os\').system(\'x\')"}',
        FakeConfig(),
    )
    out = capsys.readouterr().out
    # The specific reason matters: it shows the allowlist rejected the node
    # type, not that some generic error happened to occur.
    assert "Error" in out and "Call" in out


def test_ssrf_target_is_blocked(capsys):
    _run_tool_directly(
        '/tool fetch_url {"url": "http://169.254.169.254/latest/meta-data/"}',
        FakeConfig(),
    )
    out = capsys.readouterr().out
    assert "non-public address" in out


def test_bare_command_prints_help(capsys):
    _run_tool_directly("/tool", FakeConfig())
    assert "call a tool directly" in capsys.readouterr().out


def test_malformed_json_does_not_raise(capsys):
    _run_tool_directly("/tool calculator not-json", FakeConfig())
    assert "could not parse arguments" in capsys.readouterr().out


def test_non_object_json_is_rejected(capsys):
    """A JSON array parses fine but is not a valid argument mapping."""
    _run_tool_directly('/tool calculator ["expression"]', FakeConfig())
    assert "could not parse arguments" in capsys.readouterr().out


def test_unknown_tool_lists_the_real_ones(capsys):
    _run_tool_directly('/tool nosuchtool {"x": 1}', FakeConfig())
    out = capsys.readouterr().out
    assert "unknown tool" in out
    assert "calculator" in out
