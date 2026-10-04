"""Model loading and light validation for pbix_lint.

The expected JSON schema is documented in the README. This module loads it
and normalizes a few defaults so rules can stay simple.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Column:
    name: str
    data_type: str
    row_count: int
    distinct_count: int
    auto_date_time: bool = False


@dataclass
class Table:
    name: str
    row_count: int
    columns: list = field(default_factory=list)  # list[Column]


@dataclass
class Relationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cross_filter_direction: str = "Single"


@dataclass
class Measure:
    name: str
    dax: str
    description: str = ""


@dataclass
class SemanticModel:
    name: str
    tables: list = field(default_factory=list)  # list[Table]
    relationships: list = field(default_factory=list)  # list[Relationship]
    measures: list = field(default_factory=list)  # list[Measure]

    def column_lookup(self) -> dict:
        """Map (table, column) -> Column for quick type checks."""
        lookup = {}
        for table in self.tables:
            for col in table.columns:
                lookup[(table.name, col.name)] = col
        return lookup


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise ValueError(f"Missing required key '{key}' in {where}")
    return mapping[key]


def load_model(path: str) -> SemanticModel:
    """Load a semantic model JSON file, raising ValueError on bad input."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a JSON object")

    model = SemanticModel(name=str(raw.get("name", "UnnamedModel")))

    for t in raw.get("tables", []):
        table = Table(
            name=str(_require(t, "name", "table")),
            row_count=int(_require(t, "row_count", f"table '{t.get('name')}'")),
            columns=[
                Column(
                    name=str(_require(c, "name", "column")),
                    data_type=str(_require(c, "data_type", f"column '{c.get('name')}'")).lower(),
                    row_count=int(_require(c, "row_count", f"column '{c.get('name')}'")),
                    distinct_count=int(_require(c, "distinct_count", f"column '{c.get('name')}'")),
                    auto_date_time=bool(c.get("auto_date_time", False)),
                )
                for c in t.get("columns", [])
            ],
        )
        model.tables.append(table)

    for r in raw.get("relationships", []):
        model.relationships.append(
            Relationship(
                from_table=str(_require(r, "from_table", "relationship")),
                from_column=str(_require(r, "from_column", "relationship")),
                to_table=str(_require(r, "to_table", "relationship")),
                to_column=str(_require(r, "to_column", "relationship")),
                cross_filter_direction=str(r.get("cross_filter_direction", "Single")),
            )
        )

    for m in raw.get("measures", []):
        model.measures.append(
            Measure(
                name=str(_require(m, "name", "measure")),
                dax=str(_require(m, "dax", f"measure '{m.get('name')}'")),
                description=str(m.get("description", "") or ""),
            )
        )

    return model
