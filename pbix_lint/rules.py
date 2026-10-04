"""Lint rules for pbix_lint.

Each rule is a function ``rule_x(model) -> list[Finding]``. Rules are
registered in the RULES list in the order they run. Adding a new rule is
just: write the function, append it to RULES.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import SemanticModel

WARNING = "warning"
ERROR = "error"

# A measure longer than this many characters is probably doing too much.
LONG_DAX_THRESHOLD = 200

# A column is "near unique" when its distinct count reaches this share of
# the row count (tolerates small data-quality wobble).
HIGH_CARDINALITY_RATIO = 0.95


@dataclass
class Finding:
    rule_id: str
    severity: str  # "warning" or "error"
    location: str  # e.g. "Sales[OrderDate]" or "relationship Sales -> Customer"
    message: str
    fix: str


def rule_bidirectional_relationship(model: SemanticModel) -> list[Finding]:
    """Bi-directional cross-filtering invites ambiguous filter paths and
    confusing totals. It should be the exception, not the default."""
    findings = []
    for rel in model.relationships:
        if rel.cross_filter_direction.strip().lower() in ("both", "bidirectional"):
            findings.append(
                Finding(
                    rule_id="R01",
                    severity=WARNING,
                    location=f"{rel.from_table}[{rel.from_column}] -> {rel.to_table}[{rel.to_column}]",
                    message="Bi-directional cross-filter direction on relationship.",
                    fix="Switch to single direction unless a specific calculation requires both; use CROSSFILTER() for the exception.",
                )
            )
    return findings


def rule_auto_date_time(model: SemanticModel) -> list[Finding]:
    """Auto date/time creates a hidden date table per date column, bloating
    the model for a feature most reports never use."""
    findings = []
    for table in model.tables:
        for col in table.columns:
            if col.auto_date_time and col.data_type in ("date", "datetime", "datetime2"):
                findings.append(
                    Finding(
                        rule_id="R02",
                        severity=WARNING,
                        location=f"{table.name}[{col.name}]",
                        message="Auto date/time is enabled on a date column.",
                        fix="Turn off auto date/time and build one explicit calendar table instead.",
                    )
                )
    return findings


def _relationship_columns(model: SemanticModel) -> set:
    used = set()
    for rel in model.relationships:
        used.add((rel.from_table, rel.from_column))
        used.add((rel.to_table, rel.to_column))
    return used


def rule_high_cardinality_column(model: SemanticModel) -> list[Finding]:
    """A near-unique column costs memory like a key but behaves like none.
    Relationship key columns are exempt — they earn their keep."""
    findings = []
    rel_cols = _relationship_columns(model)
    for table in model.tables:
        for col in table.columns:
            if (table.name, col.name) in rel_cols:
                continue
            if table.row_count > 0 and col.distinct_count >= table.row_count * HIGH_CARDINALITY_RATIO:
                findings.append(
                    Finding(
                        rule_id="R03",
                        severity=WARNING,
                        location=f"{table.name}[{col.name}]",
                        message=(
                            f"Near-unique column: {col.distinct_count:,} distinct values "
                            f"over {table.row_count:,} rows."
                        ),
                        fix="If it is not a key, hide it or drop it; unique text columns are the priciest thing in a model.",
                    )
                )
    return findings


_COLUMN_REF = re.compile(r"(?:(\w+)\s*)?\[([^\[\]]+)\]")


def _dax_referenced_columns(model: SemanticModel) -> set:
    """Column names referenced as [Column] or Table[Column] in any measure."""
    refs = set()
    for measure in model.measures:
        for match in _COLUMN_REF.finditer(measure.dax):
            refs.add(match.group(2).strip())
    return refs


def rule_unused_column(model: SemanticModel) -> list[Finding]:
    """A column nobody filters, joins, or measures on is dead weight in
    every refresh and every query."""
    findings = []
    rel_cols = _relationship_columns(model)
    dax_refs = _dax_referenced_columns(model)
    for table in model.tables:
        for col in table.columns:
            if (table.name, col.name) in rel_cols:
                continue
            if col.name in dax_refs:
                continue
            findings.append(
                Finding(
                    rule_id="R04",
                    severity=WARNING,
                    location=f"{table.name}[{col.name}]",
                    message="Column is not used by any relationship or measure.",
                    fix="Remove it from the model, or hide it if it is only there for documentation.",
                )
            )
    return findings


def rule_long_dax_measure(model: SemanticModel) -> list[Finding]:
    """Long measures are hard to debug and usually hide intermediate logic
    that deserves its own name."""
    findings = []
    for measure in model.measures:
        if len(measure.dax) > LONG_DAX_THRESHOLD:
            findings.append(
                Finding(
                    rule_id="R05",
                    severity=WARNING,
                    location=f"measure '{measure.name}'",
                    message=f"DAX is {len(measure.dax)} chars (over the {LONG_DAX_THRESHOLD} guideline).",
                    fix="Split it: pull repeated logic into intermediate measures or VAR blocks with clear names.",
                )
            )
    return findings


def rule_missing_measure_description(model: SemanticModel) -> list[Finding]:
    """An undocumented measure is a future bug report. Descriptions also
    surface as tooltips in Power BI."""
    findings = []
    for measure in model.measures:
        if not measure.description.strip():
            findings.append(
                Finding(
                    rule_id="R06",
                    severity=WARNING,
                    location=f"measure '{measure.name}'",
                    message="Measure has no description.",
                    fix="Add one sentence: what it computes and any filter context it assumes.",
                )
            )
    return findings


def rule_orphan_table(model: SemanticModel) -> list[Finding]:
    """A table joined to nothing cannot be sliced by anything — usually a
    forgotten import or a broken relationship."""
    findings = []
    if len(model.tables) < 2:
        return findings
    joined = set()
    for rel in model.relationships:
        joined.add(rel.from_table)
        joined.add(rel.to_table)
    for table in model.tables:
        if table.name not in joined:
            findings.append(
                Finding(
                    rule_id="R07",
                    severity=WARNING,
                    location=f"table '{table.name}'",
                    message="Table has no relationships to any other table.",
                    fix="Add the missing relationship, or remove the table if it is not needed.",
                )
            )
    return findings


def rule_relationship_type_mismatch(model: SemanticModel) -> list[Finding]:
    """Joining columns of different data types either fails or silently
    coerces values — both are bad."""
    findings = []
    lookup = model.column_lookup()
    for rel in model.relationships:
        from_col = lookup.get((rel.from_table, rel.from_column))
        to_col = lookup.get((rel.to_table, rel.to_column))
        if from_col is None or to_col is None:
            findings.append(
                Finding(
                    rule_id="R08",
                    severity=ERROR,
                    location=f"{rel.from_table}[{rel.from_column}] -> {rel.to_table}[{rel.to_column}]",
                    message="Relationship references a column that does not exist in the model.",
                    fix="Fix the table or column name in the relationship definition.",
                )
            )
        elif from_col.data_type != to_col.data_type:
            findings.append(
                Finding(
                    rule_id="R08",
                    severity=ERROR,
                    location=f"{rel.from_table}[{rel.from_column}] -> {rel.to_table}[{rel.to_column}]",
                    message=(
                        f"Data type mismatch: {from_col.data_type} joined to {to_col.data_type}."
                    ),
                    fix="Align the data types in Power Query before the model sees them.",
                )
            )
    return findings


RULES = [
    rule_bidirectional_relationship,
    rule_auto_date_time,
    rule_high_cardinality_column,
    rule_unused_column,
    rule_long_dax_measure,
    rule_missing_measure_description,
    rule_orphan_table,
    rule_relationship_type_mismatch,
]


def run_all_rules(model: SemanticModel) -> list[Finding]:
    """Run every registered rule and return all findings in rule order."""
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(model))
    return findings
