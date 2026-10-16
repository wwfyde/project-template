import asyncio
import copy
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx2
import pytest
import pytest_asyncio
from agents import Agent, FunctionTool, RunConfig, Runner
from agents.exceptions import InputGuardrailTripwireTriggered
from agents.guardrail import (
    GuardrailFunctionOutput,
    InputGuardrail,
    InputGuardrailResult,
)
from agents.items import ModelResponse, TResponseInputItem, TResponseStreamEvent
from agents.models.interface import Model
from agents.models.openai_provider import OpenAIProvider
from agents.result import RunResultStreaming
from openai import AsyncOpenAI, RateLimitError
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
    ResponseUsage,
)
from pydantic import JsonValue

from api.agents.backends.openai_agents import OpenAIAgentsBackend
from api.agents.contracts import (
    AgentDefinition,
    AgentFailure,
    AgentTool,
    BackendState,
    RunRequest,
    ToolContext,
)


def message(text: str = "Hello") -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="msg_test",
        type="message",
        status="completed",
        role="assistant",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


class FakeModel(Model):
    def __init__(self, outputs: list[list[object]]) -> None:
        self.outputs = outputs
        self.inputs: list[object] = []
        self.error: Exception | None = None
        self.block = False
        self.closed = asyncio.Event()

    async def get_response(self, *args: object, **kwargs: object) -> ModelResponse:
        raise AssertionError("Only the streaming path should run.")

    async def stream_response(
        self, *args: object, **kwargs: object
    ) -> AsyncIterator[TResponseStreamEvent]:
        self.inputs.append(copy.deepcopy(args[1]))
        assert kwargs["previous_response_id"] is None
        assert kwargs["conversation_id"] is None
        try:
            if self.error:
                raise self.error
            output = self.outputs.pop(0)
            if output and isinstance(output[0], ResponseOutputMessage):
                content = output[0].content[0]
                assert isinstance(content, ResponseOutputText)
                yield ResponseTextDeltaEvent(
                    type="response.output_text.delta",
                    delta=content.text,
                    content_index=0,
                    output_index=0,
                    item_id=output[0].id,
                    sequence_number=1,
                    logprobs=[],
                )
            if self.block:
                await asyncio.Event().wait()
            yield ResponseCompletedEvent(
                type="response.completed",
                sequence_number=2,
                response=Response.model_construct(
                    id=f"resp_{len(self.inputs)}",
                    output=output,
                    usage=ResponseUsage.model_validate(
                        {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "total_tokens": 15,
                            "input_tokens_details": {
                                "cached_tokens": 0,
                                "cache_write_tokens": 0,
                            },
                            "output_tokens_details": {"reasoning_tokens": 0},
                        }
                    ),
                    status="completed",
                    model="test-model",
                ),
            )
        finally:
            self.closed.set()


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    model = FakeModel([[message()]])
    monkeypatch.setattr(OpenAIProvider, "get_model", lambda _self, _name: model)
    return model


@pytest_asyncio.fixture
async def backend() -> AsyncIterator[OpenAIAgentsBackend]:
    def deny_network(_request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("Backend tests must never access the network.")

    client = AsyncOpenAI(
        api_key="test-only-key",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(deny_network)),
    )
    backend = OpenAIAgentsBackend(client, default_model="test-model")
    yield backend
    await backend.aclose()


def request(
    *,
    agent: AgentDefinition | None = None,
    input: str = "Hi",
    state: BackendState | None = None,
) -> RunRequest:
    return RunRequest(
        session_id="session",
        turn_id="turn",
        agent=agent if agent is not None else AgentDefinition(),
        input=input,
        state=state,
    )


@pytest.mark.asyncio
async def test_stream_result_and_local_history(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    events = [event async for event in backend.stream(request())]
    assert [event.type for event in events] == [
        "agent.updated",
        "output_text.delta",
        "item.completed",
        "result",
    ]
    final = events[-1].result
    assert final is not None
    assert final.output == "Hello"
    assert final.usage.requests == 1
    assert final.usage.total_tokens == 15
    emitted_item = events[2].data["item"]
    assert isinstance(emitted_item, dict)
    assert final.items[0].id == emitted_item["id"]
    assert final.state.backend == "openai-agents"
    history = final.state.payload["history"]
    assert isinstance(history, list)
    assert history[0] == {"role": "user", "content": "Hi"}
    fake_model.outputs = [[message("Next")]]
    follow_up = [
        event
        async for event in backend.stream(request(input="Again", state=final.state))
    ]
    follow_up_result = follow_up[-1].result
    assert follow_up_result is not None
    assert follow_up_result.output == "Next"
    assert fake_model.inputs[-1] == [
        *history,
        {"role": "user", "content": "Again"},
    ]


@pytest.mark.asyncio
async def test_registered_tool_runs_with_application_context(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    invocations = []

    async def invoke(
        context: ToolContext, arguments: dict[str, JsonValue]
    ) -> JsonValue:
        invocations.append((context, arguments))
        return {"answer": 42}

    backend._tools["lookup"] = AgentTool(
        name="lookup",
        description="Lookup a value",
        parameters={"type": "object", "properties": {"key": {"type": "string"}}},
        invoke=invoke,
    )
    fake_model.outputs = [
        [
            ResponseFunctionToolCall(
                type="function_call",
                name="lookup",
                call_id="call_test",
                arguments='{"key":"x"}',
            )
        ],
        [message("42")],
    ]
    events = [
        event
        async for event in backend.stream(
            request(agent=AgentDefinition(tools=["lookup"]))
        )
    ]
    result = events[-1].result
    assert result is not None
    assert invocations == [(ToolContext("session", "turn"), {"key": "x"})]
    assert [item.type for item in result.items] == [
        "tool_call",
        "tool_result",
        "message",
    ]
    assert result.items[1].call_id == "call_test"
    assert result.items[1].text == '{"answer": 42}'
    assert result.usage.requests == 2
    assert result.usage.total_tokens == 30
    history = result.state.payload["history"]
    assert isinstance(history, list)
    assert any(
        isinstance(item, dict) and item.get("type") == "function_call_output"
        for item in history
    )


@pytest.mark.asyncio
async def test_tool_failure_fails_turn_without_exposing_exception(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    async def invoke(
        _context: ToolContext, _arguments: dict[str, JsonValue]
    ) -> JsonValue:
        raise ValueError("secret internal credentials")

    backend._tools["broken"] = AgentTool(
        "broken", "Broken tool", {"type": "object"}, invoke
    )
    fake_model.outputs = [
        [
            ResponseFunctionToolCall(
                type="function_call",
                name="broken",
                call_id="call_test",
                arguments="{}",
            )
        ]
    ]
    with pytest.raises(AgentFailure) as error:
        _ = [
            event
            async for event in backend.stream(
                request(agent=AgentDefinition(tools=["broken"]))
            )
        ]
    assert error.value.code == "tool_execution_failed"
    assert "secret" not in error.value.message


@pytest.mark.asyncio
async def test_closing_stream_cancels_and_joins_model(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    fake_model.block = True
    stream = backend.stream(request())
    while (await anext(stream)).type != "output_text.delta":
        pass
    await asyncio.wait_for(stream.aclose(), timeout=1)
    assert fake_model.closed.is_set()


@pytest.mark.asyncio
async def test_task_cancellation_joins_model(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    fake_model.block = True
    seen_delta = asyncio.Event()

    async def consume() -> None:
        async for event in backend.stream(request()):
            if event.type == "output_text.delta":
                seen_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(seen_delta.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake_model.closed.is_set()


@pytest.mark.asyncio
async def test_task_cancellation_joins_running_tool(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def invoke(
        _context: ToolContext, _arguments: dict[str, JsonValue]
    ) -> JsonValue:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    backend._tools["wait"] = AgentTool("wait", "Wait", {"type": "object"}, invoke)
    fake_model.outputs = [
        [
            ResponseFunctionToolCall(
                type="function_call",
                name="wait",
                call_id="call_wait",
                arguments="{}",
            )
        ]
    ]

    async def consume() -> None:
        async for _ in backend.stream(request(agent=AgentDefinition(tools=["wait"]))):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    assert stopped.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        BackendState(backend="other", payload={"history": []}),
        BackendState(backend="openai-agents", version=2, payload={"history": []}),
        BackendState(backend="openai-agents", payload={"history": "bad"}),
        BackendState(
            backend="openai-agents",
            payload={"history": [], "previous_response_id": "r1"},
        ),
    ],
)
async def test_incompatible_state_is_rejected(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
    state: BackendState,
) -> None:
    with pytest.raises(AgentFailure) as error:
        _ = [event async for event in backend.stream(request(state=state))]
    assert error.value.code == "invalid_backend_state"
    assert fake_model.inputs == []


def test_configuration_resolves_model_and_rejects_unknown_tools(
    backend: OpenAIAgentsBackend,
) -> None:
    assert backend.validate(AgentDefinition()).model == "test-model"
    assert backend.validate(AgentDefinition(model="explicit")).model == "explicit"
    with pytest.raises(AgentFailure, match="not registered"):
        backend.validate(AgentDefinition(tools=["unknown"]))
    backend._default_model = None
    with pytest.raises(AgentFailure, match="model must be configured"):
        backend.validate(AgentDefinition())


@pytest.mark.asyncio
async def test_step_limit_is_application_error(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    async def invoke(
        _context: ToolContext, _arguments: dict[str, JsonValue]
    ) -> JsonValue:
        return "done"

    backend._tools["again"] = AgentTool("again", "Again", {"type": "object"}, invoke)
    fake_model.outputs = [
        [
            ResponseFunctionToolCall(
                type="function_call",
                name="again",
                call_id="call_test",
                arguments="{}",
            )
        ]
    ]
    with pytest.raises(AgentFailure) as error:
        _ = [
            event
            async for event in backend.stream(
                request(agent=AgentDefinition(tools=["again"], max_steps=1))
            )
        ]
    assert error.value.code == "max_steps_exceeded"


@pytest.mark.asyncio
async def test_provider_error_is_sanitized(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    fake_model.error = RateLimitError(
        "private provider response",
        response=httpx2.Response(
            429, request=httpx2.Request("POST", "https://example.invalid")
        ),
        body=None,
    )
    with pytest.raises(AgentFailure) as error:
        _ = [event async for event in backend.stream(request())]
    assert error.value.code == "upstream_rate_limited"
    assert "private" not in error.value.message


@pytest.mark.asyncio
async def test_guardrail_failure_is_classified(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
) -> None:
    output = GuardrailFunctionOutput(output_info=None, tripwire_triggered=True)
    guardrail = InputGuardrail(
        guardrail_function=lambda _context, _agent, _input: output,
    )
    fake_model.error = InputGuardrailTripwireTriggered(
        InputGuardrailResult(guardrail=guardrail, output=output)
    )
    with pytest.raises(AgentFailure) as error:
        _ = [event async for event in backend.stream(request())]
    assert error.value.code == "guardrail_triggered"


@pytest.mark.asyncio
async def test_approval_is_not_reported_as_completed(
    backend: OpenAIAgentsBackend,
    fake_model: FakeModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invoke(
        _context: ToolContext, _arguments: dict[str, JsonValue]
    ) -> JsonValue:
        raise AssertionError("Approval must prevent execution.")

    backend._tools["approval"] = AgentTool(
        "approval", "Approval", {"type": "object"}, invoke
    )
    fake_model.outputs = [
        [
            ResponseFunctionToolCall(
                type="function_call",
                name="approval",
                call_id="call_test",
                arguments="{}",
            )
        ]
    ]
    original = Runner.run_streamed

    def run(
        agent: Agent[ToolContext],
        input: str | list[TResponseInputItem],
        *,
        context: ToolContext,
        max_turns: int,
        run_config: RunConfig,
        auto_previous_response_id: bool,
    ) -> RunResultStreaming:
        tool = agent.tools[0]
        assert isinstance(tool, FunctionTool)
        tool.needs_approval = True
        return original(
            agent,
            input,
            context=context,
            max_turns=max_turns,
            run_config=run_config,
            auto_previous_response_id=auto_previous_response_id,
        )

    monkeypatch.setattr(Runner, "run_streamed", run)
    with pytest.raises(AgentFailure) as error:
        _ = [
            event
            async for event in backend.stream(
                request(agent=AgentDefinition(tools=["approval"]))
            )
        ]
    assert error.value.code == "approval_unsupported"


@pytest.mark.asyncio
async def test_closing_backend_closes_owned_client() -> None:
    client = AsyncMock(spec=AsyncOpenAI)
    backend = OpenAIAgentsBackend(client)
    await backend.aclose()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_config_factory_owns_httpx2_client() -> None:
    backend = OpenAIAgentsBackend.from_config(
        api_key="test-only-key",
        base_url="https://example.invalid/v1",
        default_model="test-model",
        timeout=12,
    )
    assert isinstance(backend._client._client, httpx2.AsyncClient)
    assert backend._client.timeout == 12
    assert backend.validate(AgentDefinition()).model == "test-model"
    await backend.aclose()
    assert backend._client.is_closed()
