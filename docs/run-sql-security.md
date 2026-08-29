# run_sql 执行前安全检查 · EnhancedToolRegistry 设计

> 配套文档：
> - `docs/hook.md` / `docs/middleware.md` —— 工具执行**运行期**收敛（重复调用、骨架冻结），由 `core/agent/regulator.py` 的 hook + middleware 负责；
> - `docs/sql-safety-deployment.md` —— **数据库侧**加固清单（原生 RLS、只读账号、掩码、超时等），是应用层校验无法替代的兜底。
>
> 本文描述的是**应用层第一道防线**：在 `run_sql` 真正执行 SQL **之前**，对 LLM 生成的 SQL 做一次性安全校验与改写。

---

## 1. 角色定位

`EnhancedToolRegistry` 是 `ToolRegistry` 的子类，只 override 一个方法 `transform_args()`。它充当 `run_sql` 工具的**执行前安全闸门**：

- **一次性**：在每次 `run_sql` 工具调用、参数通过 Pydantic 校验之后、SQL 交给 `SqlRunner` 之前执行一次。
- **可拒绝**：校验不通过时返回 `ToolRejection`，`execute()` 会把它转成 `success=False` 的 `ToolResult` 回传给 LLM（LLM 看到拒绝原因后可自行修正重试）。
- **可改写**：RLS 行级过滤在放行前把 WHERE 条件注入 SQL，透明地限制用户只能看到自己有权访问的行。

它与 regulator 框架（`core/agent/regulator.py`）**分工不同、互不重叠**：

| 维度 | EnhancedToolRegistry（本文） | regulator 框架 |
|---|---|---|
| 作用点 | `transform_args`（执行**前**） | `before_tool` / `after_tool` + `before_llm_request`（执行前后 + LLM 请求前） |
| 目标 | 单条 SQL 是否安全/合规（注入、复杂度、禁查、语义、只读、RLS） | 工具**调用节奏**是否收敛（重复搜索、SQL 反复重跑、骨架冻结） |
| 手段 | 拒绝（`ToolRejection`）或改写 SQL | 软引导（注入 system_prompt）/ 硬移除工具 schema |
| 粒度 | 单次工具调用 | 一次用户消息内的多次调用 |

---

## 2. 设计原理

### 2.1 为什么挂在 `transform_args`

项目框架已预留了正确扩展点，**无需改动 Agent / registry 执行链路**：

- `core/registry.py::ToolRegistry.transform_args()` 是 NoOp 钩子，注释明确写着可用于「Applying row-level security (RLS) to SQL queries」「Validating required arguments」；
- `core/registry.py::ToolRegistry.execute()` 已接线：`transform_args` 返回 `ToolRejection` 时，直接转成 `success=False` 的 `ToolResult`（`result_for_llm` = 拒绝原因）；
- `core/tool/models.py::ToolRejection`（`reason: str`）已存在。

因此只需继承并 override `transform_args`，`execute()` 的既有逻辑自然生效。

### 2.2 为什么用 sqlglot AST 而非正则

早期从 `QueryMind` 拷贝的 `rls_registry.py` 用**正则**做表抽取与 RLS 改写，存在致命缺陷：

- `re.findall(r"(?:FROM|JOIN)\s+…)` 无法正确处理**别名、CTE、子查询、UNION** 中的表引用；
- 用正则往 SQL 里硬拼 `WHERE` 会破坏已有 `WHERE/GROUP BY/ORDER BY/LIMIT` 的结构；
- 子串匹配表名会**误伤**（例如表 `order` 会命中 `ORDER BY`）。

本项目 `sqlglot>=25` 已是正式依赖（`pyproject.toml`）。sqlglot 提供：

- **稳健解析**：`sqlglot.parse_one(sql, dialect)`，支持多方言（Postgres/MySQL/TSQL/BigQuery/…），非法 SQL 直接抛异常 → 可据此拒绝；
- **结构化遍历**：`ast.find_all(exp.Table)` / `exp.Func` / `exp.Join` 等，精确抽取表名、函数名、JOIN、CTE、子查询、窗口函数；
- **安全改写**：`exp.And` / `exp.In` / `ast.where(...)` 在 AST 上构造谓词，再由 `ast.sql(dialect)` 回吐 SQL，天然处理别名与已有 WHERE。

因此本文所有「结构校验」与「RLS 改写」均基于 sqlglot AST；只有「注入/危险模式」这类**对原始字符串敏感**的检测（注释注入、栈式分号、十六进制编码等）才用正则，且只做**黑名单命中**、不做结构改写。

---

## 3. 触发逻辑

### 3.1 调用时机

```
registry.execute(tool_call, context)
  │
  ├─ ① 查工具、② 校验权限、③ Pydantic 校验参数
  │
  ├─ ④ transform_args(tool, validated_args, user, context)   ← EnhancedToolRegistry 在此介入
  │        └─ 6 个检查点（见 §3.2）
  │              ├─ 命中拒绝 → return ToolRejection(reason)
  │              └─ RLS 改写 → args.sql = 改写后 SQL
  │
  ├─ ⑤ isinstance(ToolRejection)? → 返回 success=False 的 ToolResult（reason 回传 LLM）
  │
  └─ ⑥ tool.execute(context, final_args)   ← 真正执行
```

### 3.2 检查点顺序与判定

顺序原则：**廉价拒绝在前、改写最后**。`transform_args` 内部流程：

```
1. 工具过滤：仅 tool.name ∈ {run_sql, RunSqlTool} 且 isinstance(args, RunSqlToolArgs)，否则原样返回
2. 解析：sqlglot.parse_one(sql, dialect) 抛异常 → 拒绝「无法解析的 SQL」
3. ① 注入/危险语句 → 拒绝
4. ② 只读/写语句治理 → 拒绝
5. ③ 复杂度/资源限制 → 拒绝
6. ④ 禁查表/危险函数 → 拒绝
7. ⑤ 语义结构校验 → 拒绝
8. ⑥ RLS 行级过滤 → 改写 args.sql（仅 SELECT）
9. 返回 args（可能已改写）
```

| # | 检查点 | 判定方式 | 失败结果 | 默认状态 |
|---|--------|----------|----------|----------|
| ① | 注入/危险语句 | 正则黑名单 `forbidden_patterns` + AST 多语句/危险 DDL | `ToolRejection` | 开 |
| ② | 只读治理 | `read_only` 时 AST 根语句非 SELECT/WITH-SELECT | `ToolRejection` | 开（read_only=true） |
| ③ | 复杂度 | 长度 / 子查询 / CTE / JOIN / 结果行 超限 | `ToolRejection` | 开 |
| ④ | 禁查表/危险函数 | AST 抽取表名/函数名命中 `forbidden_tables` / `blocked_functions` | `ToolRejection` | 开 |
| ⑤ | 语义结构 | AST 启发式（JOIN 缺 ON、聚合列游离 GROUP BY、窗口缺 PARTITION BY 等） | `ToolRejection` | 开 |
| ⑥ | RLS 行级过滤 | `protected_tables` 命中 → 注入 WHERE；无权限 → `WHERE 1=0` | **改写**（非拒绝） | 开 |

### 3.3 各检查点细节

**① 注入/危险语句**

- 正则黑名单（保留拷贝版、修正误判）：`;--`、`/*…*/`、`;\s*(DROP|DELETE|TRUNCATE|ALTER|CREATE)`、`;\s*(INSERT|UPDATE|REPLACE)`、`UNION\s+DROP`、`;\s*;`、`xp_`、`(EXEC|EXECUTE)\s*\(`、`(LOAD_FILE|INTO\s+OUTFILE|INTO\s+DUMPFILE)`、`(SLEEP\(|BENCHMARK\()`、`0x[0-9a-f]+`、`xp_cmdshell`。
- **去掉**拷贝版笼统的 `(pg_|pg_catalog|information_schema|sys\.)` 黑名单（会误伤合法标识符、且 schema 发现需要访问元数据），改由 `allowed_metadata_patterns` 白名单 + AST 判断。
- AST 补充：`sqlglot.parse(sql)` 解析出**多条语句**（栈式查询）→ 拒绝；AST 根语句为 DDL/DCL（`CREATE/ALTER/DROP/TRUNCATE/GRANT/REVOKE`）→ 拒绝。

**② 只读/写语句治理**

`query_governance.read_only=true` 时，仅放行 `SELECT`（含 `WITH … SELECT`）；`INSERT/UPDATE/DELETE/MERGE` 及一切 DDL/DCL 拒绝。若业务确实需要写库，可将 `read_only` 置 `false` 并按 `allowed_statements` 白名单放行。

**③ 复杂度/资源限制**

- `max_query_length`：原始 SQL 字符数上限；
- `max_subqueries`：`ast.find_all(exp.Subquery)` 计数；
- `max_cte_depth`：`ast.find_all(exp.CTE)` 计数；
- `max_joins`：`ast.find_all(exp.Join)` 计数；
- `max_result_rows`：显式 `LIMIT n` 且 `n > max_result_rows` → 拒绝（防一次性拉全表）。

**④ 禁查表/危险函数**

- `forbidden_tables`：用 `ast.find_all(exp.Table)` 抽取表名（含 schema 限定，如 `Sales.CreditCard`），命中即拒绝；
- `blocked_functions`：用 `ast.find_all(exp.Func)` / `exp.Anonymous` 抽取函数名（如 `pg_read_file`、`COPY … PROGRAM`），命中即拒绝。

**⑤ 语义结构校验**（`sql_semantics` 各开关）

- `check_join`：每个 `JOIN` 必须有 `ON` 或 `USING`（否则笛卡尔积）；
- `check_aggregation`：含聚合函数时，`SELECT` 中的非聚合列必须出现在 `GROUP BY`；
- `check_window` + `require_partition_by_for_window_cues`：窗口函数 `OVER(...)` 无 `PARTITION BY` 且配置要求时拒绝；
- `check_rollup`：`ROLLUP/CUBE/GROUPING SETS` 的结构检查；
- `check_partition_constant`：分区键与常量比较（避免全分区扫描）的保守检查；
- `check_outer_join_null_filter`：外连接后在 WHERE 对可空侧过滤（可能把外连接退化为内连接）的检查。

> 语义校验为**保守启发式**：只拒绝明确违规（如 JOIN 缺 ON、聚合列游离），阈值可在配置中逐项开关。

**⑥ RLS 行级过滤**（详见 §6）

---

## 4. ToolRejection 说明

`transform_args` 返回 `ToolRejection(reason=…)`（见 `core/tool/models.py`）。与「在 `before_tool` 钩子里抛异常」的**本质区别**：

| | ToolRejection（本文） | hook 抛 AgentError |
|---|---|---|
| 影响范围 | **仅这一条 SQL** 被拒绝 | `before_tool` 无局部 try/except，异常上抛，最终由 `send_message` 兜底捕获，**中止整条消息** |
| LLM 收到的反馈 | `result_for_llm = reason`，作为 tool result 回传，LLM 可据此修正 | 通用错误 UI，LLM 拿不到具体原因 |
| 可恢复性 | 优雅、可重试 | 毁掉整个请求 |

拒绝原因统一前缀 `SQL rejected: `，后接中文说明，例如：

```
SQL rejected: 检测到 SQL 注入风险（statement termination followed by destructive DDL）
SQL rejected: 当前为只读模式，禁止执行非 SELECT 语句（INSERT）
SQL rejected: 查询超长（12000 > 10000）
SQL rejected: 禁止查询表 Sales.CreditCard
SQL rejected: 语义校验失败：JOIN 缺少 ON 条件
SQL rejected: 无法解析的 SQL 语句（语法错误）
```

---

## 5. 配置参考（`sql_security_config.yaml`）

配置放在包根 `src/easyq2sql/sql_security_config.yaml`，加载顺序：**传入路径 → 包资源 `importlib.resources` → 同目录兜底 → 内置默认**。全部字段用 Pydantic `SqlSecurityConfig` 承载，带类型与默认值。

```yaml
# ============================================================
# SQL 注入 / 危险语句
# ============================================================
sql_injection:
  enabled: true

  # 白名单：命中这些"只读元数据探测"模式时，跳过系统目录黑名单
  allowed_metadata_patterns:
    - pattern: "\\binformation_schema\\."
      description: "只读元数据探测"
      case_sensitive: false

  # 黑名单：命中即拒绝
  forbidden_patterns:
    - pattern: ";--"
      description: "注释注入截断语句"
    - pattern: "/\\*.*\\*/"
      description: "块注释注入"
    - pattern: ";\\s*(DROP|DELETE|TRUNCATE|ALTER|CREATE)"
      description: "语句终止后接破坏性 DDL"
      case_sensitive: false
    - pattern: "(LOAD_FILE|INTO\\s+OUTFILE|INTO\\s+DUMPFILE)"
      description: "文件读写注入"
      case_sensitive: false
    - pattern: "(SLEEP\\(|BENCHMARK\\()"
      description: "时间盲注"
      case_sensitive: false
    - pattern: "xp_cmdshell"
      description: "OS 命令执行"
      case_sensitive: false

# ============================================================
# 只读 / 写语句治理
# ============================================================
query_governance:
  enabled: true
  read_only: true          # true：仅放行 SELECT（含 WITH ... SELECT）

# ============================================================
# 复杂度 / 资源限制
# ============================================================
query_limits:
  enabled: true
  max_query_length: 10000   # SQL 字符数上限
  max_subqueries: 5         # 子查询数上限
  max_cte_depth: 3          # CTE 数上限
  max_joins: 15             # JOIN 数上限
  max_result_rows: 10000    # 显式 LIMIT 上限

  # 禁止直接查询的表（含 schema 限定）
  forbidden_tables:
    - "Person.Password"
    - "Sales.CreditCard"

  # 危险函数黑名单
  blocked_functions:
    - "pg_read_file"
    - "pg_write_file"
    - "LOAD_FILE"

# ============================================================
# 语义结构校验
# ============================================================
sql_semantics:
  enabled: true
  check_join: true
  check_aggregation: true
  check_window: true
  check_rollup: true
  check_partition_constant: true
  check_outer_join_null_filter: true
  require_partition_by_for_window_cues: true

# ============================================================
# RLS 行级过滤
# ============================================================
row_level_security:
  enabled: true             # 默认开启；protected_tables 为空时为空操作

  # 用户组 -> 允许的值集合（RLS 按此过滤）
  group_value_mapping:
    sales_west: [1, 2, 3]
    admin: ["*"]            # "*" 表示全部放行

  # 受保护表；每表指定权限列（直接列）或间接列（via join）
  protected_tables:
    - table: "Sales.SalesOrderHeader"
      column: "TerritoryID"          # 直接列：WHERE TerritoryID IN (...)
    - table: "Sales.SalesOrderDetail"
      column: ""                     # 间接列：经 via join 关联到父表权限列
      via:
        join_table: "Sales.SalesOrderHeader"
        join_column: "SalesOrderID"
        via_column: "TerritoryID"

# ============================================================
# 日志 / 审计
# ============================================================
audit:
  log_sql_transformations: true   # 记录 RLS 改写
  log_rejected_queries: true      # 记录拒绝原因
```

---

## 6. RLS 行级过滤说明

RLS 只对 `SELECT` 生效（写语句已在治理层拒绝）。逻辑：

1. `enabled=false` 或 `protected_tables` 为空 → 跳过；
2. 用 AST 找出查询引用的表（含别名），与 `protected_tables` 匹配；
3. 汇总 `user.group_memberships` 命中的允许值集合；
4. 对每个命中表追加谓词；**无权限 → 注入 `WHERE 1=0`**（返回空集，绝不泄露数据）。

### 6.1 直接列改写示例

配置：`protected_tables: [{table: "Orders", column: "region"}]`，用户 `sales_west` 允许 `[1,2,3]`。

```sql
-- 改写前
SELECT o.id, o.amount FROM Orders o WHERE o.amount > 100

-- 改写后（保留别名，AND 追加，正确处理已有 WHERE）
SELECT o.id, o.amount FROM Orders o WHERE o.amount > 100 AND (o.region IN (1, 2, 3) OR o.region IS NULL)
```

无权限用户：

```sql
SELECT o.id, o.amount FROM Orders o WHERE o.amount > 100
-- 改写后
SELECT o.id, o.amount FROM Orders o WHERE o.amount > 100 AND 1 = 0
```

### 6.2 间接列（via join）改写示例

配置：`SalesOrderDetail` 经 `SalesOrderHeader.SalesOrderID` 关联到权限列 `TerritoryID`。

```sql
-- 改写前
SELECT d.* FROM Sales.SalesOrderDetail d WHERE d.UnitPrice > 50

-- 改写后（EXISTS 子查询，把父表权限条件带入）
SELECT d.*
FROM Sales.SalesOrderDetail d
WHERE d.UnitPrice > 50
  AND EXISTS (
    SELECT 1 FROM Sales.SalesOrderHeader h
    WHERE h.SalesOrderID = d.SalesOrderID
      AND (h.TerritoryID IN (1, 2, 3) OR h.TerritoryID IS NULL)
  )
```

> 间接列（via join）改写复杂度更高，首版以 `EXISTS` 子查询实现；若项目 DB 已启用原生 RLS，优先用 DB 侧策略（见 `sql-safety-deployment.md`），应用层 RLS 作为补充。

---

## 7. 端到端示例

### 7.1 注入拒绝

```
输入 SQL:  SELECT 1; DROP TABLE users
检查点①:   命中 forbidden_patterns ";\s*(DROP|...)"
输出:      ToolRejection("SQL rejected: 检测到 SQL 注入风险（statement termination followed by destructive DDL）")
execute(): 返回 success=False 的 ToolResult，reason 回传 LLM
```

### 7.2 只读治理拒绝

```
输入 SQL:  UPDATE users SET pwd = 'x' WHERE id = 1
检查点②:   read_only=true，AST 根语句为 Update
输出:      ToolRejection("SQL rejected: 当前为只读模式，禁止执行非 SELECT 语句（UPDATE）")
```

### 7.3 复杂度拒绝

```
输入 SQL:  SELECT ...（JOIN 16 张表）
检查点③:   16 > max_joins(15)
输出:      ToolRejection("SQL rejected: JOIN 数量超限（16 > 15）")
```

### 7.4 禁查表拒绝

```
输入 SQL:  SELECT * FROM Sales.CreditCard
检查点④:   AST 抽取表名 Sales.CreditCard 命中 forbidden_tables
输出:      ToolRejection("SQL rejected: 禁止查询表 Sales.CreditCard")
```

### 7.5 RLS 改写（放行）

见 §6.1 / §6.2，改写后 `args.sql` 更新，正常执行。

---

## 8. 接线

`EnhancedToolRegistry` 是 `ToolRegistry` 的**直接替换**，构造 Agent 时把 registry 换掉即可：

```python
from easyq2sql.enhanced_tool_registry import EnhancedToolRegistry
from easyq2sql.tools import RunSqlTool
from easyq2sql.integrations.sqlite import SqliteRunner

# 用安全 registry 替代 ToolRegistry()；config_path 可选，默认加载包内 sql_security_config.yaml
registry = EnhancedToolRegistry()
registry.register_local_tool(RunSqlTool(sql_runner=SqliteRunner(database_path="app.sqlite")))

agent = Agent(
    llm_service=llm,
    tool_registry=registry,   # ← 换成安全 registry
    config=AgentConfig(...),
)
```

---

## 9. 限制与后续

- **应用层校验是"第一道防线"，不是兜底**：一旦上层被绕过，仍需 DB 侧原生 RLS、只读账号、语句超时、驱动多语句关闭等兜底（见 `sql-safety-deployment.md`）。
- **语义校验是启发式**：`check_aggregation` / `check_partition_constant` 等存在误判空间，默认「只拒绝明确违规」，阈值逐项可开关。
- **RLS 依赖 AST 正确性**：极端嵌套 / 方言特有的语法改写可能不完整，上线前应针对目标方言补测试。
- **配置为进程内静态**：`group_value_mapping` 与 `protected_tables` 在启动时加载；若权限表来自外部系统，可在 `transform_args` 内替换为动态 `user_value_resolver`（预留扩展点）。
- **骨架冻结不在本文范围**：run_sql 的「重复执行/收敛」由 regulator 框架软引导处理，二者可叠加、互不干扰。
