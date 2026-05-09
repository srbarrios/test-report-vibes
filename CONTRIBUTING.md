# Contributing to Test Report Vibes

Thanks for your interest in improving `test-report-vibes`.

## Development setup

```bash
git clone https://github.com/srbarrios/test-report-vibes.git
cd test-report-vibes
pip install -e ".[dev]"
```

## Run checks locally

```bash
pytest
black src/ tests/
ruff check src/ tests/
```

## Pull request guidelines

- Keep changes focused and small when possible.
- Add or update tests for bug fixes and new behavior.
- Keep CLI behavior backward compatible unless the PR clearly documents a breaking change.
- Update `README.md` when user-facing behavior changes.

## Commit messages

Use clear, imperative messages (for example: `Add support for pending step summaries`).

## Reporting bugs

Please include:

- Python version
- The command you ran
- A minimal Cucumber JSON sample that reproduces the issue
- The stack trace (use `-v` for verbose errors)

