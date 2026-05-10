"""HTML report generator with Jinja2 templates (fully deterministic)."""

import html
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from jinja2 import Environment, BaseLoader, Template

from .classifier import classify_status, _status_color


_STATUS_ICON = {
    "passed": "✓",
    "failed": "✗",
    "skipped": "○",
    "undefined": "○",
    "pending": "○",
}


def _format_duration(duration_ns: Optional[int]) -> str:
    """Format a nanosecond duration as ``[N.NNs]`` (empty string if missing)."""
    if duration_ns is None:
        return ""
    return f"[{duration_ns / 1_000_000_000:.2f}s]"


def _status_icon(status: str) -> str:
    return _STATUS_ICON.get(status, "○")


def _format_description(text: str) -> str:
    """Make URLs clickable and remove 'Related' lines."""
    if not text:
        return ""

    text = re.sub(r'(?i)\*?\s*Related GitHub Card:\s*https?://[^\s]+', '', text)
    text = re.sub(r'(?i)Related:\s*https?://[^\s]+', '', text)

    text = html.escape(text.strip())

    url_pattern = re.compile(r'(https?://[^\s]+)')
    text = url_pattern.sub(
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', text
    )

    return text.strip()


# ---------------------------------------------------------------------------
# Deterministic executive summary helpers
# ---------------------------------------------------------------------------

# Normalize error messages so similar failures group together.
_ERROR_NORMALIZE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"0x[0-9a-fA-F]+"), "0x?"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*"), "<TS>"),
    (re.compile(r"\b\d+\.\d+\.\d+\.\d+(?::\d+)?\b"), "<IP>"),
    (re.compile(r"https?://\S+"), "<URL>"),
    (re.compile(r"/[\w./\-]+:\d+(?::in `[^']+')?"), "<TRACE>"),
    (re.compile(r"\b\d{3,}\b"), "<N>"),
]

_ERROR_TYPE_RE = re.compile(r"^([A-Z][A-Za-z0-9_:]*(?:Error|Exception|Failure))\b")


def _normalize_error(message: str) -> str:
    """Reduce an error message to a comparable signature."""
    line = (message or "").strip().splitlines()[0] if message else ""
    line = line.strip()
    if not line:
        return ""
    for pattern, replacement in _ERROR_NORMALIZE_PATTERNS:
        line = pattern.sub(replacement, line)
    # Cap length so very long signatures don't dominate the layout.
    return line[:160]


def _extract_error_type(message: str) -> Optional[str]:
    """Best-effort extraction of an exception/error class name."""
    if not message:
        return None
    first = message.strip().splitlines()[0].strip()
    match = _ERROR_TYPE_RE.match(first)
    return match.group(1) if match else None


def _collect_failed_steps(feature_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten every failing/undefined/pending step across all features."""
    failed_steps: List[Dict[str, Any]] = []
    for group in feature_groups:
        for scenario in group.get("scenarios", []):
            for step in scenario.get("steps", []):
                status = step.get("status") if isinstance(step, dict) else step.status
                if status in ("failed", "undefined", "pending"):
                    failed_steps.append(
                        {
                            "feature_name": group.get("feature_name", ""),
                            "scenario_name": scenario.get("name", ""),
                            "status": status,
                            "keyword": (
                                step.get("keyword") if isinstance(step, dict) else step.keyword
                            ),
                            "name": (
                                step.get("name") if isinstance(step, dict) else step.name
                            ),
                            "duration": (
                                step.get("duration")
                                if isinstance(step, dict)
                                else step.duration
                            ),
                            "error_message": (
                                step.get("error_message")
                                if isinstance(step, dict)
                                else step.error_message
                            ),
                        }
                    )
    return failed_steps


def _scenario_total_duration(scenario: Dict[str, Any]) -> int:
    total = 0
    for step in scenario.get("steps", []):
        d = step.get("duration") if isinstance(step, dict) else step.duration
        if d:
            total += d
    return total


def _collect_tag_patterns(feature_groups: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
    """Collect tag frequency across failing scenarios, filter noise.

    Returns list of (tag, count) tuples for tags appearing in 2+ scenarios,
    excluding common noise tags. Limited to top 5.
    """
    tag_counter = Counter()
    for group in feature_groups:
        for scenario in group.get("scenarios", []):
            for tag in scenario.get("tags", []):
                tag_counter[tag] += 1

    # Filter: tags appearing in 2+ scenarios, exclude noise tags
    NOISE_TAGS = {"@wip", "@dev", "@test", "@skip"}
    relevant = [
        (tag, count) for tag, count in tag_counter.most_common()
        if count >= 2 and tag not in NOISE_TAGS
    ][:5]

    return relevant


def _collect_slow_steps(feature_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect steps with duration ≥3s, return top 5 by duration.

    Each dict contains: duration, keyword, name, feature, scenario.
    """
    THRESHOLD_NS = 3_000_000_000  # 3 seconds
    slow_steps = []

    for group in feature_groups:
        for scenario in group.get("scenarios", []):
            for step in scenario.get("steps", []):
                duration = step.get("duration") if isinstance(step, dict) else getattr(step, "duration", None)
                if duration and duration >= THRESHOLD_NS:
                    slow_steps.append({
                        "duration": duration,
                        "keyword": step.get("keyword", "") if isinstance(step, dict) else step.keyword,
                        "name": step.get("name", "") if isinstance(step, dict) else step.name,
                        "feature": group.get("feature_name", ""),
                        "scenario": scenario.get("name", ""),
                    })

    slow_steps.sort(key=lambda s: s["duration"], reverse=True)
    return slow_steps[:5]


def _collect_screenshot_scenarios(feature_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect scenarios with screenshots, sort by count.

    Each dict contains: feature, scenario, count.
    """
    scenarios_with_screenshots = []

    for group in feature_groups:
        for scenario in group.get("scenarios", []):
            screenshot_count = len(scenario.get("screenshots", []))
            if screenshot_count > 0:
                scenarios_with_screenshots.append({
                    "feature": group.get("feature_name", ""),
                    "scenario": scenario.get("name", ""),
                    "count": screenshot_count,
                })

    scenarios_with_screenshots.sort(key=lambda s: s["count"], reverse=True)
    return scenarios_with_screenshots[:5]


def build_default_executive_summary(
    stats: Dict[str, Any], feature_groups: List[Dict[str, Any]]
) -> str:
    """Build a rich, fully deterministic executive summary highlighting where to focus.

    The summary is composed of several optional cards:
      * Headline – overall failed features / scenarios / failure rate.
      * Most impacted features – top failing features by failing scenario count.
      * Recurring error patterns – grouped by normalized error signature.
      * Undefined / pending steps – framework gaps to fix in code.
      * Slowest failing scenarios – likely timeouts or infra trouble.
    """
    failed_features = stats.get("failed_features", len(feature_groups))
    total_features = stats.get("total_features", 0)
    failed_scenarios = stats.get("failed_scenarios", 0)
    total_scenarios = stats.get("total_scenarios", 0)
    failure_rate = stats.get("failure_rate", 0.0)
    undefined_steps = stats.get("undefined_steps", 0)
    pending_steps = stats.get("pending_steps", 0)

    if failed_features == 0:
        return (
            '<div class="exec-card exec-headline exec-success">'
            "<p>✅ All features passed. No failures detected.</p>"
            "</div>"
        )

    cards: List[str] = []

    # --- Headline ---------------------------------------------------------
    headline = (
        f"<p><strong>{failed_features}</strong> of <strong>{total_features}</strong> "
        f"feature{'s' if total_features != 1 else ''} failed "
        f"({failure_rate:.1%}), accounting for <strong>{failed_scenarios}</strong> "
        f"of <strong>{total_scenarios}</strong> scenarios.</p>"
    )
    cards.append(f'<div class="exec-card exec-headline">{headline}</div>')

    # --- Most impacted features ------------------------------------------
    top_features = feature_groups[:5]
    if top_features:
        items = "".join(
            f"<li><strong>{html.escape(g.get('feature_name', ''))}</strong>"
            f" &mdash; {g.get('failed_scenario_count', 0)} failing "
            f"scenario{'s' if g.get('failed_scenario_count', 0) != 1 else ''}</li>"
            for g in top_features
        )
        cards.append(
            '<div class="exec-card">'
            "<h3>🎯 Most impacted features</h3>"
            f"<ol>{items}</ol>"
            "</div>"
        )

    # --- Needs review first ----------------------------------------------
    ALREADY_TRACKED = {"Bug reported", "Test Framework issue"}
    _REVIEW_PRIORITY = {
        "Not reported": 0,
        "New and reported": 1,
        "Debugging": 2,
        "Flaky Test": 3,
    }

    review_candidates = []
    for g in feature_groups:
        status = classify_status(g.get("combined_tags", []))
        if status in ALREADY_TRACKED:
            continue
        review_candidates.append((g, status))

    review_candidates.sort(
        key=lambda pair: (
            _REVIEW_PRIORITY.get(pair[1], 99),
            -pair[0].get("failed_scenario_count", 0),
        )
    )

    if review_candidates:
        items = "".join(
            f"<li><strong>{html.escape(g.get('feature_name', ''))}</strong>"
            f" &mdash; {g.get('failed_scenario_count', 0)} failing "
            f"scenario{'s' if g.get('failed_scenario_count', 0) != 1 else ''}"
            f" <span class='cls-pill' style='background:{_status_color(status)};'>"
            f"{html.escape(status)}</span></li>"
            for g, status in review_candidates[:5]
        )
        cards.append(
            '<div class="exec-card">'
            "<h3>🔍 Needs review first</h3>"
            "<p class='exec-muted'>Features not yet tracked as bugs or test issues, "
            "sorted by review priority and impact.</p>"
            f"<ol>{items}</ol>"
            "</div>"
        )

    failed_steps = _collect_failed_steps(feature_groups)

    # --- Recurring error patterns ----------------------------------------
    signatures = Counter()
    sig_examples: Dict[str, str] = {}
    for step in failed_steps:
        sig = _normalize_error(step["error_message"] or "")
        if not sig:
            continue
        signatures[sig] += 1
        sig_examples.setdefault(sig, step["feature_name"])

    recurring = [
        (sig, count)
        for sig, count in signatures.most_common()
        if count >= 2
    ][:5]

    if recurring:
        items = "".join(
            f"<li><span class='exec-count'>×{count}</span> "
            f"<code>{html.escape(sig)}</code>"
            f" <span class='exec-muted'>(first seen in "
            f"{html.escape(sig_examples[sig])})</span></li>"
            for sig, count in recurring
        )
        cards.append(
            '<div class="exec-card">'
            "<h3>🔁 Recurring error patterns</h3>"
            "<p class='exec-muted'>Grouped by normalized error signature, investigate "
            "shared root causes first.</p>"
            f"<ul class='exec-list'>{items}</ul>"
            "</div>"
        )

    # --- Top error types -------------------------------------------------
    error_types = Counter()
    for step in failed_steps:
        et = _extract_error_type(step["error_message"] or "")
        if et:
            error_types[et] += 1

    top_error_types = error_types.most_common(5)
    if top_error_types:
        pills = "".join(
            f"<span class='exec-pill'>{html.escape(et)} "
            f"<span class='exec-count'>×{count}</span></span>"
            for et, count in top_error_types
        )
        cards.append(
            '<div class="exec-card">'
            "<h3>🏷️ Top error types</h3>"
            f"<div class='exec-pills'>{pills}</div>"
            "</div>"
        )

    # --- Undefined / pending steps --------------------------------------
    if undefined_steps or pending_steps:
        sections = []

        if undefined_steps:
            # Collect features with undefined steps
            undefined_features = [
                (g.get("feature_name", ""), g.get("total_undefined_steps", 0))
                for g in feature_groups
                if g.get("total_undefined_steps", 0) > 0
            ]
            undefined_features.sort(key=lambda x: x[1], reverse=True)

            # Build undefined section with top 3 features
            section_html = (
                f"<div style='margin-bottom:0.5rem;'>"
                f"<strong>Undefined steps:</strong> <span class='exec-count'>×{undefined_steps}</span>"
                f"<p class='exec-muted' style='margin:0.25rem 0 0 0;'>Missing step definitions</p>"
            )
            if undefined_features:
                items = "".join(
                    f"<li>{html.escape(fname)} <span class='exec-count'>×{count}</span></li>"
                    for fname, count in undefined_features[:3]
                )
                section_html += f"<ul class='exec-list' style='font-size:0.85rem;'>{items}</ul>"
            section_html += "</div>"
            sections.append(section_html)

        if pending_steps:
            # Collect features with pending steps
            pending_features = [
                (g.get("feature_name", ""), g.get("total_pending_steps", 0))
                for g in feature_groups
                if g.get("total_pending_steps", 0) > 0
            ]
            pending_features.sort(key=lambda x: x[1], reverse=True)

            # Build pending section with top 3 features
            section_html = (
                f"<div>"
                f"<strong>Pending steps:</strong> <span class='exec-count'>×{pending_steps}</span>"
                f"<p class='exec-muted' style='margin:0.25rem 0 0 0;'>Marked as TODO</p>"
            )
            if pending_features:
                items = "".join(
                    f"<li>{html.escape(fname)} <span class='exec-count'>×{count}</span></li>"
                    for fname, count in pending_features[:3]
                )
                section_html += f"<ul class='exec-list' style='font-size:0.85rem;'>{items}</ul>"
            section_html += "</div>"
            sections.append(section_html)

        cards.append(
            '<div class="exec-card exec-warn">'
            "<h3>⚙️ Framework gaps</h3>"
            f"{''.join(sections)}"
            "</div>"
        )

    # --- Slowest failing scenarios --------------------------------------
    scenario_durations: List[Tuple[int, str, str]] = []
    for group in feature_groups:
        for scenario in group.get("scenarios", []):
            duration = _scenario_total_duration(scenario)
            if duration > 0:
                scenario_durations.append(
                    (duration, group.get("feature_name", ""), scenario.get("name", ""))
                )

    scenario_durations.sort(reverse=True)
    slowest = scenario_durations[:3]
    # Only show when at least one scenario takes > 5s — otherwise it's noise.
    if slowest and slowest[0][0] >= 5_000_000_000:
        items = "".join(
            f"<li><code>{(duration / 1_000_000_000):.1f}s</code> "
            f"<strong>{html.escape(scenario)}</strong> "
            f"<span class='exec-muted'>in {html.escape(feature)}</span></li>"
            for duration, feature, scenario in slowest
        )
        cards.append(
            '<div class="exec-card">'
            "<h3>🐢 Slowest failing scenarios</h3>"
            "<p class='exec-muted'>Long-running failures often signal timeouts or "
            "infrastructure issues.</p>"
            f"<ul class='exec-list'>{items}</ul>"
            "</div>"
        )

    # --- Slowest failing steps -------------------------------------------
    slow_steps = _collect_slow_steps(feature_groups)
    if slow_steps:
        items = "".join(
            f"<li><code>{(step['duration'] / 1_000_000_000):.1f}s</code> "
            f"<strong>{html.escape(step['keyword'])}</strong>{html.escape(step['name'])} "
            f"<span class='exec-muted'>in {html.escape(step['feature'])} / "
            f"{html.escape(step['scenario'])}</span></li>"
            for step in slow_steps
        )
        cards.append(
            '<div class="exec-card">'
            "<h3>⏱️ Slowest failing steps</h3>"
            "<p class='exec-muted'>Individual steps with longest execution times</p>"
            f"<ul class='exec-list'>{items}</ul>"
            "</div>"
        )

    return "".join(cards)


def generate_html_report(
    feature_groups: List[Dict[str, Any]],
    stats: Dict[str, Any],
    metadata: Dict[str, str],
    output_path: str,
    classification_html: str = "",
) -> None:
    """Generate a complete deterministic HTML report.

    Args:
        feature_groups: Output of ``filter.group_issues_by_feature``.
        stats: Test statistics for the header dashboard.
        metadata: Report metadata (timestamp, input file, ...).
        output_path: Where to save the HTML file.
        classification_html: Optional pre-rendered classification ``<section>``.
    """
    summary_body = build_default_executive_summary(stats, feature_groups)
    summary_html = (
        '<section class="executive-summary">'
        '<h2 class="exec-title">Where to pay attention</h2>'
        f'<div class="exec-grid">{summary_body}</div>'
        "</section>"
    )

    env = Environment(
        loader=BaseLoader(),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["format_duration"] = _format_duration
    env.filters["status_icon"] = _status_icon
    env.filters["format_description"] = _format_description

    template = env.from_string(_TEMPLATE_STRING)

    html_output = template.render(
        feature_groups=feature_groups,
        stats=stats,
        metadata=metadata,
        executive_summary_html=summary_html,
        classification_html=classification_html,
    )

    Path(output_path).write_text(html_output, encoding="utf-8")


def get_html_template() -> Template:
    """Return the Jinja2 template (kept for backwards compatibility / tests)."""
    env = Environment(
        loader=BaseLoader(),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["format_duration"] = _format_duration
    env.filters["status_icon"] = _status_icon
    env.filters["format_description"] = _format_description
    return env.from_string(_TEMPLATE_STRING)


_TEMPLATE_STRING = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Report - {{ metadata.timestamp }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --color-error: #ef4444;
            --color-warning: #f59e0b;
            --color-success: #10b981;
            --color-info: #3b82f6;
            --color-skipped: #9ca3af;
            --color-bg: #f9fafb;
            --color-surface: #ffffff;
            --color-text: #1f2937;
            --color-text-light: #6b7280;
            --color-border: #e5e7eb;
            --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
            --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto',
                         'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: var(--color-text);
            background: var(--color-bg);
            padding: 2rem 1rem;
        }

        .container { max-width: 100%; margin: 0 auto; }

        /* Header */
        .header {
            background: var(--color-surface);
            padding: 2rem;
            border-radius: 12px;
            box-shadow: var(--shadow-md);
            margin-bottom: 2rem;
        }
        .header h1 {
            font-size: 2rem; font-weight: 700;
            color: var(--color-text); margin-bottom: 0.5rem;
        }
        .header .meta { color: var(--color-text-light); font-size: 0.875rem; margin-bottom: 1.5rem; }
        .header .meta p { margin: 0.25rem 0; }

        .stats-dashboard { margin-top: 1.5rem; }
        .stats-summary-row {
            display: flex; align-items: baseline;
            gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1rem;
        }
        .stats-summary-row .big-number {
            font-size: 2.5rem; font-weight: 800;
            color: var(--color-text); line-height: 1;
        }
        .stats-summary-row .big-label {
            font-size: 0.875rem; color: var(--color-text-light); font-weight: 500;
        }

        .pct-bar-container { margin-bottom: 0.75rem; }
        .pct-bar {
            display: flex; height: 18px; border-radius: 9px;
            overflow: hidden; background: var(--color-border);
        }
        .pct-bar .segment { transition: width 0.4s ease; min-width: 0; }
        .pct-bar .segment.passed  { background: var(--color-success); }
        .pct-bar .segment.failed  { background: var(--color-error); }
        .pct-bar .segment.skipped { background: var(--color-skipped); }

        .pct-legend {
            display: flex; flex-wrap: wrap; gap: 1.25rem;
            margin-top: 0.5rem; font-size: 0.8125rem; color: var(--color-text-light);
        }
        .pct-legend span::before {
            content: ''; display: inline-block;
            width: 10px; height: 10px; border-radius: 2px;
            margin-right: 4px; vertical-align: middle;
        }
        .pct-legend .l-passed::before  { background: var(--color-success); }
        .pct-legend .l-failed::before  { background: var(--color-error); }
        .pct-legend .l-skipped::before { background: var(--color-skipped); }

        /* Main */
        main {
            background: var(--color-surface);
            padding: 2rem; border-radius: 12px;
            box-shadow: var(--shadow-md);
        }

        main h2 {
            font-size: 1.75rem; font-weight: 700;
            color: var(--color-text); margin-bottom: 1rem;
            padding-bottom: 0.5rem; border-bottom: 2px solid var(--color-border);
        }
        main h3 { font-size: 1.375rem; font-weight: 600; color: var(--color-text); margin-top: 1rem; margin-bottom: 0.5rem; }
        main h4 { font-size: 1.0625rem; font-weight: 600; color: var(--color-text); margin-top: 1rem; margin-bottom: 0.5rem; }
        main p  { margin-bottom: 1rem; line-height: 1.7; }

        section { margin-bottom: 2rem; }

        /* Executive summary cards */
        section.executive-summary { padding: 0.5rem 0 0; }
        section.executive-summary .exec-title {
            color: var(--color-text);
            font-size: 1.25rem;
            font-weight: 700;
            margin: 0 0 0.75rem 0;
            padding-bottom: 0.4rem;
            border-bottom: 2px solid var(--color-border);
        }
        section.executive-summary .exec-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 0.75rem;
        }
        section.executive-summary .exec-card {
            background: var(--color-bg);
            border: 1px solid var(--color-border);
            border-radius: 8px;
            padding: 0.85rem 1rem;
            color: var(--color-text);
        }
        section.executive-summary .exec-card h3 {
            font-size: 0.9375rem;
            font-weight: 700;
            margin: 0 0 0.5rem 0;
            color: var(--color-text);
        }
        section.executive-summary .exec-card p,
        section.executive-summary .exec-card li {
            color: var(--color-text);
            font-size: 0.9rem;
            line-height: 1.5;
            margin: 0 0 0.25rem 0;
        }
        section.executive-summary .exec-card ol,
        section.executive-summary .exec-card ul {
            margin: 0.25rem 0 0 1.25rem;
            padding: 0;
        }
        section.executive-summary .exec-headline {
            grid-column: 1 / -1;
            background: var(--color-surface);
            border-left: 4px solid var(--color-error);
        }
        section.executive-summary .exec-headline.exec-success {
            border-left-color: var(--color-success);
        }
        section.executive-summary .exec-warn {
            border-left: 4px solid var(--color-warning);
        }
        section.executive-summary .exec-list { list-style: none; margin-left: 0; }
        section.executive-summary .exec-list li {
            padding: 0.25rem 0;
            border-bottom: 1px dashed var(--color-border);
        }
        section.executive-summary .exec-list li:last-child { border-bottom: none; }
        section.executive-summary .exec-count {
            display: inline-block;
            background: var(--color-error);
            color: white;
            font-weight: 700;
            font-size: 0.75rem;
            padding: 0.05rem 0.45rem;
            border-radius: 999px;
            margin-right: 0.35rem;
        }
        section.executive-summary .exec-muted {
            color: var(--color-text-light);
            font-size: 0.8125rem;
        }
        section.executive-summary .exec-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
        }
        section.executive-summary .exec-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 999px;
            padding: 0.15rem 0.6rem;
            font-size: 0.8125rem;
            font-weight: 600;
        }
        section.executive-summary code {
            background: var(--color-surface);
            padding: 0.1rem 0.35rem;
            border-radius: 3px;
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            font-size: 0.8125rem;
            color: var(--color-text);
        }

        article.issue {
            background: var(--color-bg);
            padding: 0.5rem; margin-bottom: 0.5rem;
            border-radius: 8px;
            box-shadow: var(--shadow-sm);
        }

        .feature-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 0.5rem;
            gap: 1rem;
        }

        .feature-header h3 {
            margin: 0;
            flex: 1;
        }

        .toggle-all-scenarios {
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 6px;
            padding: 0.4rem 0.75rem;
            font-size: 0.8125rem;
            font-weight: 500;
            color: var(--color-text);
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.35rem;
            transition: all 0.2s;
            white-space: nowrap;
            margin-left: auto;
        }

        .toggle-all-scenarios:hover {
            background: var(--color-border);
            border-color: var(--color-text-light);
        }

        .toggle-all-scenarios .toggle-icon {
            font-size: 0.7rem;
            transition: transform 0.2s;
        }

        .toggle-all-scenarios.expanded .toggle-icon {
            transform: rotate(180deg);
        }

        .scenarios-container {
            display: block;
        }

        .scenarios-container.hidden {
            display: none;
        }

        .issue-meta p { margin-bottom: 0.35rem; }

        code {
            color: black;
            padding: 0.2rem 0.5rem; border-radius: 4px;
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            font-size: 0.875rem;
        }

        /* Tag badges */
        .badge {
            display: inline-block; padding: 0.15rem 0.5rem;
            border-radius: 4px; font-size: 0.6875rem;
            font-weight: 600; text-transform: uppercase;
            color: white; white-space: nowrap;
        }
        .badge.failed    { background: var(--color-error); }
        .badge.undefined { background: var(--color-warning); }
        .badge.pending   { background: var(--color-info); }
        .badge.muted     { background: var(--color-text-light); }

        .tags-list {
            display: flex; flex-wrap: wrap;
            gap: 0.4rem; list-style: none;
            margin: 0 0 0.75rem 0; padding: 0;
        }
        .tags-list li { margin: 0; }
        .tags-list .badge { background: var(--color-text-light); }

        /* Native <details> scenario block */
        details.scenario-block {
            border: 1px solid var(--color-border);
            border-radius: 6px;
            margin: 0.5rem 0;
            background: var(--color-surface);
            overflow: hidden;
        }

        details.scenario-block.scenario-failed {
            background: #fef2f2;
            border-color: #fecaca;
        }

        details.scenario-block > summary {
            list-style: none;
            cursor: pointer;
            padding: 0.6rem 0.85rem;
            display: flex;
            align-items: center;
            gap: 0.6rem;
            background: var(--color-bg);
            user-select: none;
            transition: background 0.15s;
        }

        details.scenario-block.scenario-failed > summary {
            background: #fee2e2;
        }
        details.scenario-block > summary::-webkit-details-marker { display: none; }
        details.scenario-block > summary::before {
            content: "▶";
            font-size: 0.7rem;
            color: var(--color-text-light);
            transition: transform 0.2s;
            flex-shrink: 0;
        }
        details.scenario-block[open] > summary::before { transform: rotate(90deg); }
        details.scenario-block > summary:hover { background: var(--color-border); }
        details.scenario-block.scenario-failed > summary:hover { background: #fecaca; }

        .scenario-summary-name {
            flex: 1;
            font-size: 0.95rem;
            font-weight: 600;
        }
        .scenario-summary-name .scenario-keyword {
            color: var(--color-text-light);
            font-weight: 400;
            margin-right: 0.25rem;
        }

        .scenario-body-inner { padding: 0.75rem 1rem 1rem; background-color: white; }

        .scenario-steps-list {
            list-style: none; margin: 0; padding: 0;
            border: 1px solid var(--color-border);
            border-radius: 6px; overflow: hidden;
        }
        .scenario-steps-list > li { margin: 0; border-bottom: 1px solid var(--color-border); }
        .scenario-steps-list > li:last-child { border-bottom: none; }

        .step-content {
            display: flex; align-items: flex-start;
            gap: 0.625rem; padding: 0.5rem 0.75rem;
            font-size: 0.9rem; line-height: 1.5;
        }

        .step-status-icon {
            flex-shrink: 0; width: 1.25rem; height: 1.25rem;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 0.75rem; font-weight: 700;
            color: white; margin-top: 0.15rem;
        }
        .step-status-icon.passed    { background: var(--color-success); }
        .step-status-icon.failed    { background: var(--color-error); }
        .step-status-icon.skipped   { background: var(--color-skipped); }
        .step-status-icon.undefined { background: var(--color-warning); }
        .step-status-icon.pending   { background: var(--color-info); }

        .step-text { flex: 1; min-width: 0; }
        .step-text .step-keyword { font-weight: 700; color: var(--color-text-light); margin-right: 0.25rem; }
        .step-text .step-duration { color: var(--color-text-light); font-size: 0.8125rem; margin-left: 0.5rem; }
        .step-text .step-location {
            display: block; color: var(--color-text-light);
            font-size: 0.75rem;
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            margin-top: 0.15rem;
        }

        .step-error-detail {
            background: #fef2f2; color: var(--color-error);
            padding: 0.75rem 1rem 0.75rem 2.625rem;
            margin: 0;
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            font-size: 0.8125rem;
            white-space: pre-wrap; word-break: break-word;
            border-top: 1px solid #fecaca;
        }

        .step-embedded-content {
            padding: 0.5rem 0.75rem 0.5rem 2.625rem;
            border-top: 1px solid var(--color-border);
            background: var(--color-bg);
        }
        .step-embedded-content img {
            max-width: 100%; height: auto;
            border: 2px solid var(--color-border);
            border-radius: 8px; margin: 0.5rem 0;
            box-shadow: var(--shadow-md); display: block;
        }

        .scenario-counts {
            display: inline-flex; gap: 0.35rem;
            margin-left: 0.5rem; flex-shrink: 0;
        }

        footer {
            margin-top: 3rem; padding: 2rem;
            text-align: center; color: var(--color-text-light); font-size: 0.875rem;
        }

        /* Classification summary */
        section.classification-summary {
            background: var(--color-surface);
            border: 2px solid var(--color-border);
            padding: 1.5rem 2rem;
            border-radius: 8px;
            margin-bottom: 2rem;
        }
        section.classification-summary h2 {
            font-size: 1.375rem;
            border-bottom: 2px solid var(--color-border);
            padding-bottom: 0.4rem;
            margin-bottom: 0.75rem;
        }
        section.classification-summary h3 {
            font-size: 1.0625rem;
            margin-top: 1rem;
            margin-bottom: 0.25rem;
        }
        section.classification-summary ul {
            margin-left: 1.25rem;
            margin-bottom: 0.5rem;
        }
        section.classification-summary li {
            margin-bottom: 0.35rem;
        }
        .cls-breakdown {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin-bottom: 0.75rem;
        }
        .cls-pill {
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            color: white;
            white-space: nowrap;
        }

        @media (max-width: 768px) {
            body { padding: 1rem 0.5rem; }
            .header, main { padding: 1.5rem; }
            .header h1 { font-size: 1.5rem; }
        }

        @media print {
            body { background: white; }
            .header, main { box-shadow: none; }
            article.issue { break-inside: avoid; }
            details.scenario-block > summary::before { content: ""; }
            details.scenario-block:not([open]) > summary { background: transparent; }
            details.scenario-block .scenario-body-inner { display: block !important; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>Test Report Vibes</h1>
            <div class="meta">
                <p><strong>Generated:</strong> {{ metadata.timestamp }}</p>
            </div>

            <div class="stats-dashboard">
                <div class="stats-summary-row">
                    <div>
                        <span class="big-number">{{ stats.total_features }}</span>
                        <span class="big-label"> features</span>
                    </div>
                </div>

                <div class="pct-bar-container">
                    <div class="pct-bar">
                        {% if stats.passed_pct > 0 %}
                        <div class="segment passed" style="width:{{ stats.passed_pct }}%;" title="Passed: {{ stats.passed_pct }}%"></div>
                        {% endif %}
                        {% if stats.failed_pct > 0 %}
                        <div class="segment failed" style="width:{{ stats.failed_pct }}%;" title="Failed: {{ stats.failed_pct }}%"></div>
                        {% endif %}
                        {% if stats.skipped_pct > 0 %}
                        <div class="segment skipped" style="width:{{ stats.skipped_pct }}%;" title="Skipped: {{ stats.skipped_pct }}%"></div>
                        {% endif %}
                    </div>
                    <div class="pct-legend">
                        <span class="l-passed">Passed {{ stats.passed_features }} ({{ stats.passed_pct }}%)</span>
                        <span class="l-failed">Failed {{ stats.failed_features }} ({{ stats.failed_pct }}%)</span>
                        <span class="l-skipped">Skipped {{ stats.skipped_features }} ({{ stats.skipped_pct }}%)</span>
                    </div>
                </div>
                {{ executive_summary_html | safe }}
            </div>
        </header>

        <main>

            {% if classification_html %}
            {{ classification_html | safe }}
            {% endif %}

            {% if feature_groups %}
            <section class="issues">
                <h2>Failing Features</h2>

                {% for group in feature_groups %}
                <article class="issue" data-feature-index="{{ loop.index0 }}">
                    <div class="feature-header">
                        <h3>{{ group.feature_name }}</h3>
                    </div>

                    <div class="issue-meta">
                        {% if group.feature_uri %}
                        <p><strong>Feature:</strong> <code>{{ group.feature_uri }}</code></p>
                        {% endif %}
                        {% if group.feature_links %}
                        <p><strong>Related:</strong>
                            {% for link in group.feature_links %}
                            <a href="{{ link }}" target="_blank" rel="noopener noreferrer">{{ link }}</a>{{ ", " if not loop.last else "" }}
                            {% endfor %}
                        </p>
                        {% endif %}
                        {% if group.feature_description %}
                        <p><strong>Description:</strong> {{ group.feature_description | format_description | safe }}</p>
                        {% endif %}
                    </div>

                    <button class="toggle-all-scenarios" onclick="toggleAllScenarios({{ loop.index0 }})" title="Show/Hide scenarios">
                        <span class="toggle-icon">▶</span> <span class="toggle-text">Show scenarios</span>
                    </button>
                        
                    <div class="scenarios-container hidden">
                    {% for scenario in group.scenarios %}
                    <details class="scenario-block{% if scenario.failed_steps > 0 or scenario.undefined_steps > 0 or scenario.pending_steps > 0 %} scenario-failed{% endif %}">
                        <summary>
                            <span class="scenario-summary-name">
                                <span class="scenario-keyword">Scenario:</span>{{ scenario.name }}
                            </span>
                        </summary>

                        <div class="scenario-body-inner">
                            {% if scenario.description %}
                            <p>{{ scenario.description | format_description | safe }}</p>
                            {% endif %}

                            <ol class="scenario-steps-list" aria-label="Steps">
                                {% for step in scenario.steps %}
                                <li>
                                    <div class="step-content">
                                        <span class="step-status-icon {{ step.status }}">{{ step.status | status_icon }}</span>
                                        <div class="step-text">
                                            <span class="step-keyword">{{ step.keyword }}</span>{{ step.name }}
                                            {% if step.duration is not none %}
                                            <span class="step-duration">{{ step.duration | format_duration }}</span>
                                            {% endif %}
                                            {% if step.location %}
                                            <span class="step-location">{{ step.location }}</span>
                                            {% endif %}
                                        </div>
                                    </div>
                                    {% if step.error_message %}
                                    <pre class="step-error-detail">{{ step.error_message }}</pre>
                                    {% endif %}
                                </li>
                                {% endfor %}
                            </ol>

                            {% if scenario.screenshots %}
                            <div class="step-embedded-content">
                                {% for shot in scenario.screenshots %}
                                <img src="data:image/png;base64,{{ shot }}" alt="Screenshot">
                                {% endfor %}
                            </div>
                            {% endif %}
                        </div>
                    </details>
                    {% endfor %}
                    </div>
                </article>
                {% endfor %}
            </section>
            {% endif %}
        </main>

        <footer>
            <p>Generated by <strong>test-report-vibes</strong></p>
        </footer>
    </div>

    <script>
        function toggleAllScenarios(featureIndex) {
            const article = document.querySelector(`article.issue[data-feature-index="${featureIndex}"]`);
            const button = article.querySelector('.toggle-all-scenarios');
            const scenariosContainer = article.querySelector('.scenarios-container');
            const scenarioDetails = article.querySelectorAll('details.scenario-block');

            // Toggle visibility of scenarios container
            const isHidden = scenariosContainer.classList.contains('hidden');

            if (isHidden) {
                // Show scenarios and expand only failed details
                scenariosContainer.classList.remove('hidden');
                scenarioDetails.forEach(detail => {
                    detail.open = detail.classList.contains('scenario-failed');
                });
                button.classList.add('expanded');
                button.querySelector('.toggle-icon').textContent = '▼';
                button.querySelector('.toggle-text').textContent = 'Hide scenarios';
            } else {
                // Hide scenarios and collapse all details
                scenariosContainer.classList.add('hidden');
                scenarioDetails.forEach(detail => {
                    detail.open = false;
                });
                button.classList.remove('expanded');
                button.querySelector('.toggle-icon').textContent = '▶';
                button.querySelector('.toggle-text').textContent = 'Show scenarios';
            }
        }
    </script>
</body>
</html>"""
