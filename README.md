# pbix-lint

A small command-line linter for Power BI semantic models. Semantic models
silently accumulate design debt — bi-directional relationships, auto
date/time bloat, dead columns, overgrown DAX — that later shows up as slow
refreshes, confusing reports, and hard-to-debug measures. `pbix-lint`
flags these problems early, with a plain-language fix for each one.

Pure Python, standard library only. No dependencies.

## The problem

Most model problems are not bugs, they are defaults nobody questioned:
auto date/time left on, a relationship set to Both because a measure
"needed it once", columns imported "just in case" that no visual ever
touches. Each one is cheap alone. Together they make the model slow,
fragile, and scary to change. A linter makes the debt visible before
it compounds.

## Usage

```bash
python -m pbix_lint <model.json>
```

Exit code `0` means clean or warnings only, `1` means at least one error,
`2` means the input file could not be read.

```bash
python -m pbix_lint examples/healthy_model.json
# pbix-lint report for model 'HealthySalesModel'
# Tables: 3  Relationships: 2  Measures: 5
# Findings: 0 (0 errors, 0 warnings)
#
# Clean. No issues found.

python -m pbix_lint examples/messy_model.json
# pbix-lint report for model 'LegacySalesModel'
# Tables: 4  Relationships: 2  Measures: 3
# Findings: 18 (1 errors, 17 warnings)
#
# [ERROR] R08  Sales[OrderDate] -> Calendar[Date]
#   Data type mismatch: datetime joined to date.
#   Fix: Align the data types in Power Query before the model sees them.
#
# [WARNING] R01  Sales[CustomerID] -> Customer[CustomerID]
#   Bi-directional cross-filter direction on relationship.
#   Fix: Switch to single direction unless a specific calculation requires both; use CROSSFILTER() for the exception.
# ...
```

Run the tests with:

```bash
python -m unittest discover -s tests -v
```

## Model schema

The input is a JSON object describing the model:

```json
{
  "name": "SalesModel",
  "tables": [
    {
      "name": "Sales",
      "row_count": 50000,
      "columns": [
        {"name": "OrderDate", "data_type": "date", "row_count": 50000,
         "distinct_count": 900, "auto_date_time": false}
      ]
    }
  ],
  "relationships": [
    {"from_table": "Sales", "from_column": "ProductID",
     "to_table": "Product", "to_column": "ProductID",
     "cross_filter_direction": "Single"}
  ],
  "measures": [
    {"name": "Total Sales", "dax": "SUM(Sales[Amount])",
     "description": "Total sales amount."}
  ]
}
```

- `data_type` is normalized to lowercase (`int`, `text`, `date`,
  `datetime`, `decimal`, ...).
- `auto_date_time` is optional and defaults to `false`.
- `cross_filter_direction` is optional and defaults to `"Single"`.
- `description` is optional and defaults to `""`.

## Rules

| ID | Severity | What it flags |
|----|----------|---------------|
| R01 | warning | Bi-directional cross-filter direction on a relationship |
| R02 | warning | Auto date/time enabled on a date/datetime column |
| R03 | warning | Near-unique column (95%+ distinct values) that is not a relationship key — memory bloat |
| R04 | warning | Column not referenced by any relationship or measure DAX — dead weight |
| R05 | warning | Measure DAX longer than 200 characters — split it up |
| R06 | warning | Measure with no description |
| R07 | warning | Table with no relationships (when the model has more than one table) |
| R08 | error | Relationship joining mismatched data types, or referencing a missing column |

Every finding prints the rule id, severity, location, a one-line message,
and a one-line fix.

## How to add a new rule

1. Write a function in `pbix_lint/rules.py` with the signature
   `rule_name(model: SemanticModel) -> list[Finding]`.
2. Build `Finding` objects with a new `Rxx` id, a severity
   (`WARNING` or `ERROR`), a location string, a message, and a fix.
3. Append the function to the `RULES` list.
4. Add a test class in `tests/test_rules.py` covering the flagged case
   and the clean case.

## Project layout

```
pbix-lint/
  pbix_lint/
    __init__.py    package exports
    __main__.py    CLI: python -m pbix_lint <model.json>
    model.py       JSON loading and light validation
    rules.py       the 8 lint rules + Finding + run_all_rules
    report.py      plain-text report formatting
  tests/
    test_rules.py  27 unit tests, one per rule plus examples and CLI
  examples/
    healthy_model.json   passes clean
    messy_model.json     triggers all 8 rules
  README.md
```

## Limitations

This lints a *description* of a model, not a real `.pbix` file — there
is deliberately no parser for the binary format here. The "unused column"
check is heuristic: it looks for `[Column]` / `Table[Column]` references
in measure DAX, so exotic DAX patterns can produce false positives.
Thresholds (200-char DAX, 95% cardinality) are guidelines, not laws.
