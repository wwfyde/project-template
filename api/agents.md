# Agents 层

本项目把 agent 配置、会话、一次执行、对外事件和存储放在应用自己的协议中，由 `openai-agents` 实现第一个执行后端。前端和业务 service 不需要导入 OpenAI SDK 的类型；接入另一个 agent backend 时，HTTP 协议和会话存储接口保持不变。

设计借鉴 OpenAI Agents API 的 Agent、Session、Turn、Item/Event 分层。官方 Agents API 由 OpenAI 托管 Codex harness，并承担会话、编排、上下文压缩和恢复；这里的 harness 运行在 API 进程中，由 Agents SDK 的 runner 执行模型与工具循环。这是架构思想的应用，并非官方 Agents API 的兼容实现。[Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview)、[Architecture](https://developers.openai.com/api/docs/guides/agents-api/architecture)

## 模块边界

| 层 | 职责 |
| --- | --- |
| `routes/agents.py` | HTTP 参数校验、JSON 响应和 SSE 编码。 |
| `agents/contracts.py` | 应用拥有的配置、会话、turn、item、event、backend 和 store 协议。 |
| `AgentService` | 选择 backend、会话串行化、执行超时、终态处理、原子保存结果和续接状态。 |
| `AgentBackend` | 验证能力，将标准请求映射到具体框架，产生标准事件和运行结果，停止执行。 |
| `SessionStore` | 创建和查询会话、claim/release 执行租约、原子保存 turn 与 backend state。 |

业务依赖指向 `contracts.py`。SDK 的 `Agent`、`Runner`、Responses items、异常和 stream events 在 adapter 内转换，不进入 HTTP schema。`RunRequest` 不携带 HTTP 对象、数据库 session 或 SDK 对象。

`AgentDefinition` 描述 `name`、`instructions`、`model`、可用工具名称和 `max_steps`。`max_steps` 限制 SDK 的模型循环次数；一个循环可以有多个工具调用，不能把它当作工具调用总数上限。

`AgentSession` 在创建时固定 backend 与经过验证的 agent 配置；`AgentTurn` 记录一次用户输入、状态、输出、items、usage 和安全错误。当前输入是非空文本，未知字段会被拒绝。后续需要多模态、审批或其他能力时，应明确扩展应用协议及各 backend 的校验，而不是透传任意 SDK 参数。

## 历史、续接状态和并发

对外的 canonical items 供展示和业务消费；它们不是恢复某个 SDK 执行所需的完整上下文。`BackendState` 单独保存 `backend`、`version` 和不透明 JSON `payload`，只在 store、service 和对应 adapter 之间传递，不会出现在 HTTP 响应中。

OpenAI adapter 保存 SDK `to_input_list()` 返回的完整续接输入。下一轮把上次成功状态与新输入交给 runner，保留工具调用、工具结果等模型上下文。不会同时使用 SDK Session、`previous_response_id` 或 Conversations API，以免重复拼接上下文。[Running agents](https://developers.openai.com/api/docs/guides/agents/running-agents)、[Results and state](https://developers.openai.com/api/docs/guides/agents/results)

失败或取消的 turn 保留执行记录，但不会覆盖上次成功的续接状态。失败前已经完成的外部工具副作用不会自动撤销。HTTP 提交当前没有幂等键，不提供自动重试的安全保证；有副作用的工具应自行实现幂等性，调用方不要在连接断开后盲目重发输入。

同一个 session 一次只允许一个 turn。开始执行时 store 原子 claim 租约；并发请求返回 `409`，运行中的会话不能删除。服务设置执行超时，租约用于进程退出等异常后的恢复：下一次 claim 可以将过期 turn 标记失败，再接收新输入。保存结果时以 `active_turn_id` 比较并提交，旧执行不能覆盖新执行状态。

内存 store 适合开发和测试，进程重启即丢失，并且不能用于多个 API worker 共享会话。PostgreSQL store 保存会话和 turn，利用事务及行锁协调多个 worker。持久化结果不等于持久化正在运行的 Python 协程。

切换默认 backend 只影响新会话。已有会话仍绑定原来的 backend；不同 backend 的不透明状态不能直接互换。需要迁移时，应实现明确的转换流程或新建会话，不能把展示历史当作无损运行状态。

## HTTP 和事件

所有路径都以 `/api/agents` 开头：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/backends` | 查询已注册 backend。 |
| POST | `/sessions` | 验证 agent 配置并创建会话。 |
| GET | `/sessions/{session_id}` | 读取会话配置与当前 turn ID。 |
| DELETE | `/sessions/{session_id}` | 删除非运行中的会话及执行历史。 |
| POST | `/sessions/{session_id}/turns` | 提交文本输入；`stream=false` 等待 JSON 结果，`stream=true` 读取 SSE。 |
| GET | `/sessions/{session_id}/turns` | 读取执行历史。 |
| GET | `/sessions/{session_id}/turns/{turn_id}` | 读取指定执行记录。 |

SSE 的每个事件有 `event`、`id` 和 JSON `data`。JSON 包含 `type`、`session_id`、`turn_id`、`sequence` 和事件内容 `data`。`sequence` 在一次 turn 内递增；SSE ID 用于关联事件，当前没有重放日志，也不支持通过 `Last-Event-ID` 续流。

| 事件 | 含义 |
| --- | --- |
| `turn.started` | 已取得会话执行权，开始本轮。 |
| `output_text.delta` | 文本增量。 |
| `item.completed` | 一个标准 item 已完成。 |
| `agent.updated` | runner 报告当前 agent 变化。 |
| `turn.completed` | 本轮成功，结果及续接状态已保存。 |
| `turn.failed` | 本轮失败，包含可对外公开的错误。 |

会话不存在、backend 不支持配置或并发冲突等初始错误在发送 SSE 响应头之前返回 HTTP 错误。流开始后的执行错误通过终态事件报告，不能再改 HTTP 状态；JSON 模式返回 turn，并通过 `status` / `error` 判断运行是否成功。未知底层异常不会把 SDK 错误详情或凭据暴露给调用方。

当前执行绑定 HTTP 请求：SSE 连接断开会取消本次 runner 并保存 `cancelled` 状态；断开的客户端通过读取 turn 确认结果，没有额外的取消事件或主动取消端点。应用 lifespan 在关闭时释放 backend 客户端。没有后台 worker、排队执行、断线后继续运行、事件重放、webhook、运行中 steering、人工审批或沙箱生命周期管理。工具运行在 API 进程中，只有服务端注册的工具才可被会话选择；客户端不能提交 Python 代码、任意可执行程序或任意 MCP 地址。

这些路由沿用应用现有的访问控制方式，没有额外提供用户认证或按租户隔离会话。部署方需要在既有统一访问控制层保护端点；仅持有 session ID 本身不构成所有权校验。

## 配置和调用

依赖已包含 `openai-agents`。配置复用现有 `Settings`：`repo_type` 选择存储，`providers.openai` 提供模型客户端配置，`httpx_timeout` / `proxy_url` 控制模型 HTTP 客户端，`agents` 表控制执行层。将下面内容合并到 API 工作目录的配置文件，保留其他已有配置：

```toml
# 顶层字段，应写在第一个 [table] 之前。
repo_type = "in-memory" # 多 worker 或需要持久化时改为 "postgres"

[agents]
default_backend = "openai-agents"
run_timeout_seconds = 120
tracing_enabled = false

[providers.openai]
base_url = "https://api.openai.com/v1"
api_key = "replace-with-your-key"
model = "your-enabled-model"
```

`model` 替换为账号可用并支持 Responses API 的模型 ID；创建会话时可用 `agent.model` 覆盖默认值。`base_url` 指向其他服务时，该服务必须支持 adapter 所用的 Responses API，单纯支持 Chat Completions 不够。改变模型 API 地址仍然使用 `openai-agents` backend；替换 agent 框架需要注册另一个 backend。

没有配置 `providers.openai` 时，不注册这个 backend，调用创建会话返回 `503 backend_unavailable`，其他现有 API 路由不因此失效。没有配置默认模型且创建会话也未传模型时，返回 `400 model_required`。`run_timeout_seconds` 是整个 turn 的执行上限（默认 120 秒），与单次 HTTP 请求超时不同。

现有配置优先级和启动要求见 [README](README.md#配置优先级与生效)。可用 `AGENTS_DEFAULT_BACKEND`、`AGENTS_RUN_TIMEOUT_SECONDS`、`AGENTS_TRACING_ENABLED` 覆盖对应字段。Agents SDK tracing 默认关闭，与应用 OTel 独立；开启后使用 SDK 自己的 exporter 和认证配置，不会自动复用此处模型客户端的密钥。adapter 始终设置 `trace_include_sensitive_data=False`。

使用 PostgreSQL 时，先按现有部署方式配置数据库并执行迁移：

```bash
cd api
uv run alembic upgrade head
```

会话存储不复用现有 `/api/conversations` 的展示记录；新表由独立 migration 创建。部署前后不要在 `in-memory` / `postgres` 之间切换并期待原有 session 自动迁移。

API 启动后，在终端创建会话。以下示例用 `jq` 获取 ID，不会触发模型调用，直到提交 turn：

```bash
AGENT_API=http://localhost:8000/api/agents

curl -sS "$AGENT_API/backends"

AGENT_SESSION_ID=$(curl -fsS "$AGENT_API/sessions" \
  -H 'Content-Type: application/json' \
  -d '{"backend":"openai-agents","agent":{"name":"Assistant","instructions":"用中文简洁回答。","max_steps":10}}' \
  | jq -r '.id')

# JSON：请求等待执行完成，再返回完整 AgentTurn。
curl -sS "$AGENT_API/sessions/$AGENT_SESSION_ID/turns" \
  -H 'Content-Type: application/json' \
  -d '{"input":"我叫小林，请记住。"}'

# SSE：同一个会话复用上一次成功运行的完整上下文。
curl -N "$AGENT_API/sessions/$AGENT_SESSION_ID/turns" \
  -H 'Content-Type: application/json' \
  -d '{"input":"我叫什么？","stream":true}'

curl -sS "$AGENT_API/sessions/$AGENT_SESSION_ID/turns?limit=20"
```

## 添加或切换 backend

实现 `AgentBackend` 的 `name`、`validate()`、`stream()` 和 `aclose()` 即可接入。`validate()` 解析默认值并明确拒绝不支持的工具或模型配置；`stream()` 返回可关闭的异步生成器，产生进度事件后必须恰好产生一个 `RunEvent(type="result")` 并结束。结果中的 state 必须属于该 backend，`aclose()` 负责释放客户端等资源。

下面的 `EchoBackend` 是不依赖任何 agent SDK 的最小可运行示例，用于展示替换边界；真实实现应在自己的模块内负责框架映射与取消：

```python
from collections.abc import AsyncGenerator

from api.agents.contracts import (
    AgentDefinition, AgentFailure, AgentItem, BackendState,
    RunEvent, RunRequest, RunResult,
)


class EchoBackend:
    name = "echo"

    def validate(self, agent: AgentDefinition) -> AgentDefinition:
        if agent.tools:
            raise AgentFailure("unsupported_tool", "Echo has no tools.")
        return agent.model_copy(deep=True)

    async def stream(self, request: RunRequest) -> AsyncGenerator[RunEvent, None]:
        if request.state is not None and (
            request.state.backend != self.name or request.state.version != 1
        ):
            raise AgentFailure("invalid_backend_state", "Incompatible echo state.")
        output = request.input
        yield RunEvent(type="output_text.delta", data={"delta": output})
        yield RunEvent(
            type="result",
            result=RunResult(
                output=output,
                state=BackendState(backend=self.name, payload={"last_input": output}),
                items=[AgentItem(type="message", role="assistant", text=output)],
            ),
        )

    async def aclose(self) -> None:
        pass
```

在应用创建阶段、开始处理请求之前注册。`create_agent_service()` 是组合入口，创建配置中的 store 和默认 OpenAI adapter；HTTP 依赖优先读取 `app.state.agent_service`：

```python
from api.agents.runtime import create_agent_service
from api.core.config import settings

# 放在 create_app() 中 app 创建后、return app 之前。
service = create_agent_service(settings)
service.backends["echo"] = EchoBackend()
app.state.agent_service = service
```

请求 `POST /api/agents/sessions` 时传入 `{"backend":"echo"}` 即使用新实现；也可设置 `[agents].default_backend = "echo"` 并重启，使新会话默认选择它。注册表必须先包含对应名称。使用依赖注入时，也可覆盖 `routes.agents.get_agent_service`；测试展示了两种接入方式，均不改变 route 或 store。

业务工具使用 `AgentTool(name, description, parameters, invoke)` 注册到 `OpenAIAgentsBackend(..., tools=...)` 或 `from_config(..., tools=...)`。`parameters` 是参数 JSON Schema，异步 `invoke` 接收应用的 `ToolContext(session_id, turn_id)` 和 JSON 参数，返回 JSON。默认组合入口没有注册工具，创建会话时 `agent.tools` 只能选择服务器已注册的名称。工具 adapter 将其转为 SDK `FunctionTool`，工具实现无需依赖 SDK context。

adapter 检查工具参数是 JSON 对象；具体参数类型、必填字段和业务约束由 `invoke` 校验。

## 验证

```bash
uv run pytest api/tests/test_agents.py api/tests/test_agent_backend.py api/tests/test_agent_store.py api/tests/test_agent_runtime.py
```

service / HTTP 测试使用两个独立命名的假 backend，验证替换、状态续接、租约冲突、失败与取消、超时和 JSON / SSE 协议，不访问模型网络。存储测试覆盖事务提交和过期租约恢复；SQLite 测试不能证明 PostgreSQL 的真实跨连接并发行为，正式部署应在目标 PostgreSQL 上做迁移与并发验收。
