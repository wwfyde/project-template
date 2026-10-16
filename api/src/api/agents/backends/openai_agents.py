"""OpenAI Agents SDK execution with application-owned conversation history."""

import asyncio
import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import suppress
from typing import Any, cast

import httpx2
from agents import Agent, FunctionTool, RunConfig, Runner
from agents.exceptions import (
    InputGuardrailTripwireTriggered,
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelTimeoutError,
    OutputGuardrailTripwireTriggered,
    ToolInputGuardrailTripwireTriggered,
    ToolOutputGuardrailTripwireTriggered,
    UserError,
)
from agents.items import ItemHelpers, RunItem, TResponseInputItem
from agents.models.openai_provider import OpenAIProvider
from agents.result import RunResultStreaming
from agents.stream_events import StreamEvent
from agents.tool_context import ToolContext as SDKToolContext
from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from openai.types.responses import ResponseTextDeltaEvent
from pydantic import BaseModel, JsonValue, TypeAdapter

from api.agents.contracts import (
    AgentDefinition,
    AgentFailure,
    AgentItem,
    AgentTool,
    AgentUsage,
    BackendState,
    RunEvent,
    RunRequest,
    RunResult,
    ToolContext,
)

_JSON = TypeAdapter(JsonValue)
_GUARDRAIL_ERRORS = (
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    ToolInputGuardrailTripwireTriggered,
    ToolOutputGuardrailTripwireTriggered,
)


def _json_value(value: object) -> JsonValue:
    """Detach SDK values and reject objects or non-finite JSON numbers."""
    validated = _JSON.validate_python(value, strict=True)
    return json.loads(json.dumps(validated, allow_nan=False, ensure_ascii=False))


class OpenAIAgentsBackend:
    name = "openai-agents"

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        default_model: str | None = None,
        tools: Mapping[str, AgentTool] | None = None,
        tracing_disabled: bool = True,
    ) -> None:
        self._client = client
        self._default_model = default_model
        self._tools = dict(tools or {})
        self._tracing_disabled = tracing_disabled
        self._provider = OpenAIProvider(openai_client=client, use_responses=True)

    @classmethod
    def from_config(
        cls,
        *,
        api_key: str,
        base_url: str,
        default_model: str | None,
        timeout: float,
        proxy_url: str | None = None,
        tools: Mapping[str, AgentTool] | None = None,
        tracing_disabled: bool = True,
    ) -> "OpenAIAgentsBackend":
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            http_client=httpx2.AsyncClient(proxy=proxy_url, timeout=timeout),
        )
        return cls(
            client,
            default_model=default_model,
            tools=tools,
            tracing_disabled=tracing_disabled,
        )

    def validate(self, agent: AgentDefinition) -> AgentDefinition:
        model = agent.model or self._default_model
        if not model or not model.strip():
            raise AgentFailure("model_required", "An agent model must be configured.")
        if not 1 <= agent.max_steps <= 100:
            raise AgentFailure(
                "invalid_max_steps", "max_steps must be between 1 and 100."
            )
        if len(set(agent.tools)) != len(agent.tools):
            raise AgentFailure("duplicate_tool", "Agent tool names must be unique.")
        for name in agent.tools:
            tool = self._tools.get(name)
            if tool is None or tool.name != name:
                raise AgentFailure("unknown_tool", "An agent tool is not registered.")
        return agent.model_copy(update={"model": model}, deep=True)

    def _input(self, request: RunRequest) -> list[TResponseInputItem]:
        history: list[dict[str, JsonValue]] = []
        state = request.state
        if state is not None:
            if (
                state.backend != self.name
                or state.version != 1
                or set(state.payload) != {"history"}
            ):
                raise AgentFailure(
                    "invalid_backend_state",
                    "The agent continuation is incompatible.",
                    409,
                )
            try:
                value = _json_value(state.payload["history"])
                if not isinstance(value, list) or not all(
                    isinstance(item, dict) for item in value
                ):
                    raise ValueError("History must contain JSON objects.")
                history = cast(list[dict[str, JsonValue]], value)
            except TypeError, ValueError:
                raise AgentFailure(
                    "invalid_backend_state", "The agent continuation is invalid.", 409
                ) from None
        # This backend always replays local history. Never combine it with a
        # Responses conversation ID, previous response ID, or an SDK session.
        return cast(
            list[TResponseInputItem],
            [
                *history,
                {"role": "user", "content": request.input},
            ],
        )

    def _tool(self, tool: AgentTool) -> FunctionTool:
        async def invoke(context: SDKToolContext[ToolContext], arguments: str) -> str:
            try:
                values = _json_value(json.loads(arguments))
                if not isinstance(values, dict):
                    raise ValueError("Tool arguments must be an object.")
            except TypeError, ValueError:
                raise AgentFailure(
                    "invalid_tool_arguments",
                    "The agent supplied invalid tool arguments.",
                    502,
                ) from None
            try:
                output = _json_value(await tool.invoke(context.context, values))
                return json.dumps(output, ensure_ascii=False, allow_nan=False)
            except Exception:
                # Direct FunctionTool invocation propagates exceptions; it does not
                # turn a failed application action into a successful tool result.
                raise AgentFailure(
                    "tool_execution_failed", "An agent tool failed to execute.", 502
                ) from None

        return FunctionTool(
            name=tool.name,
            description=tool.description,
            params_json_schema=cast(dict[str, Any], _json_value(tool.parameters)),
            on_invoke_tool=invoke,
            strict_json_schema=False,
        )

    @staticmethod
    def _item(item: RunItem) -> AgentItem:
        raw = item.raw_item
        data = _json_value(
            raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
        )
        if not isinstance(data, dict):
            raise AgentFailure(
                "invalid_backend_output", "The agent returned an invalid item.", 502
            )
        raw_call_id = data.get("call_id")
        call_id = raw_call_id if isinstance(raw_call_id, str) else None
        raw_name = data.get("name")
        name = raw_name if isinstance(raw_name, str) else None
        if item.type == "message_output_item":
            return AgentItem(
                type="message",
                role="assistant",
                text=ItemHelpers.text_message_output(item),
            )
        if item.type in {"tool_call_item", "tool_search_call_item"}:
            return AgentItem(
                type="tool_call",
                call_id=call_id,
                name=name,
                data={"arguments": data.get("arguments")},
            )
        if item.type in {"tool_call_output_item", "tool_search_output_item"}:
            output = data.get("output")
            return AgentItem(
                type="tool_result",
                role="tool",
                call_id=call_id,
                name=name,
                text=output if isinstance(output, str) else None,
                data={"output": output},
            )
        if item.type in {"handoff_call_item", "handoff_output_item"}:
            return AgentItem(type="handoff", call_id=call_id, name=name)
        if item.type == "reasoning_item":
            return AgentItem(
                type="reasoning", data={"summary": data.get("summary", [])}
            )
        raise AgentFailure(
            "unsupported_item", "The agent returned an unsupported item.", 502
        )

    async def stream(self, request: RunRequest) -> AsyncGenerator[RunEvent, None]:
        definition = self.validate(request.agent)
        inputs = self._input(request)
        result: RunResultStreaming | None = None
        events = None
        settled = False
        try:
            agent = Agent[ToolContext](
                name=definition.name,
                instructions=definition.instructions,
                model=definition.model,
                tools=[self._tool(self._tools[name]) for name in definition.tools],
            )
            result = Runner.run_streamed(
                agent,
                inputs,
                context=ToolContext(request.session_id, request.turn_id),
                max_turns=definition.max_steps,
                run_config=RunConfig(
                    model_provider=self._provider,
                    tracing_disabled=self._tracing_disabled,
                    trace_include_sensitive_data=False,
                ),
                auto_previous_response_id=False,
            )
            items: dict[int, AgentItem] = {}
            events = cast(AsyncGenerator[StreamEvent, None], result.stream_events())
            async for event in events:
                if event.type == "raw_response_event" and isinstance(
                    event.data, ResponseTextDeltaEvent
                ):
                    yield RunEvent(
                        type="output_text.delta", data={"delta": event.data.delta}
                    )
                elif event.type == "agent_updated_stream_event":
                    yield RunEvent(
                        type="agent.updated", data={"name": event.new_agent.name}
                    )
                elif event.type == "run_item_stream_event":
                    if event.item.type in {
                        "tool_approval_item",
                        "mcp_approval_request_item",
                    }:
                        raise AgentFailure(
                            "approval_unsupported",
                            "Agent approvals are not supported.",
                            409,
                        )
                    converted = self._item(event.item)
                    items[id(event.item)] = converted
                    yield RunEvent(
                        type="item.completed",
                        data={"item": converted.model_dump(mode="json")},
                    )
            if not result.is_complete:
                raise AgentFailure(
                    "incomplete_run",
                    "The agent stopped before completing this turn.",
                    502,
                )
            settled = True
            if result.run_loop_exception is not None:
                raise result.run_loop_exception
            if result.interruptions:
                raise AgentFailure(
                    "approval_unsupported", "Agent approvals are not supported.", 409
                )
            if not isinstance(result.final_output, str):
                raise AgentFailure(
                    "invalid_backend_output",
                    "The agent did not produce a text result.",
                    502,
                )
            usage = result.context_wrapper.usage
            output_items = [
                items.get(id(item)) or self._item(item) for item in result.new_items
            ]
            continuation = BackendState(
                backend=self.name,
                payload={"history": _json_value(result.to_input_list())},
            )
            yield RunEvent(
                type="result",
                result=RunResult(
                    output=result.final_output,
                    state=continuation,
                    items=output_items,
                    usage=AgentUsage(
                        requests=usage.requests,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        total_tokens=usage.total_tokens,
                    ),
                ),
            )
        except AgentFailure:
            raise
        except MaxTurnsExceeded:
            raise AgentFailure(
                "max_steps_exceeded", "The agent reached its step limit.", 422
            ) from None
        except _GUARDRAIL_ERRORS:
            raise AgentFailure(
                "guardrail_triggered", "An agent guardrail stopped this turn.", 422
            ) from None
        except APITimeoutError, ModelTimeoutError:
            raise AgentFailure(
                "upstream_timeout", "The agent provider timed out.", 504
            ) from None
        except RateLimitError:
            raise AgentFailure(
                "upstream_rate_limited", "The agent provider is rate limited.", 429
            ) from None
        except APIError, ModelBehaviorError:
            raise AgentFailure(
                "upstream_error",
                "The agent provider could not complete this turn.",
                502,
            ) from None
        except UserError as error:
            # SDK 0.24 wraps direct FunctionTool exceptions in UserError.
            # Recover only our already-sanitized application failure.
            if isinstance(error.__cause__, AgentFailure):
                raise error.__cause__ from None
            raise AgentFailure(
                "agent_execution_failed", "The agent could not complete this turn.", 502
            ) from None
        except Exception:
            raise AgentFailure(
                "agent_execution_failed", "The agent could not complete this turn.", 502
            ) from None
        finally:
            if result is not None:
                if not settled:
                    result.cancel(mode="immediate")
                if events is not None:
                    with suppress(Exception, asyncio.CancelledError):
                        await events.aclose()
                if not settled:
                    # SDK cancellation is synchronous. Draining joins its model/tool
                    # tasks and closes streams before our iterator finishes closing.
                    with suppress(Exception, asyncio.CancelledError):
                        async for _ in result.stream_events():
                            pass
                result.release_agents()

    async def aclose(self) -> None:
        await self._provider.aclose()
        await self._client.close()
