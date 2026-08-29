# 工具执行限制 · LifecycleHook 观察者设计

> 配套文档：`docs/middleware.md`（干预者）。本文描述**观察与判断**，`middleware.md` 描述**干预**。

## 1. 角色定位

`LifecycleHook` 在本方案中充当**观察者/记录者**，只做两件事：

1. **观测**：在工具执行前后采集工具的调用状态（次数、成败、结果质量、SQL 形状等）。
2. **记录**：把观测结果写入共享状态 `ToolUsageTracker`，并派生出每个工具的当前状态（`OK / WARN / BLOCK`）。

**hook 不负责硬阻断**。是否干预、如何干预由 `LlmMiddleware`（见 `middleware.md`）在 LLM 请求前完成。

## 2. 设计原理

### 2.1 为什么 hook 只观察、不硬阻断

框架里 `before_tool` 的返回类型是 `None`，唯一能"阻止执行"的办法是抛 `AgentError`。但勘察 `agent.py` 后发现：

- `before_tool` 调用点（`agent.py:807`）**没有局部 try/except**，异常会一路向上传播；
- 最终被 `send_message` 的兜底 `except Exception`（`agent.py:167`）捕获，**中止整条消息**并渲染通用错误 UI，而不是"优雅地拒绝这一个工具调用"。

因此用抛异常来阻断单个工具，代价是毁掉整个请求，体验很差。正确做法是把"是否放行/限制"交给 **LLM 请求前的 middleware 注入提示（软干预）与移除工具 schema（硬干预）**，hook 只提供决策所需的状态。

### 2.2 hook 拿不到工具参数 → 用 metadata 拓展补足

`before_tool(tool, context)` 只拿到 `tool`（工具实例）和 `context`（执行上下文），**拿不到本次调用的参数**（`query` / `sql`）；`after_tool(result)` 只拿到 `ToolResult`，也没有工具名/参数。

而"是否重复 query""是否没新表""SQL 形状""行粒度"这些观测都依赖参数或结果细节。解决方式（已与用户确认）：

- 对三个工具做 **`ToolResult.metadata` 字段拓展**，把原始事实（query / sql / 命中表名等）写进结果；
- `after_tool(result)` 读 `result.metadata` 即可获取这些观测数据，无需改动 hook 签名。

> 边界约定：**工具只暴露原始事实，观察逻辑（去重、骨架提取、形状判断）归 hook**。

### 2.3 归因：`after_tool` 没有 tool 名/context

`after_tool(result)` 无法知道结果属于哪个工具、哪个请求。方案用两个 task-local `ContextVar` 在 `before_tool` → `after_tool` 之间传递归因信息（详见 §6.2）。

## 3. 触发逻辑

### 3.1 调用时机与签名

| 钩子 | 触发时机 | 签名 | 可观测状态 |
|---|---|---|---|
| `before_tool` | 工具在 registry 中查到、权限通过后、执行**前**（`agent.py:791`） | `async def before_tool(self, tool, context)` | `tool.name`；`context.user.id` / `context.conversation_id` / `context.request_id` / 可变 `context.metadata` |
| `after_tool` | 工具执行完成（含错误恢复）后（`agent.py:951`） | `async def after_tool(self, result)` | `result.success` / `result.error` / `result.metadata`（含拓展字段） |

### 3.2 一次请求内的时序

```
send_message ──────────────────────────────────────────────────────►
  │
  ├─[before_message]  user, message        （此阶段无 conversation_id/request_id）
  │
  ├─ tool 循环（每轮 LLM 响应里的多个 tool_call 逐个处理）
  │    for tool_call in response.tool_calls:
  │       before_tool(tool, context)   ← ① 计数 + 设置 contextvar 作用域
  │       registry.execute(...)        ← 工具真实执行，产出 ToolResult(含 metadata)
  │       after_tool(result)           ← ② 读 metadata + 记录质量/去重/形状
  │
  ├─ 下一轮 LLM 请求前
  │       middleware.before_llm_request(request)  ← ③ 读 tracker → 注入/移除工具
  │
  └─ ...
```

## 4. 观测维度

### 4.1 检索类（`search_table_schema` / `search_metrics`）

| # | 观测维度 | 数据来源 | 说明 |
|---|---|---|---|
| 1 | 调用次数 `calls` | `before_tool` 计数 | 每调用一次 +1 |
| 2 | 成功 / 失败 | `after_tool` 的 `result.success` | `success=False` 计为 error |
| 3 | 是否重复 query | `after_tool` 读 `metadata["query"]`，与 tracker 上次对比 | 同一 query 反复出现 = 检索陷入死循环 |
| 4 | 是否没新表 | `after_tool` 读 `metadata["tables"]`，与 tracker 累积 `seen_tables` 对比 | 本次命中表 ⊆ 已见表 = 无新信息 |
| 5 | 是否空结果 | `after_tool` 读 `metadata["match_count"] == 0` | 空结果 = 检索不到 |

### 4.2 执行类（`run_sql`）

| # | 观测维度 | 数据来源 | 说明 |
|---|---|---|---|
| 1 | 调用次数 `calls` | `before_tool` 计数 | 每调用一次 +1 |
| 2 | 成功 / 失败 | `after_tool` 的 `result.success` | `success=False` 计为 error（SQL 写错） |
| 3 | SQL 骨架 | `after_tool` 读 `metadata["sql"]` → `extract_sql_skeleton()` | 归一化字面量/对象名后的结构，用于判断"LLM 是否收敛到稳定 SQL" |
| 4 | 行粒度 | `after_tool` 读 `metadata["row_count"]` + 骨架聚合形态 | `row_count==0` 计 empty；`granularity_aligned` = 行数与骨架聚合形态一致 |

## 5. `ToolResult.metadata` 拓展规范

三个工具当前已往 `metadata` 写了一些内容；为支撑上面的观测，需新增以下字段（**只在成功路径写入原始事实**，失败路径写 `error_type` 即可）：

| 工具 | 已记录 | 需新增 | 用途 |
|---|---|---|---|
| `search_table_schema` | `match_count` | `query`（原始查询）、`tables`（命中表名 list） | 重复 query / 无新表判断 |
| `search_metrics` | `match_count` | `query`（原始查询）、`matched_atomic_metrics` / `matched_derived_metrics` / `matched_composite_metrics`（命中指标名 list） | 重复 query / 无新表判断 |
| `run_sql` | `row_count`、`columns`、`results`、`output_file`、`error_type` | `sql`（原始 SQL） | 骨架提取、形状判断 |

> `run_sql` 的 `sql_shape` / 骨架**不在工具内计算**，由 hook 侧共享函数 `extract_sql_skeleton(sql)` 从 `metadata["sql"]` 派生，保持工具改动最小。

示例（`run_sql.py` 中 SELECT 成功分支追加一行）：

```python
result.metadata["sql"] = sql  # sql 为本次执行的原始 SQL 字符串
```

## 6. 共享状态 `ToolUsageTracker` 与归因

### 6.1 结构

```python
# request_id -> {tool_name: ToolUsageRecord}
class ToolUsageRecord:
    calls: int = 0
    successes: int = 0
    errors: int = 0
    consecutive_errors: int = 0             # 连续失败计数
    empties: int = 0                        # 空结果计数
    last_query: Optional[str] = None        # 检索类：上次 query
    query_repeat_count: int = 0             # 检索类：同 query 连续重复次数
    seen_tables: set[str] = set()           # 检索类：已见表/指标/维度的并集
    no_new_streak: int = 0                  # 检索类：连续无新表次数
    skeleton_counts: dict[str, int] = {}    # run_sql：骨架 -> 复现次数
    frozen_skeleton: Optional[str] = None   # run_sql：已冻结骨架
```

- 以 `request_id` 为 key：满足"单次提问内"的粒度；请求结束，记录随 tracker 的清理策略（或 asyncio task 结束）失效。
- 用 `asyncio.Lock` 保护读写，避免并发消息互相污染。
- **注意**：`ToolUsageRecord` 只存**原始观测事实**，不存派生状态；`OK / WARN / BLOCK` 由纯函数 `evaluate_state(policy, record)` 每次现算（见 §7、§8）。

### 6.2 contextvar 归因

`after_tool` 拿不到 `tool.name` 和 `request_id`，因此在 `before_tool` 里把它们写入 task-local 变量，`after_tool` 再读取：

```python
# core/agent/regulator.py
from contextvars import ContextVar
from typing import Optional, NamedTuple

class RequestScope(NamedTuple):
    request_id: str
    conversation_id: str
    user_id: str

# 作用域：before_tool 设置，贯穿整个请求（同 asyncio task），供 middleware 读取。
# 同一请求内所有 hook 写入相同的 request_id，故可共享一个模块级 contextvar。
_request_scope: ContextVar[Optional[RequestScope]] = ContextVar("easyq2sql_regulator_scope", default=None)
```

为何可行：`before_tool` 与 `after_tool` 在同一个 `_send_message` 协程内顺序执行（`agent.py` 工具循环），contextvar 是 task-local 的，天然隔离并发消息，无需全局锁式队列。

> **"当前工具名"用每个 hook 实例独立的 contextvar**（每个 hook 自己的 `__init__` 里创建，命名带 `id(self)`）。因为三个工具的 hook（`Sql/Schema/MetricRegulatorHook`）都会收到框架对**每一个** tool_call 触发的 `before_tool`/`after_tool`，若共用同一个 `_current_tool`，后一个 hook 会覆盖前一个 hook 的值、导致归因错乱。每个 hook 只在自己负责的工具命中时设置/读取它，互不干扰。

## 7. 判断标准

### 7.1 检索类状态机（`OK → WARN → BLOCK`）

| 状态 | 触发条件（默认阈值，可配置） |
|---|---|
| WARN | `calls ≥ 3` |
| BLOCK | `calls ≥ 5`，或 连续 error ≥ 2，或 同一 query 重复 ≥ 3，或 连续 empty ≥ 3，或 连续无新表 ≥ 2 |

### 7.2 执行类状态机（`run_sql`：`OK → WARN`，无 BLOCK）

| 状态 | 触发条件（默认阈值，可配置） |
|---|---|
| WARN | `calls ≥ 2`（软提示），或 连续 error ≥ 3（提示检查 SQL） |
| 骨架冻结（WARN 级提示） | 见 §7.3 |

> `run_sql` **不进入 BLOCK、绝不移除工具**（见 `middleware.md` §4.3）。

### 7.3 SQL 骨架冻结规则（run_sql 核心收敛判断）

当同一 `skeleton` 同时满足以下四项，即判定"LLM 已收敛到稳定 SQL 却仍在反复执行"：

- **骨架复现 ≥ 2**：`skeleton_counts[skeleton] ≥ 2`；
- **行粒度对齐**：每次返回 `row_count` 与骨架聚合形态一致（聚合骨架→少量分组行；明细骨架→与扫描一致）；
- **无缺口**：骨架结构完整（每个 JOIN 有 ON、SELECT 有 FROM、聚合与 GROUP BY 一致，基于 sqlparse 完整性检查）；
- **迭代数 ≥ 阈值**：本请求内 `run_sql` 调用次数达阈值（默认 3）。

→ 命中后写入 `frozen_skeleton`，后续对该骨架（或其同形变体）的 `run_sql` 触发**软干预提示**（详见 `middleware.md`）。

## 8. 代码示例

结构分三层，依赖方向单向（`lifecycle` / `middleware` 都只依赖 `core`，互不依赖）：

- `src/easyq2sql/core/agent/regulator.py` — **共享引擎**（框架中立，被观察者与干预者共同 import）：
  - `ToolState` / `ToolLimitPolicy` / `ToolUsageRecord` / `ToolUsageTracker` / `evaluate_state`
  - `extract_sql_skeleton` / `describe_sql_shape` / `_try_freeze`
  - `RequestScope` / `_request_scope` + 默认 tracker 单例 `get_default_tool_usage_tracker()`
  - 三个 policy 常量：`RUN_SQL_POLICY` / `SCHEMA_SEARCH_POLICY` / `METRIC_SEARCH_POLICY`
- `src/easyq2sql/core/lifecycle/sql_regulator.py` — `SqlRegulatorHook`（直接继承 `LifecycleHook`，观测 `run_sql`）
- `src/easyq2sql/core/lifecycle/schema_regulator.py` — `SchemaRegulatorHook`（观测 `search_table_schema`）
- `src/easyq2sql/core/lifecycle/metric_regulator.py` — `MetricRegulatorHook`（观测 `search_metrics`）

（干预侧对应三个 middleware 在 `core/middleware/` 下，见 `middleware.md`。）

### 8.1 状态与跟踪器（`core/agent/regulator.py`）

```python
import asyncio
from enum import Enum
from typing import Dict, Optional, Set

class ToolState(str, Enum):
    OK = "ok"
    WARN = "warn"
    BLOCK = "block"

class ToolUsageRecord:
    def __init__(self) -> None:
        self.calls = 0
        self.successes = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.empties = 0
        self.last_query: Optional[str] = None
        self.query_repeat_count = 0
        self.seen_tables: Set[str] = set()
        self.no_new_streak = 0
        self.skeleton_counts: Dict[str, int] = {}
        self.frozen_skeleton: Optional[str] = None

class ToolUsageTracker:
    """以 request_id 为 key 的工具执行状态仓库。"""
    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, ToolUsageRecord]] = {}
        self._lock = asyncio.Lock()

    def _get(self, request_id: str, tool_name: str) -> ToolUsageRecord:
        return self._records.setdefault(request_id, {}).setdefault(tool_name, ToolUsageRecord())

    async def record_call(self, request_id: str, tool_name: str) -> None:
        async with self._lock:
            self._get(request_id, tool_name).calls += 1

    async def record_result(self, request_id: str, tool_name: str, result) -> None:
        # 见源码：解析 result.metadata 完成
        # error / empty / 重复 query / 无新表 / SQL 骨架计数
        ...

    async def get_record(self, request_id: str, tool_name: str) -> ToolUsageRecord:
        async with self._lock:
            return self._get(request_id, tool_name)
```

### 8.2 SQL 骨架提取（`core/agent/regulator.py`）

```python
def extract_sql_skeleton(sql: str) -> str:
    """把 SQL 归一化为结构骨架：字面量/对象名替换为 `?`，保留 JOIN/GROUP BY/窗口/rollup 结构。

    示例：
      "SELECT name FROM users WHERE id = 3"        -> "SELECT ? FROM ? WHERE ? = ?"
      "SELECT dept, SUM(sal) FROM t GROUP BY dept" -> "SELECT ? , ? ( ? ) FROM ? GROUP BY ?"
    """
    # 基于 sqlparse 实现，详见 core/agent/regulator.py
    ...
```

### 8.3 观察者 Hook（`core/lifecycle/*_regulator.py`）

每个工具的 hook **直接继承 `LifecycleHook`**（不经过中间基类），从 `core.agent.regulator` 导入共享引擎。三个文件结构相同，仅 `tool_name` / `policy` / 是否含骨架冻结检测有差异。以 `run_sql`（含冻结检测）为例：

```python
# core/lifecycle/sql_regulator.py
from contextvars import ContextVar
from typing import Optional

from ..agent.regulator import (
    RUN_SQL_POLICY, RequestScope, _request_scope,
    _try_freeze, get_default_tool_usage_tracker,
)
from .base import LifecycleHook


class SqlRegulatorHook(LifecycleHook):
    """Observe ``run_sql`` and record its execution facts into the tracker."""

    tool_name = "run_sql"
    policy = RUN_SQL_POLICY

    def __init__(self, tracker=None) -> None:
        self._tracker = tracker or get_default_tool_usage_tracker()
        # Per-instance contextvar: 每个 hook 只归因自己的工具，多个 regulator 并存不互相覆盖
        self._current_tool: ContextVar[Optional[str]] = ContextVar(
            f"easyq2sql_regulator_current_tool_{id(self)}", default=None
        )

    async def before_tool(self, tool, context) -> None:
        if tool.name != self.tool_name:
            return
        _request_scope.set(RequestScope(
            request_id=context.request_id,
            conversation_id=context.conversation_id,
            user_id=context.user.id,
        ))
        self._current_tool.set(tool.name)
        await self._tracker.record_call(context.request_id, tool.name)

    async def after_tool(self, result):
        tool_name = self._current_tool.get()
        self._current_tool.set(None)
        if not tool_name:
            return None
        scope = _request_scope.get()
        if scope is None:
            return None
        await self._tracker.record_result(scope.request_id, tool_name, result)

        # run_sql 专属：检测"已收敛却仍在重跑"的 SQL 骨架
        sql = (result.metadata or {}).get("sql")
        if sql:
            record = await self._tracker.get_record(scope.request_id, tool_name)
            _try_freeze(record, self.policy, sql, (result.metadata or {}).get("row_count"))
        return None  # 只观测，不改写结果

    async def after_message(self, result) -> None:
        scope = _request_scope.get()
        if scope is not None:
            self._tracker.drop_request(scope.request_id)
        _request_scope.set(None)
```

`SchemaRegulatorHook` / `MetricRegulatorHook`（`schema_regulator.py` / `metric_regulator.py`）结构同上，仅：`tool_name` / `policy` 换成 `search_table_schema` / `search_metrics` 与 `SCHEMA_SEARCH_POLICY` / `METRIC_SEARCH_POLICY`，且 `after_tool` 中**无骨架冻结分支**（检索工具不涉及 SQL 骨架）。

### 8.4 策略与状态派生（`core/agent/regulator.py`）

```python
from dataclasses import dataclass

@dataclass
class ToolLimitPolicy:
    warn_calls: int = 3
    block_calls: int = 5
    max_errors: int = 2
    max_empty: int = 3
    max_repeat: int = 3
    max_no_new: int = 2
    hard_block: bool = True       # run_sql 为 False（只软不硬）
    freeze_reproduce: int = 2
    freeze_iterations: int = 3
    warn_text: str = "Called too many times; stop repeating."
    block_text: str = "Call limit reached; this tool is now disabled."

# 三个 policy 常量集中定义在 core/agent/regulator.py（hook 与 middleware 都从这里 import）：
#   RUN_SQL_POLICY       -> hard_block=False，warn_calls=2，max_errors=3
#   SCHEMA_SEARCH_POLICY -> hard_block=True，默认检索阈值
#   METRIC_SEARCH_POLICY -> hard_block=True，默认检索阈值

def evaluate_state(policy: ToolLimitPolicy, record: ToolUsageRecord) -> ToolState:
    # 纯函数：据 policy 阈值 + record 观测事实返回 OK / WARN / BLOCK
    # run_sql（hard_block=False）永不返回 BLOCK
    ...
```

## 9. 限制与后续

- **重复 query / SQL 检测依赖 metadata 拓展**：hook 本身拿不到参数，需先在三个工具里补 `query` / `metric` / `tables` / `sql` 字段。
- **"无缺口"与"行粒度对齐"为启发式**：依赖 sqlparse 的完整性检查与行数区间估计，存在误判空间，阈值应可调。
- **tracker 为进程内存态**：重启即失、不跨进程；多实例部署需外置存储（可参考 `quota_lifecycle_example.py` 的 in-memory 先例，后续可换 Redis）。
- **后续扩展**：若需更细粒度的参数级观测（如具体 JOIN 深度、WHERE 列数），可在工具里继续拓展 `metadata`，无需改动 hook/middleware 结构。
