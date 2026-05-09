"""Tag-based issue classification for Cucumber test results.

Classifies failing scenarios by their tags and highlights the first failing
scenario per feature as the most important one to review.
"""

import html
from typing import Dict, List, Any, Optional

# Default mapping from Cucumber tags to human-readable status labels.
# Priority is determined by order: the first matching tag wins.
DEFAULT_TAG_MAPPING: Dict[str, str] = {
    "@new_issue": "New and reported",
    "@under_debugging": "Debugging",
    "@bug_reported": "Bug reported",
    "@test_issue": "Test Framework issue",
    "@flaky": "Flaky Test",
}

NOT_REPORTED = "Not reported"


def classify_status(tags: List[str], tag_mapping: Optional[Dict[str, str]] = None) -> str:
    """Return a human-readable status for a set of tags.

    Iterates through *tags* in order and returns the label of the first tag
    present in *tag_mapping*.  Falls back to ``"Not reported"``.
    """
    mapping = tag_mapping or DEFAULT_TAG_MAPPING
    for tag in tags:
        if tag in mapping:
            return mapping[tag]
    return NOT_REPORTED


def classify_features(
    feature_groups: List[Dict[str, Any]],
    tag_mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Classify every failing feature group.

    For each feature group (as produced by ``filter.group_issues_by_feature``),
    determines:

    * The *first* failing scenario (by position / line number) — this is the
      most important one to review because later scenarios may cascade.
    * A classification status derived from the combined feature + scenario tags
      using ``classify_status``.

    Returns a dict with:
        ``classified_features`` – list of per-feature classification dicts
        ``status_counts``       – breakdown ``{status_label: count}``
        ``total_failed_features`` – number of features with failures
        ``total_failed_scenarios`` – total failing scenarios across all features
    """
    mapping = tag_mapping or DEFAULT_TAG_MAPPING

    classified: List[Dict[str, Any]] = []
    status_counts: Dict[str, int] = {}
    total_failed_scenarios = 0

    for group in feature_groups:
        feature_name: str = group.get("feature_name", "Unknown Feature")
        feature_tags: List[str] = group.get("feature_tags", [])
        scenarios: List[Dict[str, Any]] = group.get("scenarios", [])

        first_failing: Optional[Dict[str, Any]] = None

        for scenario in scenarios:
            # Check if this scenario actually has failures (not just a passing scenario added for context)
            has_failures = (
                scenario.get("failed_steps", 0) > 0 or
                scenario.get("undefined_steps", 0) > 0 or
                scenario.get("pending_steps", 0) > 0
            )

            if not has_failures:
                continue  # Skip passing scenarios

            total_failed_scenarios += 1

            # Merge feature + scenario tags for classification
            all_tags = feature_tags + scenario.get("tags", [])
            status = classify_status(all_tags, mapping)

            # Count every failing scenario by status
            status_counts[status] = status_counts.get(status, 0) + 1

            # The first scenario in the list is by definition the earliest
            # (group_issues_by_feature sorts by line number).
            if first_failing is None:
                first_failing = {
                    "scenario_name": scenario.get("name", "Unnamed Scenario"),
                    "status": status,
                    "tags": all_tags,
                }

        # Count only scenarios with actual failures
        failing_count = sum(
            1 for s in scenarios
            if s.get("failed_steps", 0) > 0 or s.get("undefined_steps", 0) > 0 or s.get("pending_steps", 0) > 0
        )

        classified.append({
            "feature_name": feature_name,
            "first_failing": first_failing,
            "failing_scenario_count": failing_count,
        })

    return {
        "classified_features": classified,
        "status_counts": status_counts,
        "total_failed_features": len(classified),
        "total_failed_scenarios": total_failed_scenarios,
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_STATUS_COLORS: Dict[str, str] = {
    "New and reported": "#9cf3af",
    "Debugging": "#3b89f6",
    "Bug reported": "#ef0000",
    "Test Framework issue": "#8989ff",
    "Flaky Test": "#f59e0b",
    NOT_REPORTED: "#efbb85",
}


def _status_color(status: str) -> str:
    return _STATUS_COLORS.get(status, "#6b7280")


def build_classification_summary_html(classification: Dict[str, Any]) -> str:
    """Render an HTML ``<section>`` with the tag-based classification summary.

    The section has CSS class ``classification-summary`` and is designed to sit
    alongside (but independently of) the executive summary.
    """
    classified = classification["classified_features"]
    status_counts = classification["status_counts"]
    total_features = classification["total_failed_features"]
    total_scenarios = classification["total_failed_scenarios"]

    if total_features == 0:
        return (
            '<section class="classification-summary">'
            "<h2>Classified features</h2>"
            "<p>No failing features to classify.</p>"
            "</section>"
        )

    # --- Feature list (first failing scenario only) ---
    list_items = []
    for entry in classified:
        fname = html.escape(entry["feature_name"])
        first = entry.get("first_failing")
        if first:
            sname = html.escape(first["scenario_name"])
            sstatus = html.escape(first["status"])
            color = _status_color(first["status"])
            list_items.append(
                f"<li>"
                f"<strong>{fname}</strong>"
                f'<ul><li><span class="cls-pill" style="background:{color};">'
                f"{sstatus}</span> {sname}</li></ul>"
                f"</li>"
            )
        else:
            list_items.append(f"<li><strong>{fname}</strong></li>")

    features_html = "\n".join(list_items)

    return (
        '<section class="classification-summary">\n'
        "<h2>Classified features</h2>\n"
        f"<p><strong>Failed Features:</strong> {total_features}</p>\n"
        f"<p><strong>Failed Scenarios:</strong> {total_scenarios}</p>\n"
        '<p style="margin-bottom:0.25rem;color:var(--color-text-light);font-size:0.875rem;">'
        "The first failing scenario in each feature is usually the most important to review, "
        "later failures may cascade from it.</p>\n"
        f"<ul>{features_html}</ul>\n"
        "</section>"
    )

