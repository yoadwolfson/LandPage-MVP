import json
import logging
import sys
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, TypeVar
from jinja2 import Environment, FileSystemLoader, select_autoescape

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schemas.models import (
    ExtractedAppData,
    ContentStrategy,
    LandingPageContent,
    PipelineOutput,
)
try:
    from agent.extractor import extract_app_data
except ModuleNotFoundError:
    from extractor import extract_app_data
try:
    from agent.analyzer import analyze_content_strategy
except ModuleNotFoundError:
    from analyzer import analyze_content_strategy
try:
    from agent.composer import generate_landing_content
except ModuleNotFoundError:
    from composer import generate_landing_content

logger = logging.getLogger(__name__)
T = TypeVar("T")

TEMPLATE_BY_ID = {
    "default": "landing.html.j2",
    "music": "landing_music.html.j2",
    "gaming": "landing_gaming.html.j2",
    "finance": "landing_finance.html.j2",
    "productivity": "landing_productivity.html.j2",
}


class PipelineStageError(Exception):
    """Raised for stage-specific failures with a clear error contract."""

    def __init__(self, stage: str, message: str, details: str | None = None):
        self.stage = stage
        self.message = message
        self.details = details
        super().__init__(f"[{stage}] {message}")


class Pipeline:
    """
    Orchestrates the 3-agent pipeline:
    1. Extractor: Google Play URL → ExtractedAppData
    2. Analyzer: ExtractedAppData → ContentStrategy
    3. Composer: ExtractedAppData + ContentStrategy → LandingPageContent
    """

    def __init__(self, runs_dir: str = "runs", outputs_dir: str = "outputs"):
        self.runs_dir = Path(runs_dir)
        self.outputs_dir = Path(outputs_dir)
        self.templates_dir = PROJECT_ROOT / "templates"
        self.runs_dir.mkdir(exist_ok=True)
        self.outputs_dir.mkdir(exist_ok=True)

        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _run_with_retry(self, fn: Callable[[], T], stage: str, retries: int = 1) -> T:
        """Run a stage function with a single retry for transient issues."""
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return fn()
            except Exception as e:
                last_error = e
                logger.warning(f"{stage} attempt {attempt + 1} failed: {e}")
                if attempt < retries:
                    logger.info(f"Retrying {stage}...")
        raise PipelineStageError(
            stage=stage,
            message=f"{stage} failed after {retries + 1} attempts",
            details=str(last_error) if last_error else None,
        )

    def save_error_artifact(self, run_id: str, stage: str, error: str, details: str | None = None) -> Path:
        run_folder = self.runs_dir / run_id
        run_folder.mkdir(exist_ok=True)
        payload = {
            "run_id": run_id,
            "stage": stage,
            "error": error,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        }
        path = run_folder / "error.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved error artifact: {path}")
        return path

    def generate_run_id(self) -> str:
        """Generate unique run ID from timestamp."""
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        suffix = uuid.uuid4().hex[:6]
        return f"run_{stamp}_{suffix}"

    def save_artifact(self, run_id: str, stage: str, data: dict) -> Path:
        """Save intermediate artifact to runs/{run_id}/ folder."""
        run_folder = self.runs_dir / run_id
        run_folder.mkdir(exist_ok=True)

        artifact_path = run_folder / f"{stage}.json"
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved artifact: {artifact_path}")
        return artifact_path

    async def run_extractor(
        self, google_play_url: str, run_id: str
    ) -> ExtractedAppData:
        """Step 1: Run Extractor Agent."""
        logger.info("=" * 60)
        logger.info("STAGE 1: EXTRACTOR")
        logger.info("=" * 60)

        try:
            extracted_data = self._run_with_retry(
                lambda: extract_app_data(google_play_url),
                stage="extractor",
                retries=1,
            )

            # Graceful defaults for partial extraction.
            if not extracted_data.short_description:
                extracted_data.short_description = "Discover this app on Google Play."
            if not extracted_data.full_description:
                extracted_data.full_description = extracted_data.short_description
            if extracted_data.reviews is None:
                extracted_data.reviews = []
            if extracted_data.screenshots is None:
                extracted_data.screenshots = []

            # Save artifact
            self.save_artifact(run_id, "extracted", extracted_data.model_dump())

            logger.info(f"Extracted: {extracted_data.app_name}")
            logger.info(f"   Rating: {extracted_data.rating}/5")
            logger.info(f"   Installs: {extracted_data.installs}")
            logger.info(f"   Reviews collected: {len(extracted_data.reviews)}")

            return extracted_data

        except PipelineStageError:
            raise
        except Exception as e:
            logger.error(f"Extractor failed: {e}")
            raise PipelineStageError("extractor", "Failed to extract app data", str(e))

    async def run_analyzer(
        self, extracted_data: ExtractedAppData, run_id: str
    ) -> ContentStrategy:
        """Step 2: Run Analyzer Agent."""
        logger.info("\n" + "=" * 60)
        logger.info("STAGE 2: ANALYZER")
        logger.info("=" * 60)

        try:
            strategy = self._run_with_retry(
                lambda: analyze_content_strategy(extracted_data),
                stage="analyzer",
                retries=1,
            )

            self.save_artifact(run_id, "strategy", strategy.model_dump())
            logger.info("Strategy created")
            logger.info(f"   Audience: {strategy.target_audience}")
            logger.info(f"   Tone: {strategy.tone}")
            logger.info(f"   Selected reviews: {len(strategy.selected_reviews)}")
            if strategy.style_guide:
                logger.info(f"   Style bucket: {strategy.style_guide.get('bucket', 'unknown')}")

            return strategy

        except PipelineStageError:
            raise
        except Exception as e:
            logger.error(f"Analyzer failed: {e}")
            raise PipelineStageError("analyzer", "Failed to build content strategy", str(e))

    async def run_composer(
        self,
        extracted_data: ExtractedAppData,
        strategy: ContentStrategy,
        run_id: str,
    ) -> LandingPageContent:
        """Step 3: Run Composer Agent."""
        logger.info("\n" + "=" * 60)
        logger.info("STAGE 3: COMPOSER")
        logger.info("=" * 60)

        try:
            landing_content = self._run_with_retry(
                lambda: generate_landing_content(extracted_data, strategy),
                stage="composer",
                retries=1,
            )

            self.save_artifact(run_id, "landing_content", landing_content.model_dump())
            logger.info("Landing content created")
            logger.info(f"   Hero: {landing_content.hero_headline}")
            logger.info(f"   Benefits: {len(landing_content.benefits)}")
            logger.info(f"   Reviews used: {len(landing_content.social_proof_reviews)}")

            return landing_content

        except PipelineStageError:
            raise
        except Exception as e:
            logger.error(f"Composer failed: {e}")
            raise PipelineStageError("composer", "Failed to compose landing content", str(e))
    def render_html(
        self,
        run_id: str,
        extracted_data: ExtractedAppData,
        strategy: ContentStrategy,
        landing_content: LandingPageContent,
    ) -> Path:
        """Render final landing page HTML to outputs/{run_id}.html."""
        output_html = self.outputs_dir / f"{run_id}.html"

        style = strategy.style_guide or {}
        context = {
            "app": extracted_data,
            "strategy": strategy,
            "content": landing_content,
            "style": style,
            "generated_at": datetime.now().isoformat(),
        }

        template_id = str(style.get("template_id", "default") or "default").strip().lower()
        template_name = TEMPLATE_BY_ID.get(template_id, "landing.html.j2")
        if (self.templates_dir / template_name).exists():
            html = self.jinja_env.get_template(template_name).render(**context)
            logger.info(f"Template selected: {template_name} (id={template_id})")
        else:
            default_template = "landing.html.j2"
            if (self.templates_dir / default_template).exists():
                logger.warning(f"Template not found: {template_name}; using default template")
                html = self.jinja_env.get_template(default_template).render(**context)
            else:
                # Safe fallback if no template file is available.
                html = self._fallback_html(context)

        output_html.write_text(html, encoding="utf-8")
        logger.info(f"Rendered HTML: {output_html}")
        return output_html

    def _fallback_html(self, context: dict) -> str:
        """Minimal fallback HTML to keep pipeline usable without template file."""
        c = context["content"]
        s = context["style"]
        benefits = "".join(
            f"<li><strong>{b.title}</strong>: {b.description}</li>" for b in c.benefits
        )
        reviews = "".join(
            f"<li>\"{r.text}\" - {r.reviewer}</li>" for r in c.social_proof_reviews
        )
        faqs = "".join(
            f"<li><strong>{f.question}</strong><br>{f.answer}</li>" for f in c.faq_items
        )
        screenshots = "".join(
            f"<img src=\"{src}\" alt=\"screenshot\" style=\"max-width:220px;border-radius:10px;margin:6px;\"/>"
            for src in c.screenshots
        )
        return f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{context['app'].app_name}</title>
    <style>
        :root {{
            --primary: {s.get('color_primary', '#4F46E5')};
            --bg: {s.get('color_background', '#F9FAFB')};
            --text: {s.get('color_text', '#111827')};
            --surface: {s.get('color_surface', '#FFFFFF')};
        }}
        body {{ font-family: Arial, sans-serif; margin: 0; background: var(--bg); color: var(--text); }}
        .wrap {{ max-width: 980px; margin: 0 auto; padding: 24px; }}
        .card {{ background: var(--surface); border-radius: 12px; padding: 18px; margin: 14px 0; }}
        .cta {{ display:inline-block; margin-top:10px; padding: 12px 18px; background: var(--primary); color:#fff; text-decoration:none; border-radius:10px; }}
    </style>
</head>
<body>
    <div class=\"wrap\">
        <div class=\"card\">
            <h1>{c.hero_headline}</h1>
            <p>{c.hero_subheadline}</p>
            <a class=\"cta\" href=\"{c.cta_url}\">{c.cta_text}</a>
        </div>
        <div class=\"card\"><h2>Benefits</h2><ul>{benefits}</ul></div>
        <div class=\"card\"><h2>{c.social_proof_headline}</h2><ul>{reviews}</ul></div>
        <div class=\"card\"><h2>Screenshots</h2>{screenshots}</div>
        <div class=\"card\"><h2>FAQ</h2><ul>{faqs}</ul></div>
    </div>
</body>
</html>"""

    async def orchestrate(self, google_play_url: str) -> PipelineOutput:
        """
        Main orchestration function.
        Runs: Extractor → Analyzer → Composer
        Returns complete PipelineOutput.
        """
        run_id = self.generate_run_id()
        logger.info(f"\nStarting pipeline: {run_id}")
        logger.info(f"   URL: {google_play_url}")

        try:
            # Stage 1: Extract
            extracted_data = await self.run_extractor(google_play_url, run_id)

            # Stage 2: Analyze
            strategy = await self.run_analyzer(extracted_data, run_id)

            # Stage 3: Compose
            landing_content = await self.run_composer(
                extracted_data, strategy, run_id
            )

            # Create final output
            run_folder = self.runs_dir / run_id
            output_html = self.render_html(
                run_id=run_id,
                extracted_data=extracted_data,
                strategy=strategy,
                landing_content=landing_content,
            )

            pipeline_output = PipelineOutput(
                run_id=run_id,
                timestamp=datetime.now().isoformat(),
                google_play_url=google_play_url,
                extracted_data=extracted_data,
                strategy=strategy,
                landing_content=landing_content,
                html_file=str(output_html),
                artifacts_folder=str(run_folder),
                status="success",
            )

            # Save complete output
            self.save_artifact(run_id, "pipeline_output", pipeline_output.model_dump())

            logger.info("\n" + "=" * 60)
            logger.info("PIPELINE COMPLETE")
            logger.info("=" * 60)
            logger.info(f"   Run ID: {run_id}")
            logger.info(f"   Artifacts: {run_folder}")
            logger.info(f"   HTML: {output_html}")

            return pipeline_output

        except PipelineStageError as e:
            logger.error(f"\nPIPELINE FAILED at {e.stage}: {e.message}")
            self.save_error_artifact(run_id, e.stage, e.message, e.details)
            raise
        except Exception as e:
            logger.error(f"\nPIPELINE FAILED: {e}")
            self.save_error_artifact(run_id, "pipeline", "Unhandled pipeline failure", str(e))
            raise


def orchestrate_pipeline(google_play_url: str, runs_dir: str = "runs", outputs_dir: str = "outputs") -> PipelineOutput:
    """Simple stage-5 entrypoint: get URL, run extractor->analyzer->composer workflow."""
    pipeline = Pipeline(runs_dir=runs_dir, outputs_dir=outputs_dir)
    import asyncio
    return asyncio.run(pipeline.orchestrate(google_play_url))
