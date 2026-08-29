"""
Shared text formatters for ``TableSchema``.

Two distinct texts are derived from the same ``TableSchema``:

* :func:`format_table_search_text` — the *retrieval* text. A compact pipe-joined
  stream (``table | comment | field | comment | example | range | ...``) used as
  the embedding source, the ``search_text`` column value, and the Cross-Encoder
  re-rank document. Deliberately stripped of structural markers (no ``# Table:``,
  no types, no PK/FK flags, no foreign-key section) so vector/keyword recall is
  driven by names, comments, examples and ranges alone.

* :func:`format_table_llm_text` — the *display* text fed to the LLM. The rich
  per-column breakdown (``# Table:`` / ``# Foreign keys`` /
  ``[ (col:type, Primary Key, description, Maps to …, Examples, Value Range) ]``)
  that carries type and key flags so the model can write correct SQL.

Splitting the two lets the retrieval index stay lean while the LLM still receives
full structural detail — the LLM text is rebuilt on demand from ``TableSchema``
rather than stored alongside ``search_text``.
"""

from __future__ import annotations

from .models import TableSchema


def format_table_search_text(table: TableSchema) -> str:
    """Build the compact pipe-joined retrieval text for a ``TableSchema``.

    Format::

        table_name | table_description | col1 | col1_comment | [ex1, ex2] | range1 | col2 | ...

    Only non-empty segments are emitted (no `` | | |`` gaps). Type, PK/FK flags
    and the foreign-key section are intentionally omitted — this text exists for
    embedding / full-text / Cross-Encoder recall, not for SQL authoring.
    """
    parts: list[str] = [table.table_name or ""]
    if table.description:
        parts.append(table.description)

    for col in table.columns:
        if col.name:
            parts.append(col.name)
        if col.description:
            parts.append(col.description)
        if col.examples:
            truncated = [
                (e[:100] + "...") if len(e) > 100 else e for e in col.examples
            ]
            parts.append(f"[{', '.join(truncated)}]")
        if col.value_range:
            parts.append(col.value_range)

    return " | ".join(p for p in parts if p)


def format_table_llm_text(table: TableSchema) -> str:
    """Build the rich per-column display text fed to the LLM.

    Format::

        # Table: {name}
        Description: {desc}
        # Foreign keys: {name}.{col} = {ref_table}.{ref_col}, ...
        [
        (col:TYPE, Primary Key, Foreign Key, description
        Maps to ref_table(ref_col), Examples: [v1, v2, v3], Value Range: ...),
        ...
        ]
    """
    lines = [f"# Table: {table.table_name}"]
    if table.description:
        lines.append(f"Description: {table.description}")

    fk_columns = [
        c for c in table.columns
        if c.is_foreign_key and c.fk_reference_table
    ]
    if fk_columns:
        fk_parts = [
            f"{table.table_name}.{c.name} = "
            f"{c.fk_reference_table}.{c.fk_reference_column or 'id'}"
            for c in fk_columns
        ]
        lines.append(f"# Foreign keys: {', '.join(fk_parts)}")

    lines.append("[")

    for col in table.columns:
        flags: list[str] = []
        if col.is_primary_key:
            flags.append("Primary Key")
        if col.is_foreign_key:
            flags.append("Foreign Key")

        flag_str = ", ".join(flags)
        desc = col.description or ""
        header = f"({col.name}:{col.data_type}"
        if flag_str:
            header += f", {flag_str}"
        if desc:
            header += f", {desc}"
        lines.append(header)

        extras: list[str] = []
        if col.is_foreign_key and col.fk_reference_table:
            ref_col = col.fk_reference_column or "id"
            extras.append(f"Maps to {col.fk_reference_table}({ref_col})")
        if col.examples:
            truncated = [
                (e[:100] + "...") if len(e) > 100 else e for e in col.examples
            ]
            extras.append(f"Examples: [{', '.join(truncated)}]")
        if col.value_range:
            extras.append(f"Value Range: {col.value_range}")

        if extras:
            lines.append(", ".join(extras))

        lines[-1] += "),"

    lines.append("]")
    return "\n".join(lines)
