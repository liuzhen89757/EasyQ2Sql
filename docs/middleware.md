# 工具执行限制 · LlmMiddleware 干预者设计

> 配套文档：`docs/hook.md`（观察者）。本文描述**干预**，观察与判断见 `hook.md`。

## 1. 角色定位

`LlmMiddleware` 在本方案中充当**干预者/注入器**，在 **LLM 请求发出之前**（`before_llm_request`）读取共享状态，把约束信息注入请求，从而影响 LLM 下一轮的决策：

- **软干预**：向 `system_prompt` 追加引导文案，提示 LLM 收敛（少搜、别乱改 SQL）。
- **硬干预**：从 `request.tools` 移除某个工具的 schema，使 LLM 这一轮起**无法再调用**该工具。

**middleware 不记录状态、不做判断**——它只消费 `ToolUsageTracker` 里由 hook 派生出的状态，并把状态翻译成对 LLM 的约束。

## 2. 设计原理

### 2.1 为什么在 LLM 请求前注入

- 干预的目标是"改变 LLM 下一步行为"，而 LLM 的下一步行为由下一轮 `LlmRequest` 决定。
- `before_llm_request(request)` 在每次 LLM 调用前执行（`agent.py:1348` 非流式 / `1422` 流式），且 `LlmRequest` 是可变 Pydantic 模型——可以就地改 `system_prompt`、`tools`，改完返回即可生效。
- 相比在 hook 里抛异常（会中止整条消息），这种方式**优雅、可恢复、可逐轮调整**。

### 2.2 软硬分级，按工具区分

| 工具 | 软干预（注入提示） | 硬干预（移除工具 schema） | 理由 |
|---|---|---|---|
| `search_table_schema` | ✅ WARN/BLOCK | ✅ BLOCK | 检索工具是辅助，LLM 卡死时应强制其用已有信息或问用户 |
| `search_metrics` | ✅ WARN/BLOCK | ✅ BLOCK | 同上 |
| `run_sql` | ✅ 全程 | ❌ **永不移除** | 取数是核心目标，逻辑上不能通过移除 `run_sql` 来"限流"；只能计数 + 提示引导 |

### 2.3 与 hook 共享同一份状态

hook 与 middleware 通过**同一个 `ToolUsageTracker` 实例** + **同一个 contextvar `_request_scope`** 通信：

- hook 在 `before_tool` 时把 `(request_id, conversation_id, user_id)` 写入 `_request_scope`；
- middleware 在 `before_llm_request` 时读取 `_request_scope` 得到当前 `request_id`，再查 tracker 拿到各工具状态。

因为二者运行在同一个 `_send_message` 协程（同一个 asyncio task），contextvar 能正确传递，天然隔离并发消息。

## 3. 触发逻辑

### 3.1 调用时机与输入

| 钩子 | 触发时机 | 输入 | 可改字段 |
|---|---|---|---|
| `before_llm_request` | 每一轮 LLM 调用前（首轮、以及每轮 tool 循环之后的下一轮都会触发） | `LlmRequest` | `system_prompt`、`tools`、`messages`、`metadata` |

`LlmRequest` 关键字段（`core/llm/models.py`）：

```python
class LlmRequest(BaseModel):
    messages: List[LlmMessage]
    tools: Optional[List[ToolSchema]] = None   # 每项有 .name
    user: User                                  # user.id 可用
    system_prompt: Optional[str] = None
    metadata: Dict[str, Any] = {}
```

> 注意：`LlmRequest` **没有 `request_id` / `conversation_id`**，所以中间件拿"当前请求"靠 `_request_scope` 上下文变量（见 §2.3）。

### 3.2 首轮不干预

首轮 LLM 调用发生在任何工具执行之前，此时 tracker 无记录、`_request_scope` 也未设置。middleware 读到 `scope is None` 应直接返回原 `request`，不做任何注入。

## 4. 干预策略

### 4.1 软干预（注入 system_prompt）

把当前处于 WARN/BLOCK 的工具约束，追加到 `system_prompt` 末尾（不存在则新建）。统一用一个醒目的段落包裹，避免与原有系统提示混淆：

```
[工具使用约束]
- search_table_schema：已调用 4 次（上限 5），建议停止重复搜索，基于已有 schema 或向用户确认表名。
- run_sql：SQL 骨架已稳定，请勿再改动或重复执行，基于当前结果作答。
```

### 4.2 硬干预（移除工具 schema）

对处于 BLOCK 状态、且 `policy.hard_block == True` 的检索类工具，从 `request.tools` 里按 `schema.name` 过滤掉：

```python
removable = {t for t in blocked if policies[t].hard_block}
if removable:
    request.tools = [s for s in request.tools if s.name not in removable]
```

### 4.3 run_sql 例外（只软不硬）

`run_sql` 无论处于何种状态（计数超限、连续错误、骨架冻结），都**只注入提示，绝不从 `request.tools` 移除**。原因：取数是 NL→SQL 的核心诉求，硬移除会让 Agent 无法完成任务；对 `run_sql` 的"限制"应体现为引导 LLM 停止无谓重跑，而非剥夺取数能力。

### 4.4 三个工具的干预文案示例

| 工具 | WARN 文案 | BLOCK 文案（仅检索类） |
|---|---|---|
| `search_table_schema` | 已多次搜索表结构，建议停止重复搜索，基于已有 schema 生成回答，或向用户确认表名。 | 调用次数已达上限，该工具已停用。请基于已有信息作答，或请用户澄清。 |
| `search_metrics` | 已多次搜索指标，建议向用户确认 metric/dimension 口径，而非继续搜索。 | 调用次数已达上限，该工具已停用。请基于已有信息作答，或请用户澄清。 |
| `run_sql` | `calls≥2`：注意 SQL 正确性，已执行多次；`连续 error`：SQL 反复报错，请检查语法/字段，勿继续盲试；`骨架冻结`：该 SQL 骨架已稳定，请勿再改动或重复执行，基于当前结果作答。 | （无） |

## 5. 代码示例

三个工具的 middleware 各自一个文件，**直接继承 `LlmMiddleware`**（不经过中间基类），共享引擎与 policy 常量都从 `core.agent.regulator` 导入（**不 import `core.lifecycle`**）：

- `src/easyq2sql/core/middleware/sql_regulator.py` — `SqlRegulatorMiddleware`（约束 `run_sql`，只软不硬）
- `src/easyq2sql/core/middleware/schema_regulator.py` — `SchemaRegulatorMiddleware`（约束 `search_table_schema`，软+硬）
- `src/easyq2sql/core/middleware/metric_regulator.py` — `MetricRegulatorMiddleware`（约束 `search_metrics`，软+硬）

```python
# core/middleware/sql_regulator.py
from ..agent.regulator import (
    RUN_SQL_POLICY, ToolState, _request_scope,
    evaluate_state, get_default_tool_usage_tracker,
)
from .base import LlmMiddleware


class SqlRegulatorMiddleware(LlmMiddleware):
    """Constrain ``run_sql``: soft guidance only, never remove the tool."""

    tool_name = "run_sql"
    policy = RUN_SQL_POLICY

    def __init__(self, tracker=None) -> None:
        self._tracker = tracker or get_default_tool_usage_tracker()

    async def before_llm_request(self, request):
        scope = _request_scope.get()
        if scope is None or request.tools is None:
            # 首轮（尚无工具调用）或无可过滤工具：不干预
            return request

        record = await self._tracker.get_record(scope.request_id, self.tool_name)
        state = evaluate_state(self.policy, record)
        if state is ToolState.OK:
            return request

        text = self.policy.warn_text if state is ToolState.WARN else (self.policy.block_text or self.policy.warn_text)
        guidance = f"[工具使用约束]\n- {self.tool_name}: {text}"
        request.system_prompt = (request.system_prompt or "") + "\n\n" + guidance

        # 硬干预：仅 hard_block=True（检索类）；run_sql 永不移除
        if state is ToolState.BLOCK and self.policy.hard_block:
            request.tools = [s for s in request.tools if getattr(s, "name", None) != self.tool_name]

        return request
```

`SchemaRegulatorMiddleware` / `MetricRegulatorMiddleware` 结构同上，仅 `tool_name` / `policy` / docstring 换成 `search_table_schema` / `search_metrics` 与 `SCHEMA_SEARCH_POLICY` / `METRIC_SEARCH_POLICY`。

> 说明：`ToolUsageRecord` 不存派生状态，因此 middleware 调用纯函数 `evaluate_state(policy, record)` 现算 `OK / WARN / BLOCK`（见 `hook.md` §8.4）。
>
> 依赖方向：`core.middleware.*` 只依赖 `core.agent.regulator`（框架中立引擎），**不 import `core.lifecycle`**——观察者与干预者通过共享 tracker + 共享 contextvar `_request_scope` 通信，而非互相引用。

## 6. 完整接入示例（`MyAgent.py`）

在构建 `Agent` 时，把三个工具的 hook 与 middleware 分别注入 `lifecycle_hooks` 与 `llm_middlewares`。它们**默认共享进程级单例 tracker**（`get_default_tool_usage_tracker()`），因此无需手工创建并传入同一个实例：

```python
from easyq2sql.core.lifecycle import (
    SqlRegulatorHook, SchemaRegulatorHook, MetricRegulatorHook,
)
from easyq2sql.core.middleware import (
    SqlRegulatorMiddleware, SchemaRegulatorMiddleware, MetricRegulatorMiddleware,
)

agent = Agent(
    llm_service=llm,
    tool_registry=tools,
    user_resolver=user_resolver,
    agent_memory=agent_memory,
    conversation_store=conversation_store,
    config=config,
    # ... 其余既有参数 ...
    lifecycle_hooks=[
        SqlRegulatorHook(),          # run_sql 观察者
        SchemaRegulatorHook(),       # search_table_schema 观察者
        MetricRegulatorHook(),       # search_metrics 观察者
    ],
    llm_middlewares=[
        SqlRegulatorMiddleware(),    # run_sql 干预者（只软不硬）
        SchemaRegulatorMiddleware(), # search_table_schema 干预者（软+硬）
        MetricRegulatorMiddleware(), # search_metrics 干预者（软+硬）
    ],
)
```

> 接线位即 `MyAgent.py` 的 `Agent(...)`（已传入 `lifecycle_hooks`/`llm_middlewares`）。
>
> 每个工具的 hook 与 middleware 一一对应，可独立增删；它们默认共享**同一个**进程级 tracker 单例。若需要多个互不干扰的 Agent 实例（或测试隔离），可显式创建 `tracker = ToolUsageTracker()` 并分别传入 `SqlRegulatorHook(tracker)` / `SqlRegulatorMiddleware(tracker)` 等。

## 7. 限制与后续

- **干预是可被 LLM 违反的软约束**：注入提示依赖模型遵循，不能保证 100% 生效；硬移除工具是更强的保证，但仅检索类可用。
- **流式/非流式两条路径都触发**：`before_llm_request` 在两条路径都有调用点（`agent.py:1348` / `1422`），行为一致，无需区分。
- **`request.tools` 的移除是"本轮起"生效**：若后续状态回落（本方案状态只单调升级，不回落），不会恢复；如需临时封禁+恢复，需在 tracker 增加时间窗/冷却逻辑。
- **文案可配置**：`warn_text`/`block_text` 应收敛到 `ToolLimitPolicy` 配置项，便于按产品调优。
