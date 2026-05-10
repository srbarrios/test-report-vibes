"""Test Report Vibes - deterministic HTML summaries of Cucumber test reports."""

__version__ = "0.2.1"
__author__ = "Test Report Vibes Contributors"
__description__ = "Deterministic HTML summaries of Cucumber test reports"

from .parser import parse_cucumber_json
from .filter import filter_issues, calculate_summary_stats, group_issues_by_feature
from .html_generator import generate_html_report, build_default_executive_summary
from .classifier import classify_features, build_classification_summary_html
from .models import Feature, Scenario, Step, FilteredIssue

__all__ = [
    "parse_cucumber_json",
    "filter_issues",
    "calculate_summary_stats",
    "group_issues_by_feature",
    "generate_html_report",
    "build_default_executive_summary",
    "classify_features",
    "build_classification_summary_html",
    "Feature",
    "Scenario",
    "Step",
    "FilteredIssue",
]
