"""
Prompt templates for the metric-graph extraction engine.

LightRAG-style prompt texts (system / user / continuation) plus the few-shot
examples, used by :mod:`easyq2sql.metric_graph.engine`. The placeholder
substitutions (``{tuple_delimiter}``, ``{completion_delimiter}``,
``{entity_types}``, ``{relationship_types}``, ``{examples}``, ``{language}``,
``{input_text}``) are applied by ``extract_entities``.
"""

_ENTITY_EXTRACTION_SYSTEM_PROMPT = """---Role---
You are a Knowledge Graph Specialist responsible for extracting entities and relationships from the input text.

---Instructions---
1.  **Entity Extraction & Output:**
    *   **Identification:** Identify clearly defined and meaningful entities in the input text.
    *   **Entity Details:** For each identified entity, extract the following information:
        *   `entity_name`: The name of the entity. If the entity name is case-insensitive, capitalize the first letter of each significant word (title case). Ensure **consistent naming** across the entire extraction process.
        *   `entity_type`: Categorize the entity using STRICTLY one of the following types:
{entity_types}
        **CRITICAL: You MUST NOT invent any new entity types. You MUST rely EXACTLY on the Chinese labels listed above. Read their descriptions carefully to classify correctly. If an entity does not fit ANY of the provided types, do NOT output it at all. Failure to match exactly will break the JSON schema.**
        *   `entity_description`: Provide a concise yet comprehensive description of the entity's attributes and activities, based *solely* on the information present in the input text.
        *   `properties`: A JSON string containing key-value pairs of specific attributes extracted for this entity. Extract as many relevant quantitative and qualitative details as possible. **CRITICAL: The property keys MUST come from the provided schema (Chinese keys) whenever available; do NOT invent new property keys.** If a detail has no matching schema field, omit it. (e.g., {{ "姓名": "张三", "评估价值": 3000000 }}).
    *   **Output Format - Entities:** Output a total of 5 fields for each entity, delimited by `{tuple_delimiter}`, on a single line. The first field *must* be the literal string `entity`.
        *   Format: `entity{tuple_delimiter}entity_name{tuple_delimiter}entity_type{tuple_delimiter}entity_description{tuple_delimiter}properties`

2.  **Relationship Extraction & Output:**
    *   **Identification:** Identify direct, clearly stated, and meaningful relationships between previously extracted entities.
    *   **N-ary Relationship Decomposition:** If a single statement describes a relationship involving more than two entities (an N-ary relationship), decompose it into multiple binary (two-entity) relationship pairs for separate description.
    *   **Relationship Details:** For each binary relationship, extract the following fields:
        *   `source_entity`: The name of the source entity. Ensure **consistent naming** with entity extraction.
        *   `target_entity`: The name of the target entity. Ensure **consistent naming** with entity extraction.
        *   `relationship_keywords`: A single keyword summarizing the relationship. **CRITICAL: You MUST choose EXACTLY ONE relationship type from the provided list:**
{relationship_types}
        **CRITICAL: You MUST rely EXACTLY on the Chinese labels listed above. If none of the provided relationship types apply, do NOT output that relationship.**
        *   `relationship_description`: A concise explanation of the nature of the relationship between the source and target entities.
        *   `properties`: A JSON string containing key-value pairs of specific attributes for this relationship. **CRITICAL: The property keys MUST come from the provided schema (Chinese keys) whenever available; do NOT invent new property keys.** If a detail has no matching schema field, omit it. (e.g., {{ "权重": 1.0, "任职时间区间": "2020年" }}).
    *   **Output Format - Relationships:** Output a total of 6 fields for each relationship, delimited by `{tuple_delimiter}`, on a single line. The first field *must* be the literal string `relation`.
        *   Format: `relation{tuple_delimiter}source_entity{tuple_delimiter}target_entity{tuple_delimiter}relationship_keywords{tuple_delimiter}relationship_description{tuple_delimiter}properties`

3.  **Delimiter Usage Protocol:**
    *   The `{tuple_delimiter}` is a complete, atomic marker and **must not be filled with content**. It serves strictly as a field separator.
    *   **Incorrect Example:** `entity{tuple_delimiter}Tokyo<|location|>Tokyo is the capital of Japan.`
    *   **Correct Example:** `entity{tuple_delimiter}Tokyo{tuple_delimiter}location{tuple_delimiter}Tokyo is the capital of Japan.`

4.  **Relationship Direction & Duplication:**
    *   Treat all relationships as **undirected** unless explicitly stated otherwise. Swapping the source and target entities for an undirected relationship does not constitute a new relationship.
    *   Avoid outputting duplicate relationships.

5.  **Output Order & Prioritization:**
    *   Output all extracted entities first, followed by all extracted relationships.
    *   Within the list of relationships, prioritize and output those relationships that are **most significant** to the core meaning of the input text first.

6.  **Context & Objectivity:**
    *   Ensure all entity names and descriptions are written in the **third person**.
    *   Explicitly name the subject or object; **avoid using pronouns** such as `this article`, `this paper`, `our company`, `I`, `you`, and `he/she`.

7.  **Language & Proper Nouns:**
    *   The entire output (entity names, keywords, and descriptions) must be written in `{language}`.
    *   Proper nouns (e.g., personal names, place names, organization names) should be retained in their original language if a proper, widely accepted translation is not available or would cause ambiguity.

8.  **Completion Signal:** Output the literal string `{completion_delimiter}` only after all entities and relationships, following all criteria, have been completely extracted and outputted.

9.  **Metric Definitions (CRITICAL):**
    原子指标：业务度量的最小单元，不可进一步拆解，承载核心业务统计口径与原始计算逻辑，不附加任何过滤限定条件。示例：下单总数。
    派生指标：由原子指标 + 一个维度组合生成，通过维度对原子指标做范围过滤，刻画特定业务约束下的业务结果，用于反映细分场景下的业务现状。
        维度：对业务统计范围进行限定、过滤的约束条件，常见如时间区间、终端类型、地域、渠道等；同一个派生指标可叠加多组维度做多层筛选。示例：近一日下单总数。
    复合指标：以派生指标为计算输入，经过环比、同比、差值、占比等二次组合运算得到，主要服务跨周期、跨维度的数据对比分析场景。示例：某业务周环比增长率。

10. **Metric Extraction Rules (CRITICAL):**
    *  不要把维度当做原子指标。
    *  不要根据维度值罗举生成派生指标。一个原子指标和一个维度只生成一个派生指标。
---Examples---
{examples}

---Real Data to be Processed---
<Input>
Text:
```
{input_text}
```
"""

_ENTITY_EXTRACTION_USER_PROMPT = """---Task---
Extract entities and relationships from the input text to be processed.

---Instructions---
1.  **Strict Adherence to Format:** Strictly adhere to all format requirements for entity and relationship lists, including output order, field delimiters, and proper noun handling, as specified in the system prompt.
2.  **Output Content Only:** Output *only* the extracted list of entities and relationships. Do not include any introductory or concluding remarks, explanations, or additional text before or after the list.
3.  **Completion Signal:** Output `{completion_delimiter}` as the final line after all relevant entities and relationships have been extracted and presented.
4.  **Output Language:** Ensure the output language is {language}. Proper nouns (e.g., personal names, place names, organization names) must be kept in their original language and not translated.

<Output>
"""

_ENTITY_CONTINUE_EXTRACTION_USER_PROMPT = """---Task---
Based on the last extraction task, identify and extract any **missed or incorrectly formatted** entities and relationships from the input text.

---Instructions---
1.  **Strict Adherence to System Format:** Strictly adhere to all format requirements for entity and relationship lists, including output order, field delimiters, and proper noun handling, as specified in the system instructions.
2.  **Focus on Corrections/Additions:**
    *   **Do NOT** re-output entities and relationships that were **correctly and fully** extracted in the last task.
    *   If an entity or relationship was **missed** in the last task, extract and output it now according to the system format.
    *   If an entity or relationship was **truncated, had missing fields, or was otherwise incorrectly formatted** in the last task, re-output the *corrected and complete* version in the specified format.
3.  **Output Format - Entities:** Output a total of 5 fields for each entity, delimited by `{tuple_delimiter}`, on a single line. The first field *must* be the literal string `entity`.
    *   Format: `entity{tuple_delimiter}entity_name{tuple_delimiter}entity_type{tuple_delimiter}entity_description{tuple_delimiter}properties`
4.  **Output Format - Relationships:** Output a total of 6 fields for each relationship, delimited by `{tuple_delimiter}`, on a single line. The first field *must* be the literal string `relation`.
    *   Format: `relation{tuple_delimiter}source_entity{tuple_delimiter}target_entity{tuple_delimiter}relationship_keywords{tuple_delimiter}relationship_description{tuple_delimiter}properties`
5.  **Output Content Only:** Output *only* the extracted list of entities and relationships. Do not include any introductory or concluding remarks, explanations, or additional text before or after the list.
6.  **Completion Signal:** Output `{completion_delimiter}` as the final line after all relevant missing or corrected entities and relationships have been extracted and presented.
7.  **Output Language:** Ensure the output language is {language}. Proper nouns (e.g., personal names, place names, organization names) must be kept in their original language and not translated.

<Output>
"""

# NOTE: the JSON braces in the examples are literal (unescaped). extract_entities
# only replaces the delimiter placeholders via .replace(), never .format(), so the
# {"key": ...} literals are not mistaken for format fields.
_ENTITY_EXTRACTION_EXAMPLES = """<Input Text>
```
# Table: pay_order
Description: 支付订单明细
[
(id:bigint, Primary Key, 订单号
Examples: [1, 2, 3], Value Range: 1 ~ 1000000),
(terminal_type:varchar(20), 终端类型
Examples: [PC, 移动, PC], Value Range: [PC, 移动]),
(pay_amount:decimal(18,2), 支付金额(元)
Examples: [199.00, 89.00, 350.00]),
(pay_user_id:varchar(64), 支付用户ID
Examples: [u1001, u1002, u1003]),
(pay_time:date, 时间区间
Examples: [近一周，近一个月]),Value Range: [近一周，近一个月]),
]
```

<Output>
entity {tuple_delimiter} PayAmount_Atomic {tuple_delimiter} 原子指标 {tuple_delimiter} 支付金额 {tuple_delimiter}{"指标名称":"支付金额","业务描述":"单笔支付订单的支付金额","来源字段":"pay_amount","计算函数":"sum"}
entity {tuple_delimiter} PayUserCnt_Atomic {tuple_delimiter} 原子指标 {tuple_delimiter} 支付用户数 {tuple_delimiter}{"指标名称":"支付用户数","业务描述":"发生支付的去重用户数","来源字段":"pay_user_id","计算函数":"count_distinct"}
entity {tuple_delimiter} PayAmount_time {tuple_delimiter} 派生指标 {tuple_delimiter} 支付金额（按时间区间） {tuple_delimiter}{"指标名称":"支付金额（按时间区间）","业务描述":"按时间区间统计支付金额汇总","维度字段来源":"pay_time"}
entity {tuple_delimiter} PayUserCnt_time {tuple_delimiter} 派生指标 {tuple_delimiter} 支付用户数（按时间区间） {tuple_delimiter}{"指标名称":"支付用户数（按时间区间）","业务描述":"按时间区间统计发生支付的去重用户数","维度字段来源":"pay_time"}
entity {tuple_delimiter} PayAmount_terminal {tuple_delimiter} 派生指标 {tuple_delimiter} 支付金额（按终端类型） {tuple_delimiter}{"指标名称":"支付金额（按终端类型）","业务描述":"按终端类型统计支付金额汇总","维度字段来源":"terminal_type"}
entity {tuple_delimiter} PayUserCnt_terminal {tuple_delimiter} 派生指标 {tuple_delimiter} 支付用户数（按终端类型） {tuple_delimiter}{"指标名称":"支付用户数（按终端类型）","业务描述":"按终端类型统计发生支付的去重用户数","维度字段来源":"terminal_type"}
entity {tuple_delimiter} AvgOrderValue_time {tuple_delimiter} 复合指标 {tuple_delimiter} 客单价（按时间区间） {tuple_delimiter}{"指标名称":"客单价（按时间区间）","业务描述":"按时间区间，支付金额除以支付用户数得到的人均支付金额","组合计算":"比值"}
entity {tuple_delimiter} AvgOrderValue_terminal {tuple_delimiter} 复合指标 {tuple_delimiter} 客单价（按终端类型） {tuple_delimiter}{"指标名称":"客单价（按终端类型）","业务描述":"按终端类型，支付金额除以支付用户数得到的人均支付金额","组合计算":"比值"}
relation {tuple_delimiter} AvgOrderValue_time {tuple_delimiter} PayAmount_time {tuple_delimiter} 派生指标来源 {tuple_delimiter} 派生指标来源 {tuple_delimiter}{}
relation {tuple_delimiter} AvgOrderValue_time {tuple_delimiter} PayUserCnt_time {tuple_delimiter} 派生指标来源 {tuple_delimiter} 派生指标来源 {tuple_delimiter}{}
relation {tuple_delimiter} AvgOrderValue_terminal {tuple_delimiter} PayAmount_terminal {tuple_delimiter} 派生指标来源 {tuple_delimiter} 派生指标来源 {tuple_delimiter}{}
relation {tuple_delimiter} AvgOrderValue_terminal {tuple_delimiter} PayUserCnt_terminal {tuple_delimiter} 派生指标来源 {tuple_delimiter} 派生指标来源 {tuple_delimiter}{}
relation {tuple_delimiter} PayAmount_time {tuple_delimiter} PayAmount_Atomic {tuple_delimiter} 派生自原子指标 {tuple_delimiter} 派生自原子指标 {tuple_delimiter}{}
relation {tuple_delimiter} PayUserCnt_time {tuple_delimiter} PayUserCnt_Atomic {tuple_delimiter} 派生自原子指标 {tuple_delimiter} 派生自原子指标 {tuple_delimiter}{}
relation {tuple_delimiter} PayAmount_terminal {tuple_delimiter} PayAmount_Atomic {tuple_delimiter} 派生自原子指标 {tuple_delimiter} 派生自原子指标 {tuple_delimiter}{}
relation {tuple_delimiter} PayUserCnt_terminal {tuple_delimiter} PayUserCnt_Atomic {tuple_delimiter} 派生自原子指标 {tuple_delimiter} 派生自原子指标 {tuple_delimiter}{}

"""
