"""pbix_lint: a small command-line linter for Power BI semantic models.

The linter reads a JSON description of a semantic model (tables, columns,
relationships, measures) and flags common design smells: bi-directional
relationships, auto date/time bloat, unused or high-cardinality columns,
overgrown DAX, undocumented measures, orphan tables, and type-mismatched
relationships.
"""

__version__ = "0.1.0"

from .rules import RULES, Finding, run_all_rules  # noqa: F401
from .model import load_model, SemanticModel  # noqa: F401
from .report import format_report  # noqa: F401
