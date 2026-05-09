"""Filter and extract issues from Cucumber test results."""

import re
from typing import List, Dict, Any, Optional
from .models import Feature, Step, FilteredIssue, FilteredStepContext

_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


def filter_issues(features: List[Feature]) -> List[FilteredIssue]:
    """
    Extract only failures, undefined, and error steps from Cucumber features.

    Filtering criteria:
    - status == "failed"
    - status == "undefined"
    - status == "pending" (unimplemented)

    Excludes:
    - status == "passed"
    - status == "skipped"

    Args:
        features: List of parsed Feature objects

    Returns:
        List of FilteredIssue objects with context
    """
    issues = []

    for feature in features:
        # Extract feature-level tags
        feature_tags = [t.get("name", "") for t in feature.tags if "name" in t]

        for scenario in feature.elements:
            # Extract scenario-level tags
            scenario_tags = [t.get("name", "") for t in scenario.tags if "name" in t]

            # Build all steps context for the scenario
            all_steps_context = _build_steps_context(scenario.steps)

            # Extract before/after hook locations from scenario
            before_hooks = _extract_hook_locations(scenario.before)
            after_hooks = _extract_hook_locations(scenario.after)

            # Collect screenshots from scenario-level before/after hooks
            scenario_screenshots = extract_screenshots_from_hooks(
                scenario.before + scenario.after
            )

            for step in scenario.steps:
                # Check if step has an issue that needs attention
                if step.result.status in ["failed", "undefined", "pending"]:
                    # Extract screenshots from step embeddings and step-level hooks
                    step_screenshots = extract_screenshots(step)
                    # Merge with scenario-level hook screenshots (deduplicated)
                    screenshots = step_screenshots + [
                        s for s in scenario_screenshots if s not in step_screenshots
                    ]

                    # Get step definition location
                    step_location = None
                    if step.match and step.match.location:
                        step_location = step.match.location

                    issue = FilteredIssue(
                        feature_name=feature.name,
                        feature_uri=feature.uri,
                        feature_description=feature.description or None,
                        feature_tags=feature_tags,
                        feature_line=feature.line,
                        scenario_name=scenario.name,
                        scenario_id=scenario.id,
                        scenario_description=scenario.description or None,
                        scenario_tags=scenario_tags,
                        scenario_line=scenario.line,
                        step_keyword=step.keyword,
                        step_name=step.name,
                        step_line=step.line,
                        step_location=step_location,
                        step_duration=step.result.duration,
                        status=step.result.status,
                        error_message=step.result.error_message,
                        screenshots=screenshots,
                        all_steps=all_steps_context,
                        before_hooks=before_hooks,
                        after_hooks=after_hooks,
                    )
                    issues.append(issue)

    return issues


def _build_steps_context(steps: List[Step]) -> List[FilteredStepContext]:
    """Build context list of all steps in a scenario."""
    result = []
    for step in steps:
        location = None
        if step.match and step.match.location:
            location = step.match.location

        result.append(
            FilteredStepContext(
                keyword=step.keyword,
                name=step.name,
                status=step.result.status,
                line=step.line,
                location=location,
                duration=step.result.duration,
                error_message=step.result.error_message,
                output=step.output,
                embeddings_count=len(step.embeddings),
            )
        )
    return result


def _extract_hook_locations(hooks) -> List[str]:
    """Extract location strings from hook entries."""
    locations = []
    for hook in hooks:
        if hook.match and hook.match.location:
            locations.append(hook.match.location)
    return locations


def extract_screenshots(step: Step) -> List[str]:
    """
    Extract base64 image data from step embeddings and step-level after hooks.

    Args:
        step: Step object with potential embeddings

    Returns:
        List of base64 encoded image strings
    """
    screenshots = []

    for embedding in step.embeddings:
        if embedding.mime_type.startswith("image/"):
            screenshots.append(embedding.data)

    # Also check step-level after hooks
    screenshots.extend(extract_screenshots_from_hooks(step.after))

    return screenshots


def extract_screenshots_from_hooks(hooks) -> List[str]:
    """
    Extract base64 image data from hook embeddings.

    Args:
        hooks: List of HookEntry objects

    Returns:
        List of base64 encoded image strings
    """
    screenshots = []
    for hook in hooks:
        for embedding in hook.embeddings:
            if embedding.mime_type.startswith("image/"):
                screenshots.append(embedding.data)
    return screenshots


def calculate_summary_stats(features: List[Feature]) -> Dict[str, int]:
    """
    Calculate statistics for context.

    Provides overall test execution stats to give LLM context about scale
    (e.g., "2 failures out of 50 scenarios" vs "45 failures").

    Args:
        features: List of parsed Feature objects

    Returns:
        Dictionary with statistics
    """
    stats = {
        "total_features": len(features),
        "total_scenarios": 0,
        "total_steps": 0,
        "passed_steps": 0,
        "failed_steps": 0,
        "skipped_steps": 0,
        "pending_steps": 0,
        "undefined_steps": 0,
        "failed_scenarios": 0,
        "passed_scenarios": 0,
        "skipped_scenarios": 0,
        "scenarios_with_issues": 0,
        "passed_features": 0,
        "failed_features": 0,
        "skipped_features": 0,
    }

    for feature in features:
        stats["total_scenarios"] += len(feature.elements)
        feature_has_failure = False
        feature_all_passed = True
        feature_all_skipped = True

        for scenario in feature.elements:
            scenario_has_failure = False
            scenario_all_passed = True
            scenario_all_skipped = True

            for step in scenario.steps:
                stats["total_steps"] += 1

                status = step.result.status
                if status == "passed":
                    stats["passed_steps"] += 1
                    scenario_all_skipped = False
                elif status == "failed":
                    stats["failed_steps"] += 1
                    scenario_has_failure = True
                    scenario_all_passed = False
                    scenario_all_skipped = False
                elif status == "skipped":
                    stats["skipped_steps"] += 1
                    scenario_all_passed = False
                elif status == "pending":
                    stats["pending_steps"] += 1
                    scenario_has_failure = True
                    scenario_all_passed = False
                    scenario_all_skipped = False
                elif status == "undefined":
                    stats["undefined_steps"] += 1
                    scenario_has_failure = True
                    scenario_all_passed = False
                    scenario_all_skipped = False

            if scenario_has_failure:
                stats["failed_scenarios"] += 1
                feature_has_failure = True
                feature_all_passed = False
                feature_all_skipped = False
            if scenario_all_passed and len(scenario.steps) > 0:
                stats["passed_scenarios"] += 1
                feature_all_skipped = False
            if scenario_all_skipped and len(scenario.steps) > 0 and not scenario_has_failure:
                stats["skipped_scenarios"] += 1
                feature_all_passed = False
            if scenario_has_failure:
                stats["scenarios_with_issues"] += 1
            if not scenario_all_skipped and not scenario_has_failure and not scenario_all_passed:
                feature_all_passed = False
                feature_all_skipped = False

        if feature_has_failure:
            stats["failed_features"] += 1
        elif feature_all_skipped and len(feature.elements) > 0:
            stats["skipped_features"] += 1
        elif len(feature.elements) > 0:
            stats["passed_features"] += 1

    # Calculate total issues and failure rate
    stats["total_issues"] = (
        stats["failed_steps"] + stats["undefined_steps"] + stats["pending_steps"]
    )

    total = stats["total_features"]
    if total > 0:
        stats["failure_rate"] = stats["failed_features"] / total
        stats["passed_pct"] = round(stats["passed_features"] / total * 100, 1)
        stats["failed_pct"] = round(stats["failed_features"] / total * 100, 1)
        stats["skipped_pct"] = round(stats["skipped_features"] / total * 100, 1)
    else:
        stats["failure_rate"] = 0.0
        stats["passed_pct"] = 0.0
        stats["failed_pct"] = 0.0
        stats["skipped_pct"] = 0.0

    return stats


def _extract_links(text: str) -> List[str]:
    """Extract HTTP(S) URLs from a free-form text block."""
    if not text:
        return []
    # Strip trailing punctuation that often follows URLs in prose.
    return [u.rstrip(".,;:") for u in _URL_RE.findall(text)]


def _enrich_with_passing_scenarios(
    feature_uri: str,
    failing_scenarios: List[Dict[str, Any]],
    features: List[Feature]
) -> List[Dict[str, Any]]:
    """
    Add passing scenarios that come before the last failing scenario.

    Args:
        feature_uri: URI of the feature to enrich
        failing_scenarios: List of scenarios with failures (already sorted by line)
        features: Original list of all features with all scenarios

    Returns:
        Enriched list of scenarios including passing ones before last failure
    """
    # Find the corresponding feature in the original list
    feature = None
    for f in features:
        if f.uri == feature_uri:
            feature = f
            break

    if not feature:
        return failing_scenarios

    # Find the index of the last failing scenario in the original feature
    last_failing_line = None
    if failing_scenarios:
        # Get the line number of the last failing scenario (they're already sorted)
        last_failing_line = failing_scenarios[-1]["line"]

    if last_failing_line is None:
        return failing_scenarios

    # Build a dict of failing scenario IDs for quick lookup
    failing_scenario_ids = {
        sc["id"] or f"{sc['name']}:{sc['line']}"
        for sc in failing_scenarios
    }

    # Collect all scenarios up to and including the last failing scenario
    enriched = []
    for scenario in feature.elements:
        scenario_line = scenario.line

        # Stop if we've passed the last failing scenario
        if scenario_line and last_failing_line and scenario_line > last_failing_line:
            break

        # Check if this scenario is already in the failing scenarios
        scenario_id = scenario.id or f"{scenario.name}:{scenario.line}"
        if scenario_id in failing_scenario_ids:
            # Already included, find and add it
            for fs in failing_scenarios:
                fs_id = fs["id"] or f"{fs['name']}:{fs['line']}"
                if fs_id == scenario_id:
                    enriched.append(fs)
                    break
        else:
            # This is a passing scenario before the last failure, add it
            scenario_tags = [t.get("name", "") for t in scenario.tags if "name" in t]
            steps_context = _build_steps_context(scenario.steps)

            enriched.append({
                "id": scenario.id,
                "name": scenario.name,
                "description": (scenario.description or "").strip() or None,
                "tags": scenario_tags,
                "line": scenario.line,
                "steps": steps_context,
                "screenshots": [],
                "failed_steps": 0,
                "undefined_steps": 0,
                "pending_steps": 0,
            })

    return enriched


def group_issues_by_feature(issues: List[FilteredIssue], features: Optional[List[Feature]] = None) -> List[Dict[str, Any]]:
    """
    Group filtered issues by feature.

    Each returned group represents a single failing feature (regardless of how
    many scenarios fail inside it) and contains the unique failing scenarios
    with their full step context, deduplicated tags, and links extracted from
    the feature description.

    If features list is provided, also includes passing scenarios that come
    before the last failing scenario in each feature.

    Groups are sorted by number of failing scenarios (desc) then feature name.
    """
    groups: Dict[str, Dict[str, Any]] = {}

    for issue in issues:
        key = issue.feature_uri or issue.feature_name
        group = groups.get(key)
        if group is None:
            group = {
                "feature_name": issue.feature_name,
                "feature_uri": issue.feature_uri,
                "feature_description": (issue.feature_description or "").strip() or None,
                "feature_links": _extract_links(issue.feature_description or ""),
                "feature_tags": list(issue.feature_tags),
                "_scenarios": {},
            }
            groups[key] = group
        else:
            for t in issue.feature_tags:
                if t not in group["feature_tags"]:
                    group["feature_tags"].append(t)

        scen_key = issue.scenario_id or f"{issue.scenario_name}:{issue.scenario_line}"
        scenario = group["_scenarios"].get(scen_key)
        if scenario is None:
            scenario = {
                "id": issue.scenario_id,
                "name": issue.scenario_name,
                "description": (issue.scenario_description or "").strip() or None,
                "tags": list(issue.scenario_tags),
                "line": issue.scenario_line,
                "steps": list(issue.all_steps),
                "screenshots": list(issue.screenshots),
                "failed_steps": 0,
                "undefined_steps": 0,
                "pending_steps": 0,
            }
            group["_scenarios"][scen_key] = scenario
        else:
            for t in issue.scenario_tags:
                if t not in scenario["tags"]:
                    scenario["tags"].append(t)
            for sc in issue.screenshots:
                if sc not in scenario["screenshots"]:
                    scenario["screenshots"].append(sc)

        if issue.status == "failed":
            scenario["failed_steps"] += 1
        elif issue.status == "undefined":
            scenario["undefined_steps"] += 1
        elif issue.status == "pending":
            scenario["pending_steps"] += 1

    result: List[Dict[str, Any]] = []
    for group in groups.values():
        scenarios = list(group.pop("_scenarios").values())
        # Stable scenario order: by line number when present, else by name.
        scenarios.sort(key=lambda s: (s["line"] is None, s["line"] or 0, s["name"]))

        # If features provided, enrich with passing scenarios before last failing scenario
        if features:
            scenarios = _enrich_with_passing_scenarios(
                group["feature_uri"],
                scenarios,
                features
            )

        # Combined, de-duplicated tag list (feature tags first, then scenario tags).
        combined: List[str] = list(group["feature_tags"])
        for sc in scenarios:
            for t in sc["tags"]:
                if t not in combined:
                    combined.append(t)

        group["scenarios"] = scenarios
        group["combined_tags"] = combined
        # Count only scenarios with actual failures (not passing scenarios)
        group["failed_scenario_count"] = sum(
            1 for s in scenarios
            if s["failed_steps"] > 0 or s["undefined_steps"] > 0 or s["pending_steps"] > 0
        )
        group["total_failed_steps"] = sum(s["failed_steps"] for s in scenarios)
        group["total_undefined_steps"] = sum(s["undefined_steps"] for s in scenarios)
        group["total_pending_steps"] = sum(s["pending_steps"] for s in scenarios)
        result.append(group)

    result.sort(
        key=lambda g: (-g["failed_scenario_count"], (g["feature_name"] or "").lower())
    )
    return result

