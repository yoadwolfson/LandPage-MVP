import click
import os
import sys
import logging
import asyncio
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from agent.orchestrator import Pipeline, PipelineStageError
except ModuleNotFoundError:
    from orchestrator import Pipeline, PipelineStageError

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('pipeline.log')
    ]
)
logger = logging.getLogger(__name__)


@click.command()
@click.argument('google_play_url')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
def main(google_play_url: str, verbose: bool):
    """
    LandPage MVP Agent
    
    Generates a marketing landing page for a Google Play app.
    
    Usage:
        python agent/main.py https://play.google.com/store/apps/details?id=com.example.app
    
    Output:
        - HTML page: outputs/run_*.html
        - Artifacts: runs/run_*/{extracted,strategy,landing_content,pipeline_output}.json
    """
    
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        click.echo("📋 Verbose mode enabled")
    
    # Validate URL
    if not google_play_url.startswith("https://play.google.com"):
        click.echo("❌ Invalid URL. Must be a Google Play Store link.")
        sys.exit(1)
    
    click.echo(f"\n🚀 Starting LandPage generation")
    click.echo(f"   URL: {google_play_url}\n")
    
    # Create pipeline and run
    try:
        pipeline = Pipeline(runs_dir="runs", outputs_dir="outputs")
        
        # Run async pipeline
        result = asyncio.run(pipeline.orchestrate(google_play_url))
        
        # Summary
        click.echo("\n" + "=" * 60)
        click.echo("📋 SUMMARY")
        click.echo("=" * 60)
        click.echo(f"Run ID: {result.run_id}")
        click.echo(f"App: {result.extracted_data.app_name}")
        click.echo(f"Rating: {result.extracted_data.rating}/5.0")
        click.echo(f"Installs: {result.extracted_data.installs}")
        click.echo(f"\nArtifacts saved to: runs/{result.run_id}/")
        click.echo(f"HTML preview: outputs/{result.run_id}.html")
        click.echo("=" * 60 + "\n")
        
        click.echo("✅ Done! Check outputs/ folder for results")
        
    except KeyboardInterrupt:
        click.echo("\n⚠️  Interrupted by user")
        sys.exit(130)
    except PipelineStageError as e:
        click.echo(f"\n❌ Stage failed: {e.stage}")
        click.echo(f"   Reason: {e.message}")
        if e.details:
            click.echo(f"   Details: {e.details}")
        logger.exception("Pipeline stage failure")
        sys.exit(1)
    except Exception as e:
        click.echo(f"\n❌ Error: {e}")
        logger.exception("Pipeline failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
