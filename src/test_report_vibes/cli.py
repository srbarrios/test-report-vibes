"""Command-line interface for test-report-vibes (deterministic)."""

import click
from pathlib import Path
from datetime import datetime
from rich.console import Console

from .parser import parse_cucumber_json
from .filter import filter_issues, calculate_summary_stats, group_issues_by_feature
from .html_generator import generate_html_report
from .classifier import classify_features, build_classification_summary_html


@click.command()
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output HTML file path (default: INPUT_FILE.html)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose output with detailed error messages",
)
@click.option(
    "--no-classify",
    is_flag=True,
    help="Skip the tag-based classification section in the report.",
)
def main(
    input_file: Path,
    output: Path,
    verbose: bool,
    no_classify: bool,
):
    """Generate a deterministic HTML summary from a Cucumber JSON report.

    \b
    Examples:
        test-report-vibes cucumber-report.json
        test-report-vibes cucumber-report.json -o summary.html
        test-report-vibes cucumber-report.json --no-classify
    """
    console = Console()

    if output is None:
        output = input_file.with_suffix(".html")

    try:
        # Step 1: Parse Cucumber JSON
        console.print("[cyan]📄 Parsing Cucumber report...[/cyan]")
        features = parse_cucumber_json(str(input_file))
        console.print(f"[green]✓[/green] Parsed {len(features)} features")

        # Step 2: Filter issues
        console.print("[cyan]🔍 Filtering issues...[/cyan]")
        issues = filter_issues(features)
        stats = calculate_summary_stats(features)

        if not issues:
            console.print(
                "[green]✅ No issues found! All tests passing or skipped.[/green]"
            )
            console.print(
                f"[dim]Total: {stats['total_scenarios']} scenarios, "
                f"{stats['total_steps']} steps[/dim]"
            )

        else:
            console.print(
                f"[yellow]⚠ Found {len(issues)} issues to analyze[/yellow]"
            )
            console.print(
                f"[dim]  • Failed steps: {stats['failed_steps']}[/dim]\n"
                f"[dim]  • Undefined steps: {stats['undefined_steps']}[/dim]\n"
                f"[dim]  • Pending steps: {stats['pending_steps']}[/dim]"
            )

        # Step 3: Group issues by feature (deterministic)
        feature_groups = group_issues_by_feature(issues, features)
        console.print(
            f"[cyan]🧩 Grouped failures into {len(feature_groups)} feature(s)[/cyan]"
        )

        # Step 4: Optionally classify issues by tags (deterministic)
        classification_html = ""
        if not no_classify:
            console.print("[cyan]📋 Classifying issues by tags...[/cyan]")
            classification = classify_features(feature_groups)
            classification_html = build_classification_summary_html(classification)
            console.print(
                f"[green]✓[/green] Classified {classification['total_failed_features']} "
                f"feature(s) with {len(classification['status_counts'])} status(es)"
            )

        # Step 5: Render HTML
        console.print("[cyan]📝 Creating HTML report...[/cyan]")

        metadata = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "input_file": str(input_file.name),
        }

        generate_html_report(
            feature_groups=feature_groups,
            stats=stats,
            metadata=metadata,
            output_path=str(output),
            classification_html=classification_html,
        )

        console.print("[green]✅ Report generated successfully![/green]")
        console.print(f"[bold blue]→ {output}[/bold blue]")

    except click.ClickException:
        raise
    except FileNotFoundError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        if verbose:
            console.print_exception()
        raise click.ClickException(str(e))


if __name__ == "__main__":
    main()
