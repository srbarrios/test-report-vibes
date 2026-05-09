"""Tests for the classifier module."""

from pathlib import Path

from test_report_vibes.parser import parse_cucumber_json
from test_report_vibes.filter import filter_issues, group_issues_by_feature
from test_report_vibes.classifier import classify_features


MULTIPLE_FAILURES = Path(__file__).parent / "fixtures" / "multiple_failures.json"
MIXED_SCENARIOS = Path(__file__).parent / "fixtures" / "mixed_scenarios.json"


def test_classify_features_counts_only_failing_scenarios():
    """Verify that classification only counts scenarios with actual failures."""
    # Load features with passing scenarios before failures
    features = parse_cucumber_json(str(MULTIPLE_FAILURES))
    issues = filter_issues(features)
    groups = group_issues_by_feature(issues, features)

    # Classify features
    classification = classify_features(groups)

    # Should have 2 failing scenarios (not 4 which includes passing scenarios)
    assert classification["total_failed_scenarios"] == 2

    # The feature should report 2 failing scenarios
    assert classification["classified_features"][0]["failing_scenario_count"] == 2


def test_classify_features_with_single_failure():
    """Verify classification with single failing scenario and passing context."""
    features = parse_cucumber_json(str(MIXED_SCENARIOS))
    issues = filter_issues(features)
    groups = group_issues_by_feature(issues, features)

    classification = classify_features(groups)

    # Should have 1 failing scenario (not 2 which includes passing scenario)
    assert classification["total_failed_scenarios"] == 1
    assert classification["classified_features"][0]["failing_scenario_count"] == 1
