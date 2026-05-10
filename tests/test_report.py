"""Tests for stats calculation and deterministic HTML report generation."""

import tempfile
from pathlib import Path

from test_report_vibes.parser import parse_cucumber_json
from test_report_vibes.filter import (
    calculate_summary_stats,
    filter_issues,
    group_issues_by_feature,
)
from test_report_vibes.html_generator import (
    build_default_executive_summary,
    generate_html_report,
)


SAMPLE_REPORT = Path(__file__).parent.parent / "examples" / "sample_report.json"
ALL_PASSING = Path(__file__).parent / "fixtures" / "all_passing.json"
TAGGED_SCENARIOS = Path(__file__).parent / "fixtures" / "tagged_scenarios.json"
SLOW_STEPS = Path(__file__).parent / "fixtures" / "slow_steps.json"
WITH_SCREENSHOTS = Path(__file__).parent / "fixtures" / "with_screenshots.json"
MIXED_SCENARIOS = Path(__file__).parent / "fixtures" / "mixed_scenarios.json"
MULTIPLE_FAILURES = Path(__file__).parent / "fixtures" / "multiple_failures.json"
MIXED_TAGS_PRIORITY = Path(__file__).parent / "fixtures" / "mixed_tags_priority.json"


def _load_features(path: Path = SAMPLE_REPORT):
    return parse_cucumber_json(str(path))


class TestCalculateSummaryStats:
    def test_total_counts(self):
        stats = calculate_summary_stats(_load_features())
        assert stats["total_features"] == 6
        assert stats["total_scenarios"] == 14
        assert stats["total_steps"] == 45

    def test_percentages_present(self):
        stats = calculate_summary_stats(_load_features())
        assert "passed_pct" in stats
        assert "failed_pct" in stats
        assert "skipped_pct" in stats

    def test_percentages_sum_reasonable(self):
        stats = calculate_summary_stats(_load_features())
        total_pct = stats["passed_pct"] + stats["failed_pct"] + stats["skipped_pct"]
        assert 0 <= total_pct <= 100

    def test_passed_scenarios_count(self):
        stats = calculate_summary_stats(_load_features())
        assert stats["passed_scenarios"] == 8

    def test_failed_scenarios_count(self):
        stats = calculate_summary_stats(_load_features())
        assert stats["failed_scenarios"] == 6

    def test_skipped_scenarios_count(self):
        stats = calculate_summary_stats(_load_features())
        assert stats["skipped_scenarios"] == 0


class TestGenerateHtmlReport:
    def _render(self, features) -> str:
        stats = calculate_summary_stats(features)
        feature_groups = group_issues_by_feature(filter_issues(features))
        metadata = {
            "timestamp": "2026-05-09 12:00:00",
            "input_file": "sample_report.json",
        }
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name
        generate_html_report(
            feature_groups=feature_groups,
            stats=stats,
            metadata=metadata,
            output_path=output_path,
        )
        return Path(output_path).read_text(encoding="utf-8")

    def test_report_renders(self):
        features = _load_features()
        html = self._render(features)
        feature_groups = group_issues_by_feature(filter_issues(features))

        # Stats dashboard elements
        assert "features" in html
        assert "Passed" in html
        assert "Failed" in html
        assert "%" in html

        # Deterministic feature breakdown
        assert html.count('<article class="issue"') == len(feature_groups)
        assert 'class="scenario-block' in html
        assert '<details class="scenario-block" open' not in html and '<details class="scenario-block scenario-failed" open' not in html
        assert 'toggleAllScenarios' in html  # Verify toggle functionality exists

    def test_executive_summary_is_always_present(self):
        html = self._render(_load_features())
        assert 'class="executive-summary"' in html
        assert "Where to pay attention" in html
        # Headline mentions the failure ratio
        assert "feature" in html and "scenario" in html

    def test_executive_summary_when_all_passing(self):
        html = self._render(_load_features(ALL_PASSING))
        assert "All features passed" in html

    def test_toggle_all_scenarios_button_present(self):
        html = self._render(_load_features())
        assert 'toggle-all-scenarios' in html
        assert 'Show scenarios' in html
        assert 'toggleAllScenarios' in html
        assert 'data-feature-index' in html
        assert 'scenarios-container hidden' in html  # Verify scenarios are hidden by default


class TestBuildDefaultExecutiveSummary:
    def test_all_passing_returns_success_card(self):
        stats = calculate_summary_stats(_load_features(ALL_PASSING))
        summary = build_default_executive_summary(stats, [])
        assert "All features passed" in summary
        assert "exec-success" in summary

    def test_failing_summary_includes_top_features(self):
        features = _load_features()
        stats = calculate_summary_stats(features)
        groups = group_issues_by_feature(filter_issues(features))

        summary = build_default_executive_summary(stats, groups)

        assert "Most impacted features" in summary
        # Each top feature name should appear
        for g in groups[:3]:
            assert g["feature_name"] in summary

    def test_failing_summary_contains_no_section_wrapper(self):
        # Wrapping is owned by generate_html_report — keep this function returning
        # raw cards so callers can compose them freely.
        features = _load_features()
        stats = calculate_summary_stats(features)
        groups = group_issues_by_feature(filter_issues(features))

        summary = build_default_executive_summary(stats, groups)
        assert "<section" not in summary

    def test_slow_steps_card_shown_for_steps_over_3s(self):
        """Slow steps card shows individual steps ≥3s duration."""
        features = _load_features(SLOW_STEPS)
        stats = calculate_summary_stats(features)
        groups = group_issues_by_feature(filter_issues(features))

        summary = build_default_executive_summary(stats, groups)

        assert "Slowest failing steps" in summary
        assert "8.5s" in summary  # 8500000000 ns = 8.5s
        assert "I wait for a very long time" in summary

    def test_slow_steps_card_hidden_when_all_fast(self):
        """Slow steps card hidden when no steps are ≥3s."""
        features = _load_features(MIXED_SCENARIOS)
        stats = calculate_summary_stats(features)
        groups = group_issues_by_feature(filter_issues(features))

        summary = build_default_executive_summary(stats, groups)

        # Mixed scenarios fixture has no steps ≥3s
        assert "Slowest failing steps" not in summary

    def test_framework_gaps_separates_undefined_and_pending(self):
        """Framework gaps card shows undefined and pending separately."""
        features = _load_features(SAMPLE_REPORT)
        stats = calculate_summary_stats(features)
        groups = group_issues_by_feature(filter_issues(features))

        summary = build_default_executive_summary(stats, groups)

        assert "Framework gaps" in summary
        assert "Undefined steps:" in summary
        assert "Missing step definitions" in summary
        # Sample report has undefined but not pending
        assert "Pending steps:" not in summary


class TestGroupIssuesByFeature:
    def test_groups_multiple_failing_scenarios_into_one_feature(self):
        features = _load_features()
        groups = group_issues_by_feature(filter_issues(features))

        uris = [g["feature_uri"] for g in groups]
        assert len(uris) == len(set(uris))

        counts = [g["failed_scenario_count"] for g in groups]
        assert counts == sorted(counts, reverse=True)

    def test_only_failing_features_included(self):
        features = _load_features()
        groups = group_issues_by_feature(filter_issues(features))
        stats = calculate_summary_stats(features)
        assert len(groups) == stats["failed_features"]

    def test_includes_passing_scenarios_before_failures_when_features_provided(self):
        """When features are provided, include passing scenarios before last failure."""
        features = _load_features(MIXED_SCENARIOS)
        issues = filter_issues(features)

        # Without features: only failing scenario
        groups_without_features = group_issues_by_feature(issues)
        assert len(groups_without_features) == 1
        assert len(groups_without_features[0]["scenarios"]) == 1  # Only failing scenario

        # With features: passing scenarios before failure + failing scenario
        groups_with_features = group_issues_by_feature(issues, features)
        assert len(groups_with_features) == 1
        assert len(groups_with_features[0]["scenarios"]) == 2  # Passing + failing scenarios

        # First scenario should be passing
        assert groups_with_features[0]["scenarios"][0]["name"] == "Successful login with valid credentials"
        assert groups_with_features[0]["scenarios"][0]["failed_steps"] == 0

        # Second scenario should be failing
        assert groups_with_features[0]["scenarios"][1]["name"] == "Login with invalid password"
        assert groups_with_features[0]["scenarios"][1]["failed_steps"] == 1

        # Third scenario (after last failure) should NOT be included
        scenario_names = [s["name"] for s in groups_with_features[0]["scenarios"]]
        assert "Password reset functionality" not in scenario_names

        # Verify failed_scenario_count only counts scenarios with failures
        assert groups_with_features[0]["failed_scenario_count"] == 1  # Only 1 failing scenario

    def test_includes_all_scenarios_up_to_last_failure_with_multiple_failures(self):
        """With multiple failures, include all scenarios up to last failure."""
        features = _load_features(MULTIPLE_FAILURES)
        issues = filter_issues(features)

        # With features provided
        groups = group_issues_by_feature(issues, features)
        assert len(groups) == 1

        # Should include scenarios 1-4 but not 5
        # Scenario 1: passing
        # Scenario 2: failing
        # Scenario 3: passing
        # Scenario 4: failing (last failure at line 14)
        # Scenario 5: passing (line 17, after last failure) - should be excluded
        scenarios = groups[0]["scenarios"]
        assert len(scenarios) == 4

        scenario_names = [s["name"] for s in scenarios]
        assert scenario_names == [
            "Add item to cart",
            "View cart contents",
            "Update item quantity",
            "Proceed to payment",
        ]

        # Verify Order confirmation (after last failure) is NOT included
        assert "Order confirmation" not in scenario_names

        # Verify failed_scenario_count only counts scenarios with failures
        assert groups[0]["failed_scenario_count"] == 2  # 2 failing scenarios (2 and 4)


class TestNeedsReviewFirstCard:
    def _summary(self, fixture=MIXED_TAGS_PRIORITY):
        features = _load_features(fixture)
        stats = calculate_summary_stats(features)
        groups = group_issues_by_feature(filter_issues(features))
        return build_default_executive_summary(stats, groups)

    def test_card_present_with_mixed_tags(self):
        summary = self._summary()
        assert "Needs review first" in summary

    def test_excludes_bug_reported_and_test_issue(self):
        summary = self._summary()
        assert "Search Feature" not in summary.split("Needs review first")[1].split("</div>")[0]
        assert "User Profile" not in summary.split("Needs review first")[1].split("</div>")[0]

    def test_includes_untagged_features(self):
        summary = self._summary()
        card = summary.split("Needs review first")[1].split("</div>")[0]
        assert "Checkout Flow" in card

    def test_includes_new_issue_and_flaky_and_debugging(self):
        summary = self._summary()
        card = summary.split("Needs review first")[1].split("</div>")[0]
        assert "Login Page" in card
        assert "Shopping Cart" in card
        assert "Dashboard Analytics" in card

    def test_not_reported_features_appear_first(self):
        summary = self._summary()
        card = summary.split("Needs review first")[1].split("</div>")[0]
        checkout_pos = card.index("Checkout Flow")
        login_pos = card.index("Login Page")
        cart_pos = card.index("Shopping Cart")
        assert checkout_pos < login_pos
        assert checkout_pos < cart_pos

    def test_shows_status_pills(self):
        summary = self._summary()
        card = summary.split("Needs review first")[1].split("</div>")[0]
        assert "Not reported" in card
        assert "New and reported" in card
        assert "Flaky Test" in card

    def test_card_shown_for_untagged_features(self):
        """Sample report has no tags — all features should appear in the card."""
        summary = self._summary(SAMPLE_REPORT)
        assert "Needs review first" in summary

    def test_card_hidden_when_all_passing(self):
        summary = self._summary(ALL_PASSING)
        assert "Needs review first" not in summary
