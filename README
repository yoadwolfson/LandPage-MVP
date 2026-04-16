# LandPage MVP

LandPage MVP turns a Google Play app URL into a polished landing page. It is built as a small 3-agent pipeline and can be run manually or through a simple terminal UI.

## How To Use

### Manual Run

Use this when you want to generate a single landing page from one app URL.

```bash
python run.py "https://play.google.com/store/apps/details?id=com.example.app"
```

### Terminal UI

Use this when you want a guided menu or a demo batch.

```bash
python terminal_ui.py
```

In the menu:
- `1` runs one app URL
- `2` runs multiple URLs you paste in
- `3` runs the demo set
- `4` opens the latest HTML outputs
- `5` cleanup mode (clear `runs/` and `outputs/` for fresh testing)

## What Happens In The Pipeline

1. **Extractor** pulls app data from Google Play, including name, description, screenshots, installs, rating, and reviews.
2. **Analyzer** reads the extracted data and uses the analyzer prompt plus OpenAI to choose the angle, benefits, layout, and review strategy.
3. **Composer** turns the strategy into final landing-page content. It loads the composer prompt, then builds the hero, benefits, proof, FAQ, and CTA copy.
4. **Renderer** applies the Jinja2 template and writes the final HTML page.

## Main Features

- Terminal UI for single URL, multi URL, and demo runs.
- Style-aware templates (music, gaming, finance, productivity, default).
- Improved review filtering for marketing quality:
  - Blocks complaint patterns like `annoying`, and `deleted`.
  - Keeps social proof focused on clearly positive reviews.

## Outputs

Each run creates:

- `outputs/{run_id}.html` for the rendered landing page
- `runs/{run_id}/extracted.json`
- `runs/{run_id}/strategy.json`
- `runs/{run_id}/landing_content.json`
- `runs/{run_id}/pipeline_output.json`

## Notes

- The analyzer prompt is actively used in the OpenAI strategy step.
- The composer prompt is loaded by the composer stage, and the extractor works directly from Google Play data.
- Generated folders such as `runs/` and `outputs/` can be cleaned when you want a fresh workspace.
