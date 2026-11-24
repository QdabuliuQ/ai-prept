"""Tool calling 双模：原生 tools + 伪协议兜底。

为什么必须双模：项目跑在多厂商网关上，``tools`` 参数兼容性参差；
Agent Loop 一旦依赖 tool calling，网关不支持就直接瘫痪。
伪协议（JSON 描述动作）网关无关，必然可用。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import llm

TOOLS = [
    {
        "name": "write_plan",
        "description": "提交规划",
        "parameters": {"type": "object", "properties": {"plan": {"type": "object"}}},
    }
]


# ---------------------------------------------------------------------------
# 伪协议解析
# ---------------------------------------------------------------------------


def test_pseudo_reply_parses_action() -> None:
    reply = llm._parse_pseudo_reply(
        json.dumps(
            {"thought": "先规划", "action": {"name": "write_plan", "args": {"plan": {"a": 1}}}},
            ensure_ascii=False,
        )
    )
    assert reply.mode == "pseudo"
    assert len(reply.calls) == 1
    assert reply.calls[0].name == "write_plan"
    assert reply.calls[0].args == {"plan": {"a": 1}}
    assert reply.calls[0].thought == "先规划"


def test_pseudo_reply_tolerates_code_fence() -> None:
    raw = '```json\n{"action": {"name": "finish", "args": {}}}\n```'
    reply = llm._parse_pseudo_reply(raw)
    assert reply.calls[0].name == "finish"


def test_pseudo_reply_tolerates_prose_wrapping() -> None:
    raw = '好的，我这样处理：{"action": {"name": "finish", "args": {}}} 完成。'
    reply = llm._parse_pseudo_reply(raw)
    assert reply.calls[0].name == "finish"


def test_pseudo_reply_tolerates_trailing_comma() -> None:
    raw = '{"action": {"name": "finish", "args": {},},}'
    reply = llm._parse_pseudo_reply(raw)
    assert reply.calls[0].name == "finish"


def test_pseudo_reply_plain_text_has_no_calls() -> None:
    reply = llm._parse_pseudo_reply("我觉得这页应该改成两栏")
    assert reply.calls == []
    assert reply.text


def test_pseudo_reply_missing_args_defaults_empty() -> None:
    reply = llm._parse_pseudo_reply('{"action": {"name": "read_plan"}}')
    assert reply.calls[0].args == {}


def test_pseudo_reply_missing_action_name_has_no_calls() -> None:
    reply = llm._parse_pseudo_reply('{"action": {"args": {"x": 1}}}')
    assert reply.calls == []


def test_pseudo_reply_non_object_args_ignored() -> None:
    reply = llm._parse_pseudo_reply('{"action": {"name": "x", "args": "not-a-dict"}}')
    assert reply.calls[0].args == {}


# ---------------------------------------------------------------------------
# 工具结果编码：两种模式的回路形状不同
# ---------------------------------------------------------------------------


def test_tool_result_native_uses_tool_role() -> None:
    reply = llm.ToolReply(mode="native")
    call = llm.ToolCall(name="write_plan", call_id="call_1")
    msgs = llm.tool_result_messages(reply, call, {"ok": True})
    assert msgs[0]["role"] == "tool"
    assert msgs[0]["tool_call_id"] == "call_1"


def test_tool_result_pseudo_uses_user_role() -> None:
    """网关不认识 tool 角色，伪协议必须用普通 user 消息回灌。"""
    reply = llm.ToolReply(mode="pseudo")
    call = llm.ToolCall(name="write_plan")
    msgs = llm.tool_result_messages(reply, call, {"ok": False, "error": "重叠 34px"})
    assert msgs[0]["role"] == "user"
    assert "重叠 34px" in msgs[0]["content"]
    assert "write_plan" in msgs[0]["content"]


def test_tool_result_payload_is_json() -> None:
    reply = llm.ToolReply(mode="pseudo")
    call = llm.ToolCall(name="x")
    payload = {"ok": True, "items": [1, 2], "中文": "值"}
    content = llm.tool_result_messages(reply, call, payload)[0]["content"]
    assert "中文" in content and "值" in content


# ---------------------------------------------------------------------------
# 工具 schema 归一化
# ---------------------------------------------------------------------------


def test_tool_specs_wraps_plain_definition() -> None:
    specs = llm._tool_specs(TOOLS)
    assert specs[0]["type"] == "function"
    assert specs[0]["function"]["name"] == "write_plan"


def test_tool_specs_passes_through_openai_shape() -> None:
    already = {"type": "function", "function": {"name": "x", "parameters": {}}}
    specs = llm._tool_specs([already])
    assert specs[0] is already


def test_tool_specs_defaults_parameters() -> None:
    specs = llm._tool_specs([{"name": "x"}])
    assert specs[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_tool_list_for_prompt_mentions_all_tools() -> None:
    text = llm._tool_list_for_prompt(TOOLS)
    assert "write_plan" in text
    assert "提交规划" in text


# ---------------------------------------------------------------------------
# prefer 模式与降级
# ---------------------------------------------------------------------------


def test_chat_tools_rejects_bad_prefer() -> None:
    with pytest.raises(ValueError):
        llm.chat_tools(
            model="m", messages=[], tools=TOOLS, prefer="magic", pool=None, client=None
        )


def test_unsupported_error_detection() -> None:
    assert llm._looks_like_tool_unsupported(Exception("tools parameter unsupported"))
    assert llm._looks_like_tool_unsupported(Exception("unknown parameter: tools"))
    assert llm._looks_like_tool_unsupported(Exception("invalid_request_error"))
    assert not llm._looks_like_tool_unsupported(Exception("rate limit exceeded"))


def test_auto_mode_falls_back_to_pseudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """原生失败且明确是"不支持 tools" → 自动降级伪协议。"""

    def boom(**_kw: Any) -> llm.ToolReply:
        raise RuntimeError("tools parameter unsupported by this gateway")

    monkeypatch.setattr(llm, "_chat_tools_native", boom)
    seen: dict[str, Any] = {}

    def fake_pseudo(**kw: Any) -> llm.ToolReply:
        seen.update(kw)
        return llm.ToolReply(mode="pseudo")

    monkeypatch.setattr(llm, "_chat_tools_pseudo", fake_pseudo)
    reply = llm.chat_tools(model="m", messages=[], tools=TOOLS, client=object())  # type: ignore[arg-type]
    assert reply.mode == "pseudo"
    assert seen["tools"] == TOOLS


def test_auto_mode_does_not_mask_unrelated_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """限流/超时这类错误不能被误判为"不支持 tools"而静默降级。"""

    def boom(**_kw: Any) -> llm.ToolReply:
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(llm, "_chat_tools_native", boom)
    monkeypatch.setattr(
        llm, "_chat_tools_pseudo", lambda **_kw: llm.ToolReply(mode="pseudo")
    )
    with pytest.raises(RuntimeError, match="rate limit"):
        llm.chat_tools(model="m", messages=[], tools=TOOLS, client=object())  # type: ignore[arg-type]


def test_native_mode_raises_instead_of_falling_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_kw: Any) -> llm.ToolReply:
        raise RuntimeError("tools parameter unsupported")

    monkeypatch.setattr(llm, "_chat_tools_native", boom)
    with pytest.raises(RuntimeError):
        llm.chat_tools(
            model="m", messages=[], tools=TOOLS, prefer="native", client=object()  # type: ignore[arg-type]
        )


def test_pseudo_mode_skips_native(monkeypatch: pytest.MonkeyPatch) -> None:
    """A/B 时用 pseudo 消除协议差异，不应试探原生。"""
    called = {"native": False}

    def native(**_kw: Any) -> llm.ToolReply:
        called["native"] = True
        return llm.ToolReply(mode="native")

    monkeypatch.setattr(llm, "_chat_tools_native", native)
    monkeypatch.setattr(
        llm, "_chat_tools_pseudo", lambda **_kw: llm.ToolReply(mode="pseudo")
    )
    reply = llm.chat_tools(
        model="m", messages=[], tools=TOOLS, prefer="pseudo", client=object()  # type: ignore[arg-type]
    )
    assert reply.mode == "pseudo"
    assert called["native"] is False


def test_native_reply_trims_extra_tool_calls():
    """模型并行发多个 tool_calls 时，assistant 消息只留第一个。

    Agent Loop 每轮只执行一个工具；若历史里留下 2 个 tool_calls 却只回一条
    role=tool，网关下一轮会直接 400 No tool output found for tool call call_xx。
    """
    from types import SimpleNamespace

    from llm import _chat_tools_native

    def _call(i, name):
        return SimpleNamespace(
            id=f"call_{i}",
            function=SimpleNamespace(name=name, arguments="{}"),
        )

    fake_msg = SimpleNamespace(
        content=None,
        tool_calls=[_call(1, "read_style_card"), _call(2, "write_plan")],
    )
    fake_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=fake_msg, finish_reason="tool_calls")],
        usage=None,
    )

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return fake_resp

    reply = _chat_tools_native(
        client=_Client(),
        model="deepseek-v4.1-flash",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "read_style_card", "description": "", "parameters": {}}],
        temperature=0.0,
        pool=None,
    )
    assert [c.name for c in reply.calls] == ["read_style_card"]
    assert len(reply.assistant_message["tool_calls"]) == 1
    assert reply.assistant_message["tool_calls"][0]["id"] == "call_1"


def test_tool_output_error_not_treated_as_unsupported():
    """tool 消息不匹配是真 bug，不应被当成"网关不支持 tools"降级。"""
    from llm import _looks_like_tool_unsupported

    assert _looks_like_tool_unsupported(
        RuntimeError(
            "Error code: 400 - {'error': {'message': 'No tool output found for "
            "tool call call_01_ET_x', 'code': 'invalid_request_error'}}"
        )
    ) is False
    assert _looks_like_tool_unsupported(RuntimeError("unsupported parameter: tools")) is True


def test_custom_gateway_skips_thinking_extra(monkeypatch):
    """Custom 网关不认 thinking 参数：命中 CUSTOM_LLM_BASE_URL 时不发 extra_body。"""
    from llm import _chat_extra_body

    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", "https://gateway.magicrew.io/v1")
    monkeypatch.setenv("LLM_THINKING", "1")

    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.magicrew.io/v1")
    assert _chat_extra_body("deepseek-v4.1-flash") is None

    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    assert _chat_extra_body("deepseek-v4-flash") == {"thinking": {"type": "enabled"}}


def test_request_max_tokens_on_custom_gateway(monkeypatch):
    """Custom 网关默认输出上限偏小，必须显式传 max_tokens，否则工具参数被截断。"""
    from llm import _request_max_tokens

    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", "https://gateway.magicrew.io/v1")

    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.magicrew.io/v1")
    assert _request_max_tokens() == 24576

    # 其它供应商保持原样：不传 max_tokens，交给网关默认值。
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    assert _request_max_tokens() is None

    # 显式设置则全链路生效，并 clamp 到 256..32768。
    monkeypatch.setenv("LLM_MAX_TOKENS", "100")
    assert _request_max_tokens() == 256
    monkeypatch.setenv("LLM_MAX_TOKENS", "999999")
    assert _request_max_tokens() == 65536


def test_native_tools_pass_max_tokens(monkeypatch):
    """原生 tools 请求必须带 max_tokens，否则 write_plan 的大 JSON 会被截断。"""
    import llm as llm_mod

    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", "https://gateway.magicrew.io/v1")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.magicrew.io/v1")

    captured: dict = {}

    class _Msg:
        content = ""
        tool_calls = []

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = None

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    llm_mod._chat_tools_native(
        client=_Client(),
        model="deepseek-v4.1-flash",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        temperature=0.3,
        pool=None,
    )
    assert captured["max_tokens"] == 24576
