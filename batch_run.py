import os
from pathlib import Path

import click
from dotenv import load_dotenv

from agent.orchestrator import orchestrate_pipeline


load_dotenv()


def _read_urls_from_file(file_path: str) -> list[str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"URL file not found: {file_path}")

    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        urls.append(value)
    return urls


@click.command()
@click.option("--url", "urls", multiple=True, help="Google Play URL to test. Use multiple times for multiple apps.")
@click.option("--file", "urls_file", type=click.Path(exists=True, dir_okay=False, path_type=str), help="Text file with one Google Play URL per line.")
@click.option("--open-html", is_flag=True, help="Open each generated HTML file after it is created.")
def main(urls: tuple[str, ...], urls_file: str | None, open_html: bool):
    """Run the pipeline for multiple apps and compare styles across app categories."""
    combined_urls: list[str] = list(urls)
    if urls_file:
        combined_urls.extend(_read_urls_from_file(urls_file))

    if not combined_urls:
        raise click.UsageError("Provide at least one --url or a --file with URLs.")

    click.echo(f"Testing {len(combined_urls)} app(s)...")
    click.echo("=" * 70)

    for index, url in enumerate(combined_urls, start=1):
        click.echo(f"\n[{index}/{len(combined_urls)}] {url}")
        try:
            result = orchestrate_pipeline(url)
            style_bucket = result.strategy.style_guide.get("bucket", "default") if result.strategy.style_guide else "default"
            click.echo(f"  Run ID: {result.run_id}")
            click.echo(f"  App: {result.extracted_data.app_name}")
            click.echo(f"  Style: {style_bucket}")
            click.echo(f"  Rating: {result.extracted_data.rating}")
            click.echo(f"  Installs: {result.extracted_data.installs}")
            click.echo(f"  Reviews used: {len(result.landing_content.social_proof_reviews)}")
            click.echo(f"  HTML: {result.html_file}")

            if open_html:
                os.startfile(result.html_file)

        except Exception as exc:
            click.echo(f"  FAILED: {exc}")

    click.echo("\nDone.")


if __name__ == "__main__":
    main()