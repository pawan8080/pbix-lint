"""Human-readable report formatting for pbix_lint."""

from __future__ import annotations

from .model import SemanticModel
from .rules import ERROR, Finding, WARNING


def format_report(model: SemanticModel, findings: list[Finding]) -> str:
    """Render the lint results as a plain-text report."""
    errors = [f for f in findings if f.severity == ERROR]
    warnings = [f for f in findings if f.severity == WARNING]

    lines = [
        f"pbix-lint report for model '{model.name}'",
        f"Tables: {len(model.tables)}  Relationships: {len(model.relationships)}  Measures: {len(model.measures)}",
        f"Findings: {len(findings)} ({len(errors)} errors, {len(warnings)} warnings)",
        "",
    ]

    if not findings:
        lines.append("Clean. No issues found.")
        return "\n".join(lines)

    # Errors first, then warnings, keeping rule order within each group.
    for finding in errors + warnings:
        lines.append(f"[{finding.severity.upper()}] {finding.rule_id}  {finding.location}")
        lines.append(f"  {finding.message}")
        lines.append(f"  Fix: {finding.fix}")
        lines.append("")

    return "\n".join(lines).rstrip()
