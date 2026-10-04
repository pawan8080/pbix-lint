"""CLI entry point: python -m pbix_lint <model.json>"""

from __future__ import annotations

import argparse
import sys

from .model import load_model
from .report import format_report
from .rules import ERROR, run_all_rules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pbix-lint",
        description="Lint a Power BI semantic model JSON file for common design smells.",
    )
    parser.add_argument("model", help="Path to the model JSON file.")
    args = parser.parse_args(argv)

    try:
        model = load_model(args.model)
    except (OSError, ValueError) as exc:
        print(f"pbix-lint: {exc}", file=sys.stderr)
        return 2

    findings = run_all_rules(model)
    print(format_report(model, findings))

    # Exit 1 when any error-severity finding exists; warnings do not fail.
    return 1 if any(f.severity == ERROR for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
