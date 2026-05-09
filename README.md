# Test Report Vibes

**Deterministic HTML summaries of Cucumber test reports.**

`test-report-vibes` turns Cucumber JSON output into a focused, self-contained HTML report so you can quickly review what failed and why.

## What it does

- Filters report data to failing, undefined, and pending steps
- Keeps scenario context (all steps), plus optional screenshots from embeddings/hooks
- Groups issues by feature and includes pass/fail stats across the full run
- Builds a deterministic executive summary (no external AI/LLM calls)
- Optionally classifies failing scenarios by tags such as `@new_issue` and `@flaky`

## Installation

From source:

```bash
git clone https://github.com/srbarrios/test-report-vibes.git
cd test-report-vibes
pip install -e .
```

## Quick start

```bash
test-report-vibes examples/sample_report_with_classifiers.json
```

This creates `examples/sample_report_with_classifiers.html`.

## CLI usage

```text
test-report-vibes [OPTIONS] INPUT_FILE

Arguments:
  INPUT_FILE              Path to Cucumber JSON report [required]

Options:
  -o, --output PATH       Output HTML file path (default: INPUT_FILE.html)
  -v, --verbose           Verbose output with detailed exception trace on errors
  --no-classify           Skip the tag-based classification section
  --help                  Show this message and exit
```

Examples:

```bash
# Default output path: INPUT_FILE.html
test-report-vibes cucumber-report.json

# Custom output file
test-report-vibes cucumber-report.json -o report-summary.html

# Disable tag-based classification section
test-report-vibes cucumber-report.json --no-classify

# Run as module
python -m test_report_vibes cucumber-report.json
```

## Input format

The tool expects standard Cucumber JSON (root array of features). At minimum, each feature should include:

- `uri`, `id`, `name`, `keyword`, `elements`

Steps support these statuses:

- `passed`, `failed`, `skipped`, `pending`, `undefined`

Screenshots are supported through base64 embeddings with image mime types (for example `image/png`) on steps and hooks.

## Output report highlights

Generated HTML includes:

- Overall run dashboard (passed/failed/skipped feature percentages)
- Executive summary cards such as:
  - Most impacted features
  - Recurring normalized error patterns
  - Top error types
  - Framework gaps (undefined/pending steps)
  - Slowest failing scenarios and steps
- Failing features with collapsible scenario details
- Full step context including status, duration, location, and error text
- Embedded screenshots when present
- Optional "Classified features" section from tag-based mapping

## Tag-based classification

When classification is enabled (default), statuses are derived from tags in this priority order:

- `@new_issue` -> `New and reported`
- `@under_debugging` -> `Debugging`
- `@bug_reported` -> `Bug reported`
- `@test_issue` -> `Test Framework issue`
- `@flaky` -> `Flaky Test`
- no match -> `Not reported`

## Development

Install dev dependencies:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Format and lint:

```bash
black src/
ruff check src/
```

## License

This project is licensed under the MIT License. See `LICENSE` for details.

