"""Tests for pbix_lint. Run with: python -m unittest discover -s tests -v"""

import json
import os
import tempfile
import unittest

from pbix_lint.model import load_model, SemanticModel, Table, Column, Relationship, Measure
from pbix_lint.rules import (
    RULES,
    run_all_rules,
    rule_bidirectional_relationship,
    rule_auto_date_time,
    rule_high_cardinality_column,
    rule_unused_column,
    rule_long_dax_measure,
    rule_missing_measure_description,
    rule_orphan_table,
    rule_relationship_type_mismatch,
)
from pbix_lint.report import format_report
from pbix_lint.__main__ import main

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "examples")


def make_model(**kwargs) -> SemanticModel:
    """Minimal valid model; override pieces per test."""
    model = SemanticModel(name="TestModel")
    model.tables = kwargs.get(
        "tables",
        [Table(name="Sales", row_count=100,
               columns=[Column(name="Amount", data_type="decimal",
                               row_count=100, distinct_count=50)])],
    )
    model.relationships = kwargs.get("relationships", [])
    model.measures = kwargs.get(
        "measures",
        [Measure(name="Total", dax="SUM(Sales[Amount])", description="Total.")],
    )
    return model


class TestRuleRegistration(unittest.TestCase):
    def test_eight_rules_registered(self):
        self.assertEqual(len(RULES), 8)


class TestBidirectional(unittest.TestCase):
    def test_flags_both(self):
        model = make_model(relationships=[
            Relationship("Sales", "CustomerID", "Customer", "CustomerID", "Both")])
        findings = rule_bidirectional_relationship(model)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "R01")
        self.assertEqual(findings[0].severity, "warning")

    def test_single_direction_is_clean(self):
        model = make_model(relationships=[
            Relationship("Sales", "CustomerID", "Customer", "CustomerID", "Single")])
        self.assertEqual(rule_bidirectional_relationship(model), [])


class TestAutoDateTime(unittest.TestCase):
    def test_flags_auto_date_time_on_date_column(self):
        model = make_model(tables=[
            Table(name="Sales", row_count=100, columns=[
                Column(name="OrderDate", data_type="datetime", row_count=100,
                       distinct_count=90, auto_date_time=True),
                Column(name="Amount", data_type="decimal", row_count=100, distinct_count=50),
            ])])
        findings = rule_auto_date_time(model)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "R02")

    def test_ignores_non_date_columns(self):
        model = make_model(tables=[
            Table(name="Sales", row_count=100, columns=[
                Column(name="Note", data_type="text", row_count=100,
                       distinct_count=90, auto_date_time=True),
            ])])
        self.assertEqual(rule_auto_date_time(model), [])


class TestHighCardinality(unittest.TestCase):
    def test_flags_near_unique_column(self):
        model = make_model(tables=[
            Table(name="Sales", row_count=1000, columns=[
                Column(name="TransactionGUID", data_type="text", row_count=1000,
                       distinct_count=1000),
            ])])
        findings = rule_high_cardinality_column(model)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "R03")

    def test_exempts_relationship_key_columns(self):
        model = make_model(
            tables=[Table(name="Sales", row_count=1000, columns=[
                Column(name="OrderID", data_type="int", row_count=1000, distinct_count=1000),
            ])],
            relationships=[Relationship("Sales", "OrderID", "Orders", "OrderID")],
        )
        self.assertEqual(rule_high_cardinality_column(model), [])

    def test_low_cardinality_is_clean(self):
        model = make_model()  # Amount: 50 distinct over 100 rows
        self.assertEqual(rule_high_cardinality_column(model), [])


class TestUnusedColumn(unittest.TestCase):
    def test_flags_dead_column(self):
        model = make_model(tables=[
            Table(name="Sales", row_count=100, columns=[
                Column(name="Amount", data_type="decimal", row_count=100, distinct_count=50),
                Column(name="OldNote", data_type="text", row_count=100, distinct_count=90),
            ])])
        findings = rule_unused_column(model)
        self.assertEqual([f.location for f in findings], ["Sales[OldNote]"])
        self.assertEqual(findings[0].rule_id, "R04")

    def test_column_used_in_relationship_is_clean(self):
        model = make_model(
            tables=[Table(name="Sales", row_count=100, columns=[
                Column(name="Amount", data_type="decimal", row_count=100, distinct_count=50),
                Column(name="CustomerID", data_type="int", row_count=100, distinct_count=40),
            ])],
            relationships=[Relationship("Sales", "CustomerID", "Customer", "CustomerID")],
        )
        self.assertEqual(rule_unused_column(model), [])


class TestLongDax(unittest.TestCase):
    def test_flags_long_measure(self):
        model = make_model(measures=[
            Measure(name="Monster", dax="SUM(Sales[Amount]) " * 30, description="x")])
        findings = rule_long_dax_measure(model)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "R05")

    def test_short_measure_is_clean(self):
        self.assertEqual(rule_long_dax_measure(make_model()), [])


class TestMissingDescription(unittest.TestCase):
    def test_flags_blank_description(self):
        model = make_model(measures=[
            Measure(name="M", dax="SUM(Sales[Amount])", description="   ")])
        findings = rule_missing_measure_description(model)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "R06")

    def test_documented_measure_is_clean(self):
        self.assertEqual(rule_missing_measure_description(make_model()), [])


class TestOrphanTable(unittest.TestCase):
    def test_flags_unjoined_table(self):
        model = make_model(
            tables=[
                Table(name="Sales", row_count=100, columns=[]),
                Table(name="Forgotten", row_count=10, columns=[]),
            ],
            relationships=[Relationship("Sales", "ID", "Customer", "ID")],
        )
        findings = rule_orphan_table(model)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "R07")
        self.assertIn("Forgotten", findings[0].location)

    def test_single_table_model_is_clean(self):
        self.assertEqual(rule_orphan_table(make_model()), [])


class TestTypeMismatch(unittest.TestCase):
    def test_flags_mismatched_types(self):
        model = make_model(
            tables=[
                Table(name="Sales", row_count=100, columns=[
                    Column(name="CustomerID", data_type="int", row_count=100, distinct_count=40)]),
                Table(name="Customer", row_count=40, columns=[
                    Column(name="CustomerID", data_type="text", row_count=40, distinct_count=40)]),
            ],
            relationships=[Relationship("Sales", "CustomerID", "Customer", "CustomerID")],
        )
        findings = rule_relationship_type_mismatch(model)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "R08")
        self.assertEqual(findings[0].severity, "error")

    def test_flags_missing_column(self):
        model = make_model(relationships=[
            Relationship("Sales", "Nope", "Customer", "CustomerID")])
        findings = rule_relationship_type_mismatch(model)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "error")

    def test_matching_types_are_clean(self):
        model = make_model(
            tables=[
                Table(name="Sales", row_count=100, columns=[
                    Column(name="CustomerID", data_type="int", row_count=100, distinct_count=40)]),
                Table(name="Customer", row_count=40, columns=[
                    Column(name="CustomerID", data_type="int", row_count=40, distinct_count=40)]),
            ],
            relationships=[Relationship("Sales", "CustomerID", "Customer", "CustomerID")],
        )
        self.assertEqual(rule_relationship_type_mismatch(model), [])


class TestModelLoading(unittest.TestCase):
    def test_rejects_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                load_model(path)
        finally:
            os.unlink(path)

    def test_rejects_missing_required_key(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"tables": [{"row_count": 5}]}, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                load_model(path)
        finally:
            os.unlink(path)


class TestExamples(unittest.TestCase):
    def test_healthy_model_is_clean(self):
        path = os.path.join(EXAMPLES, "healthy_model.json")
        findings = run_all_rules(load_model(path))
        self.assertEqual(findings, [], f"expected clean, got: {findings}")

    def test_messy_model_triggers_every_rule(self):
        path = os.path.join(EXAMPLES, "messy_model.json")
        findings = run_all_rules(load_model(path))
        rule_ids = {f.rule_id for f in findings}
        self.assertEqual(
            rule_ids,
            {"R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08"},
            f"missing rules, got: {sorted(rule_ids)}",
        )
        self.assertTrue(any(f.severity == "error" for f in findings))

    def test_report_mentions_model_name(self):
        path = os.path.join(EXAMPLES, "healthy_model.json")
        model = load_model(path)
        report = format_report(model, run_all_rules(model))
        self.assertIn("HealthySalesModel", report)
        self.assertIn("Clean", report)


class TestCli(unittest.TestCase):
    def test_clean_model_exits_zero(self):
        path = os.path.join(EXAMPLES, "healthy_model.json")
        self.assertEqual(main([path]), 0)

    def test_model_with_error_exits_one(self):
        path = os.path.join(EXAMPLES, "messy_model.json")
        self.assertEqual(main([path]), 1)

    def test_missing_file_exits_two(self):
        self.assertEqual(main(["/does/not/exist.json"]), 2)


if __name__ == "__main__":
    unittest.main()
