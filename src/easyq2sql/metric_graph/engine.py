"""
Structured metric-graph extraction engine.

LightRAG-style structured extraction (entities + relationships) adapted to run
without the ``lightrag`` package. It extracts the three metric entity types —
atomic metrics (原子指标), derived metrics (派生指标), and composite metrics
(复合指标) — from table-schema text, constrained by ``MetricSchema.json``.

Production entry points (used by ``easyq2sql.metric_graph.extract`` and
``easyq2sql.metric_graph.draft``):

* :func:`extract_entities` / :func:`extract_entities_sync` — the extraction loop
* :func:`load_schema_from_file` — load the entity/relation vocabulary
* :func:`validate_metric_fields` — drop metrics whose field references don't
  resolve against the structured table/column set
* :func:`prefix_table_field` / :func:`_coerce_properties` / :func:`_first_key` —
  field-reference helpers
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from typing import Callable, Optional

from .prompt import (
    _ENTITY_CONTINUE_EXTRACTION_USER_PROMPT,
    _ENTITY_EXTRACTION_EXAMPLES,
    _ENTITY_EXTRACTION_SYSTEM_PROMPT,
    _ENTITY_EXTRACTION_USER_PROMPT,
)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_TUPLE_DELIMITER = "<|#|>"
DEFAULT_COMPLETION_DELIMITER = "<|COMPLETE|>"

DEFAULT_MAX_GLEANING = 1


# ============================================================================
# Text cleaning / normalisation
# ============================================================================

def sanitize_text_for_encoding(text: str, replacement_char: str = "") -> str:
    """Remove surrogate/control characters that break UTF-8 encoding."""
    if not text:
        return text
    try:
        text = text.strip()
        if not text:
            return text
        text.encode("utf-8")

        sanitized = ""
        for char in text:
            code_point = ord(char)
            if 0xD800 <= code_point <= 0xDFFF:  # surrogate
                sanitized += replacement_char
            elif code_point == 0xFFFE or code_point == 0xFFFF:  # non-characters
                sanitized += replacement_char
            else:
                sanitized += char

        sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", replacement_char, sanitized)
        sanitized.encode("utf-8")
        sanitized = html.unescape(sanitized)
        sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", "", sanitized)
        return sanitized.strip()
    except UnicodeEncodeError as e:
        raise ValueError(f"Text contains uncleanable UTF-8 encoding issues: {str(e)[:100]}") from e
    except Exception:
        try:
            text.encode("utf-8")
            return text
        except UnicodeEncodeError as e:
            raise ValueError(f"Text sanitization failed: {str(e)}") from e


def normalize_extracted_info(name: str, remove_inner_quotes: bool = False) -> str:
    """Normalise entity/relation names and descriptions.

    Strips HTML tags, converts full-width to half-width, removes intra-Chinese
    whitespace, and strips surrounding quotes.
    """
    name = re.sub(r"</p\s*>|<p\s*>|<p/>", "", name, flags=re.IGNORECASE)
    name = re.sub(r"</br\s*>|<br\s*>|<br/>", "", name, flags=re.IGNORECASE)

    name = name.translate(str.maketrans(
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    ))
    name = name.translate(str.maketrans("０１２３４５６７８９", "0123456789"))

    name = name.replace("－", "-").replace("＋", "+").replace("／", "/").replace("＊", "*")
    name = name.replace("（", "(").replace("）", ")")
    name = name.replace("—", "-").replace("－", "-")
    name = name.replace("　", " ")

    name = re.sub(r"(?<=[一-龥])\s+(?=[一-龥])", "", name)
    name = re.sub(r"(?<=[一-龥])\s+(?=[a-zA-Z0-9\(\)\[\]@#$%!&\*\-=+_])", "", name)
    name = re.sub(r"(?<=[a-zA-Z0-9\(\)\[\]@#$%!&\*\-=+_])\s+(?=[一-龥])", "", name)

    if len(name) >= 2:
        if name.startswith('"') and name.endswith('"'):
            inner = name[1:-1]
            if '"' not in inner:
                name = inner
        if name.startswith("'") and name.endswith("'"):
            inner = name[1:-1]
            if "'" not in inner:
                name = inner
        if name.startswith("“") and name.endswith("”"):
            inner = name[1:-1]
            if "“" not in inner and "”" not in inner:
                name = inner
        if name.startswith("‘") and name.endswith("’"):
            inner = name[1:-1]
            if "‘" not in inner and "’" not in inner:
                name = inner
        if name.startswith("《") and name.endswith("》"):
            inner = name[1:-1]
            if "《" not in inner and "》" not in inner:
                name = inner

    if remove_inner_quotes:
        name = name.replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
        name = re.sub(r"['\"]+(?=[一-龥])", "", name)
        name = re.sub(r"(?<=[一-龥])['\"]+", "", name)
        name = name.replace(" ", " ")
        name = re.sub(r"(?<=[^\d]) ", " ", name)

    name = name.strip()

    if len(name) < 3 and re.match(r"^[0-9]+$", name):
        return ""

    def _should_filter_by_dots(text: str) -> bool:
        return all(c.isdigit() or c == "." for c in text) and "." in text

    if len(name) < 6 and _should_filter_by_dots(name):
        return ""

    return name


def sanitize_and_normalize_extracted_text(input_text: str, remove_inner_quotes: bool = False) -> str:
    safe_input_text = sanitize_text_for_encoding(input_text)
    if safe_input_text:
        return normalize_extracted_info(safe_input_text, remove_inner_quotes=remove_inner_quotes)
    return ""


def split_string_by_multi_markers(content: str, markers: list) -> list:
    if not markers:
        return [content]
    content = content if content is not None else ""
    results = re.split("|".join(re.escape(marker) for marker in markers), content)
    return [r.strip() for r in results if r.strip()]


def fix_tuple_delimiter_corruption(record: str, delimiter_core: str, tuple_delimiter: str) -> str:
    """Repair corrupted variants of the tuple_delimiter in the LLM output."""
    if not record or not delimiter_core or not tuple_delimiter:
        return record
    escaped = re.escape(delimiter_core)

    record = re.sub(rf"<\|{escaped}\|*?{escaped}\|>", tuple_delimiter, record)      # <|##|>, <|#||#|>
    record = re.sub(rf"<\|\\{escaped}\|>", tuple_delimiter, record)                # <|\#|>
    record = re.sub(r"<\|+>", tuple_delimiter, record)                             # <|>, <||>
    record = re.sub(rf"<.?\|{escaped}\|*?>", tuple_delimiter, record)              # <X|#|>, <|#|Y>
    record = re.sub(rf"<\|?{escaped}\|?>", tuple_delimiter, record)                # <#>, <#|>, <|#>
    record = re.sub(rf"<[^|]{escaped}\|>|<\|{escaped}[^|]>", tuple_delimiter, record)  # <X#|>, <|#X>
    record = re.sub(rf"<\|{escaped}\|+(?!>)", tuple_delimiter, record)             # <|#|
    record = re.sub(rf"<\|{escaped}:(?!>)", tuple_delimiter, record)               # <|#:
    record = re.sub(r"<\|\|(?!>)", tuple_delimiter, record)                        # <||
    record = re.sub(rf"(?<!<)\|{escaped}\|>", tuple_delimiter, record)             # |#|>
    record = re.sub(rf"<\|{escaped}\|>\|", tuple_delimiter, record)                # <|#|>|
    record = re.sub(rf"\|\|{escaped}\|\|", tuple_delimiter, record)                # ||#||
    return record


def remove_think_tags(text: str) -> str:
    return re.sub(r"^(<think>.*?</think>|.*</think>)", "", text, flags=re.DOTALL).strip()


def pack_user_ass_to_openai_messages(*args: str) -> list:
    roles = ["user", "assistant"]
    return [{"role": roles[i % 2], "content": content} for i, content in enumerate(args)]


# ============================================================================
# Extraction-result parsing
# ============================================================================

def _parse_json_properties(raw_props: str) -> dict:
    """Parse the properties JSON string; return an empty dict on failure."""
    try:
        raw_props = raw_props.strip()
        if raw_props.startswith("{") and raw_props.endswith("}"):
            return json.loads(raw_props)
    except Exception:
        pass
    return {}


def _parse_entity(record_attributes: list, chunk_key: str, timestamp: int, file_path: str) -> Optional[dict]:
    # Expects 5 fields: entity, name, type, description, properties.
    if len(record_attributes) < 4 or "entity" not in record_attributes[0]:
        return None
    try:
        entity_name = sanitize_and_normalize_extracted_text(record_attributes[1], remove_inner_quotes=True)
        if not entity_name or not entity_name.strip():
            return None
        entity_type = sanitize_and_normalize_extracted_text(record_attributes[2], remove_inner_quotes=True)
        entity_description = sanitize_and_normalize_extracted_text(record_attributes[3])

        extracted_properties = {}
        if len(record_attributes) >= 5:
            extracted_properties = _parse_json_properties(record_attributes[4])

        return dict(
            entity_name=entity_name,
            entity_type=entity_type,
            description=entity_description,
            properties=extracted_properties,
            source_id=chunk_key,
            file_path=file_path,
            timestamp=timestamp,
        )
    except Exception as e:
        print(f"[warn] entity parse failed in chunk {chunk_key}: {e}")
        return None


def _parse_relation(record_attributes: list, chunk_key: str, timestamp: int, file_path: str) -> Optional[dict]:
    # Expects at least 5 fields: relation, src, tgt, keywords, description; a 6th is properties.
    if len(record_attributes) < 5 or "relation" not in record_attributes[0]:
        return None
    try:
        source = sanitize_and_normalize_extracted_text(record_attributes[1], remove_inner_quotes=True)
        target = sanitize_and_normalize_extracted_text(record_attributes[2], remove_inner_quotes=True)
        if not source or not target or source == target:
            return None

        edge_keywords = sanitize_and_normalize_extracted_text(record_attributes[3], remove_inner_quotes=True)
        edge_keywords = edge_keywords.replace("，", ",")
        edge_description = sanitize_and_normalize_extracted_text(record_attributes[4])

        extracted_properties = {}
        if len(record_attributes) >= 6:
            extracted_properties = _parse_json_properties(record_attributes[5])

        weight = 1.0
        if "权重" in extracted_properties:
            try:
                weight = float(extracted_properties["权重"])
            except Exception:
                pass
        elif "weight" in extracted_properties:
            try:
                weight = float(extracted_properties["weight"])
            except Exception:
                pass

        return dict(
            src_id=source,
            tgt_id=target,
            weight=weight,
            description=edge_description,
            keywords=edge_keywords,
            properties=extracted_properties,
            source_id=chunk_key,
            file_path=file_path,
            timestamp=timestamp,
        )
    except Exception as e:
        print(f"[warn] relation parse failed in chunk {chunk_key}: {e}")
        return None


def _parse_extraction_result(
    result: str,
    chunk_key: str,
    timestamp: int,
    file_path: str = "unknown_source",
    tuple_delimiter: str = DEFAULT_TUPLE_DELIMITER,
    completion_delimiter: str = DEFAULT_COMPLETION_DELIMITER,
) -> tuple[dict, dict]:
    """Parse the LLM output into (nodes_dict, edges_dict)."""
    from collections import defaultdict
    maybe_nodes = defaultdict(list)
    maybe_edges = defaultdict(list)

    if completion_delimiter not in result:
        print(f"[warn] {chunk_key}: completion delimiter not found in extraction result")

    records = split_string_by_multi_markers(result, ["\n", completion_delimiter, completion_delimiter.lower()])

    # Repair records where the LLM used tuple_delimiter instead of newlines to separate entries.
    fixed_records = []
    for record in records:
        record = record.strip()
        if record is None:
            continue
        entity_records = split_string_by_multi_markers(record, [f"{tuple_delimiter}entity{tuple_delimiter}"])
        for entity_record in entity_records:
            if not entity_record.startswith("entity") and not entity_record.startswith("relation"):
                entity_record = f"entity<|{entity_record}"
            entity_relation_records = split_string_by_multi_markers(
                entity_record,
                [f"{tuple_delimiter}relationship{tuple_delimiter}", f"{tuple_delimiter}relation{tuple_delimiter}"],
            )
            for er_record in entity_relation_records:
                if not er_record.startswith("entity") and not er_record.startswith("relation"):
                    er_record = f"relation{tuple_delimiter}{er_record}"
                fixed_records.append(er_record)

    for record in fixed_records:
        record = record.strip()
        if record is None:
            continue

        delimiter_core = tuple_delimiter[2:-2]  # extract "#" from "<|#|>"
        record = fix_tuple_delimiter_corruption(record, delimiter_core, tuple_delimiter)
        if delimiter_core != delimiter_core.lower():
            record = fix_tuple_delimiter_corruption(record, delimiter_core.lower(), tuple_delimiter)

        record_attributes = split_string_by_multi_markers(record, [tuple_delimiter])

        entity_data = _parse_entity(record_attributes, chunk_key, timestamp, file_path)
        if entity_data is not None:
            maybe_nodes[entity_data["entity_name"]].append(entity_data)
            continue

        relationship_data = _parse_relation(record_attributes, chunk_key, timestamp, file_path)
        if relationship_data is not None:
            maybe_edges[(relationship_data["src_id"], relationship_data["tgt_id"])].append(relationship_data)

    return dict(maybe_nodes), dict(maybe_edges)


# ============================================================================
# Schema -> prompt vocabulary
# ============================================================================

def _zh_name_of(prop: dict) -> str:
    """Read a property's Chinese name, tolerating ``zh_name`` or ``zh_key_name``."""
    return prop.get("zh_name") or prop.get("zh_key_name") or ""


def build_schema_prompt(
    schema_definition: Optional[list] = None,
    entity_types: Optional[list] = None,
    relationship_types: Optional[list] = None,
) -> tuple[str, str]:
    """Build the entity/relation vocabulary strings injected into the prompt.

    Priority: ``schema_definition`` (with descriptions + properties) >
    ``entity_types``/``relationship_types`` (bare lists) > open-domain.
    """
    entity_types_prompt_str = ""
    relationship_types_prompt_str = ""

    if schema_definition:
        dynamic_entity_types = []
        dynamic_rel_types = []
        for item in schema_definition:
            if item.get("label"):
                label = item["label"]
                desc = item.get("description", "")
                props_zh_names = [_zh_name_of(p) for p in item.get("properties", []) if _zh_name_of(p)]
                props_str = f"提取属性：{', '.join(props_zh_names)}" if props_zh_names else "无特定属性要求"
                dynamic_entity_types.append(f"- {label}: {props_str} {desc}".strip())

            for rel in item.get("relations", []):
                rel_name = _zh_name_of(rel)
                if rel_name:
                    rel_desc = rel.get("description", "")
                    rprops_zh_names = [_zh_name_of(p) for p in rel.get("properties", []) if _zh_name_of(p)]
                    rprops_str = f"提取属性：{', '.join(rprops_zh_names)}" if rprops_zh_names else "无特定属性要求"
                    dynamic_rel_types.append(f"- {rel_name}: {rprops_str} {rel_desc}".strip())

        if dynamic_entity_types:
            entity_types_prompt_str = "\n".join(list(dict.fromkeys(dynamic_entity_types)))
        if dynamic_rel_types:
            relationship_types_prompt_str = "\n".join(list(dict.fromkeys(dynamic_rel_types)))

    if not entity_types_prompt_str:
        if entity_types:
            entity_types_prompt_str = ", ".join(entity_types)
        else:
            entity_types_prompt_str = "开放域提取，请根据上下文自行总结合适的类别名称，名称必须简短且具概括性。"

    if not relationship_types_prompt_str:
        if relationship_types:
            relationship_types_prompt_str = ", ".join(relationship_types)
        else:
            relationship_types_prompt_str = "开放域模式：请用简洁的中文语义短语描述关系，例如：申请贷款、拥有、担保、创办、订立合同等，禁止输出无意义词汇。"

    return entity_types_prompt_str, relationship_types_prompt_str


# ============================================================================
# Schema loading (JSON file)
# ============================================================================

def load_schema_from_file(schema_path: str) -> dict:
    """Load a schema JSON file into ``{entity_types, relationship_types, schema_definition}``."""
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_data = json.load(f)

    entity_types = []
    relationship_types = []
    schema_definition = []

    # conceptTypes are also part of the entity-type vocabulary.
    for c_type in schema_data.get("conceptTypes", []):
        if "label" in c_type:
            entity_types.append(c_type["label"])

    for e_type in schema_data.get("entityTypes", []):
        if "label" in e_type:
            entity_types.append(e_type["label"])
        for rel in e_type.get("relations", []):
            rel_name = _zh_name_of(rel)
            if rel_name:
                relationship_types.append(rel_name)

    entity_types = list(dict.fromkeys(entity_types))
    relationship_types = list(dict.fromkeys(relationship_types))

    # Build a schema_definition matching the API request-body (EntityTypeDef) shape.
    for e_type in schema_data.get("entityTypes", []):
        schema_definition.append({
            "label": e_type.get("label"),
            "description": e_type.get("description", ""),
            "properties": [
                {"zh_name": p.get("zh_key_name") or p.get("zh_name")}
                for p in e_type.get("properties", [])
            ],
            "relations": [
                {
                    "zh_name": r.get("zh_key_name") or r.get("zh_name"),
                    "description": r.get("description", ""),
                    "properties": [
                        {"zh_name": p.get("zh_key_name") or p.get("zh_name")}
                        for p in r.get("properties", [])
                    ],
                }
                for r in e_type.get("relations", [])
            ],
        })

    return {
        "entity_types": entity_types,
        "relationship_types": relationship_types,
        "schema_definition": schema_definition,
    }


# ============================================================================
# Extraction entry point
# ============================================================================

async def extract_entities(
    text: str,
    *,
    llm_func: Callable,
    schema_definition: Optional[list] = None,
    entity_types: Optional[list] = None,
    relationship_types: Optional[list] = None,
    language: str = "Simplified Chinese",
    max_gleaning: int = DEFAULT_MAX_GLEANING,
    chunk_key: str = "default-chunk",
) -> dict:
    """Run structured extraction on a single text segment.

    Args:
        text: The raw text to extract from (treated as a single chunk).
        llm_func: Async LLM callable with signature
            ``async def f(user_prompt, *, system_prompt=None, history_messages=None) -> str``.
        schema_definition / entity_types / relationship_types: Schema constraints
            (any one may be supplied).
        language: Output language.
        max_gleaning: Gleaning (gap-filling) rounds; 0 disables it.
        chunk_key: Source identifier recorded on each extracted entity/relation
            as ``source_id`` (the table name in the metric-graph flow).

    Returns:
        ``{"entities": [...], "relationships": [...]}``.
    """
    entity_types_prompt_str, relationship_types_prompt_str = build_schema_prompt(
        schema_definition, entity_types, relationship_types
    )

    # The example template contains literal JSON braces ({"table_name": ...}), so
    # .format() would treat them as fields (KeyError). Use .replace() to only swap
    # the delimiter placeholders.
    examples = _ENTITY_EXTRACTION_EXAMPLES.replace(
        "{tuple_delimiter}", DEFAULT_TUPLE_DELIMITER
    ).replace("{completion_delimiter}", DEFAULT_COMPLETION_DELIMITER)

    context_base = dict(
        tuple_delimiter=DEFAULT_TUPLE_DELIMITER,
        completion_delimiter=DEFAULT_COMPLETION_DELIMITER,
        entity_types=entity_types_prompt_str,
        relationship_types=relationship_types_prompt_str,
        examples=examples,
        language=language,
    )

    system_prompt = _ENTITY_EXTRACTION_SYSTEM_PROMPT.format(**{**context_base, "input_text": text})
    user_prompt = _ENTITY_EXTRACTION_USER_PROMPT.format(**context_base)
    continue_user_prompt = _ENTITY_CONTINUE_EXTRACTION_USER_PROMPT.format(**context_base)

    file_path = "unknown_source"

    # First extraction pass.
    result = remove_think_tags(await llm_func(user_prompt, system_prompt=system_prompt))
    history = pack_user_ass_to_openai_messages(user_prompt, result)
    maybe_nodes, maybe_edges = _parse_extraction_result(
        result, chunk_key, 0, file_path,
        DEFAULT_TUPLE_DELIMITER, DEFAULT_COMPLETION_DELIMITER,
    )

    # Gleaning passes: keep the longer description per duplicate entity/relation.
    for _ in range(max(0, max_gleaning)):
        glean_result = remove_think_tags(
            await llm_func(continue_user_prompt, system_prompt=system_prompt, history_messages=history)
        )
        history = pack_user_ass_to_openai_messages(user_prompt, result, continue_user_prompt, glean_result)

        glean_nodes, glean_edges = _parse_extraction_result(
            glean_result, chunk_key, 0, file_path,
            DEFAULT_TUPLE_DELIMITER, DEFAULT_COMPLETION_DELIMITER,
        )

        for entity_name, glean_entities in glean_nodes.items():
            if entity_name in maybe_nodes:
                old_len = len(maybe_nodes[entity_name][0].get("description", "") or "")
                new_len = len(glean_entities[0].get("description", "") or "")
                if new_len > old_len:
                    maybe_nodes[entity_name] = list(glean_entities)
            else:
                maybe_nodes[entity_name] = list(glean_entities)

        for edge_key, glean_rel in glean_edges.items():
            if edge_key in maybe_edges:
                old_len = len(maybe_edges[edge_key][0].get("description", "") or "")
                new_len = len(glean_rel[0].get("description", "") or "")
                if new_len > old_len:
                    maybe_edges[edge_key] = list(glean_rel)
            else:
                maybe_edges[edge_key] = list(glean_rel)

    # Flatten: keep the first record per entity/relation.
    entities = [items[0] for items in maybe_nodes.values()]
    relationships = [items[0] for items in maybe_edges.values()]

    return {"entities": entities, "relationships": relationships}


def extract_entities_sync(text: str, **kwargs) -> dict:
    """Synchronous wrapper for :func:`extract_entities`."""
    return asyncio.run(extract_entities(text, **kwargs))


# ============================================================================
# Metric field-reference validation
# ============================================================================

def _coerce_properties(props) -> dict:
    """Normalise extracted properties into a dict (may be a dict or JSON string)."""
    if isinstance(props, dict):
        return props
    if isinstance(props, str) and props.strip():
        try:
            parsed = json.loads(props)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _as_str_list(value) -> list:
    """Normalise a field-reference value into a list of strings.

    Accepts a Python list, a JSON-array string (``'["a","b"]'``), a
    comma-separated string, or a single string.
    """
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                items = parsed if isinstance(parsed, list) else [s]
            except Exception:
                items = [s]
        else:
            items = [x for x in s.replace("，", ",").split(",")]
    else:
        items = [value]

    out = []
    for it in items:
        if it is None:
            continue
        it = str(it).strip().strip('"').strip("'").strip()
        if it:
            out.append(it)
    return out


def _split_table_field(raw: str) -> tuple:
    """Split ``'table.column'`` into ``(table, column)``; table is empty without a dot."""
    name = (raw or "").strip()
    if "." in name:
        table, _, field = name.partition(".")
        return table.strip(), field.strip()
    return "", name.strip()


def prefix_table_field(table: str, value) -> str:
    """Prefix bare field names with their table to produce ``table.column``.

    Field values that already carry a table prefix (contain a dot) are kept
    as-is. Multiple fields are comma-joined. The table name is supplied by the
    caller (``chunk_key`` -> ``source_id``); the LLM only extracts the field name.
    """
    table = (table or "").strip()
    out = []
    for raw in _as_str_list(value):
        t, f = _split_table_field(raw)
        if t or not f:
            out.append(raw)
        elif table:
            out.append(f"{table}.{f}")
        else:
            out.append(f)
    if not out:
        return ""
    return out[0] if len(out) == 1 else ",".join(out)


def _first_key(props: dict, *keys):
    """Return the first non-empty value across candidate keys (CN/EN tolerant)."""
    for k in keys:
        if k in props and props[k] is not None:
            return props[k]
    return None


def validate_metric_fields(metric_result: dict, table_field_result: dict) -> dict:
    """Validate that each metric entity's field reference exists in its table.

    After batch extraction, field properties (来源字段 / 维度字段来源) carry only
    the field name; the table name is injected by the caller via ``chunk_key`` ->
    ``source_id``. A metric entity with an unknown source table or an unmatched
    field is **dropped** (with a warning), and any relationship referencing a
    dropped entity is removed too, so all returned relationship endpoints remain
    valid entities.

    Args:
        metric_result: ``extract_entities()`` return value (metric entities + links).
        table_field_result: ``{"tables": {table: {field: col_meta}}}`` where
            ``col_meta`` is ``{"value_range": ..., "fk": ...}`` (either may be None).

    Returns:
        Filtered ``{"entities": [...], "relationships": [...]}``.
    """
    tables = table_field_result.get("tables", {})

    kept_entities = []
    dropped_names = set()

    for m in metric_result.get("entities", []):
        props = _coerce_properties(m.get("properties"))
        metric_name = m.get("entity_name", "")
        table = (m.get("source_id") or "").strip()

        if table not in tables:
            print(f"[validate] unknown source table, dropping metric: {metric_name} -> {table or '(empty)'}")
            dropped_names.add(metric_name)
            continue

        field_set = tables[table]
        # Keys follow MetricSchema.json:
        #   AtomicMetric:   source_field
        #   DerivedMetric:  dimension_field
        source_field = _first_key(props, "来源字段", "source_field", "source_fields")
        dim_field = _first_key(props, "维度字段来源", "dimension_field", "metric_fields")

        bad = False
        # First matched field (for back-filling value_range / FK).
        matched_field = None
        for raw in _as_str_list(source_field):
            if raw not in field_set:
                print(f"[validate] source field not matched, dropping metric: {metric_name} -> {raw}")
                bad = True
            elif matched_field is None:
                matched_field = raw
        for raw in _as_str_list(dim_field):
            if raw not in field_set:
                print(f"[validate] dimension field not matched, dropping metric: {metric_name} -> {raw}")
                bad = True
            elif matched_field is None:
                matched_field = raw
        if bad:
            dropped_names.add(metric_name)
            continue

        # Pull value_range / FK from column metadata into the entity properties
        # (only when the column actually carries them).
        if matched_field is not None:
            col_meta = field_set[matched_field] or {}
            value_range = col_meta.get("value_range")
            fk = col_meta.get("fk")
            if value_range:
                props["取值范围"] = value_range
            if fk:
                props["外键关系"] = fk
            m["properties"] = props

        kept_entities.append(m)

    kept_relationships = [
        r for r in metric_result.get("relationships", [])
        if r.get("src_id") not in dropped_names and r.get("tgt_id") not in dropped_names
    ]

    return {"entities": kept_entities, "relationships": kept_relationships}
