# LandPage MVP - Short Execution Plan

## Goal (End-to-End)
Build a CLI Agent that:
1. Accepts Google Play URL as command-line argument
2. Runs 3 sub-agents sequentially using Copilot SDK
3. Outputs mobile landing page + JSON artifacts to files

Usage: `python agent.py https://play.google.com/store/apps/details?id=...`

Output landing page includes:
- Hero
- Benefits/features
- Social proof (rating/installs/reviews)
- Screenshot gallery
- FAQ
- Main CTA: Install on Google Play

## Stack
- Python CLI with Click or argparse
- Copilot SDK (if available) or OpenAI API for LLM calls
- Playwright + BeautifulSoup (web scraping)
- Pydantic (schema validation)
- Jinja2 (HTML template rendering)
- Local files (runs/, outputs/) for results storage

## 0) CLI Setup (15-20 min)
1. Create folders: agent/, schemas/, templates/, outputs/, runs/
2. Create requirements.txt with: click, pydantic, playwright, beautifulsoup4, jinja2, python-dotenv, openai
3. Create main entry: agent/main.py with Click CLI
4. Setup argument: google_play_url (required positional argument)
5. Setup .env file with OPENAI_API_KEY
6. Create simple CLI help text

Done when:
- `python agent.py --help` shows proper options
- `python agent.py https://...` starts execution (even if incomplete)

## 1) Define Contracts First (25-35 min)
1. Create Pydantic models:
   - ExtractedAppData
   - ContentStrategy
   - LandingPageContent
   - PipelineOutput (combines all results)
2. Add strict required fields and safe defaults
3. Create sample JSON files for testing

Done when:
- You can instantiate each model from sample JSON

## 2) Build Extractor Agent (45-60 min)
1. Input: google_play_url
2. Extract:
- app title, short/full description
- icon URL
- screenshots
- rating
- installs
- reviews (best effort)
3. Add fallback parsing if selector fails
4. Return validated ExtractedAppData

Done when:
- One real app URL returns usable JSON

## 3) Build Analyzer Agent (30-40 min)
1. Input: ExtractedAppData
2. Prompt model to decide:
- target angle
- top benefits
- selected high-signal review snippets (prefer rating >= 4.5)
- FAQ topics
3. Return validated ContentStrategy JSON

Done when:
- Output is structured and concise (no long paragraphs)

## 4) Build Composer Agent (30-40 min)
1. Input: ExtractedAppData + ContentStrategy
2. Generate final LandingPageContent:
- hero headline/subheadline
- benefit cards
- social proof section
- FAQ list
- CTA text + target URL (Google Play)
3. Validate with Pydantic

Done when:
- JSON can directly render a page with no manual edits

## 5) Build Orchestrator Function (30-40 min)
1. Create agent/orchestrator.py
2. Main function orchestrate_pipeline(google_play_url):
   - extractor → analyzer → composer (in sequence)
3. Save stage artifacts in runs/{run_id}/stage-{name}.json
4. Render HTML to outputs/{run_id}.html
5. Return PipelineOutput with all results
6. Wire orchestrator to Click CLI main entry

Done when:
- One CLI call produces full HTML + artifacts

## 6) Build Landing Template (40-60 min)
1. Create responsive Jinja2 template sections:
- Hero
- Benefits
- Social proof
- Screenshots
- FAQ
- Final CTA
2. Keep layout clean and readable on mobile

Done when:
- Opened HTML looks complete and coherent on phone width

## 7) Reliability Pass (25-35 min)
1. Handle missing fields (no reviews, no installs, few screenshots)
2. Add retry for LLM calls (1 retry enough for MVP)
3. Add clear error message per stage

Done when:
- Pipeline fails gracefully and still outputs useful page when partial data exists

## 8) Demo Prep (15-20 min)
1. Test CLI directly:
```bash
python agent.py https://play.google.com/store/apps/details?id=com.example.app
```
2. Verify outputs in outputs/ and runs/ folders
3. Save screenshots of:
   - CLI command + console output
   - Generated HTML page (open in browser)
   - JSON artifacts (extracted.json, strategy.json)
4. Write short README with usage instructions

Done when:
- You can generate a full landing page in under 1 minute per URL

## Stretch (Only if Time Left)
- Add caching by URL hash
- Add language toggle (EN/HE)
- Add simple score report (why these benefits/reviews were picked)

## Minimum Submission Checklist
- Working CLI entry point (`python agent.py [URL]`)
- 3 sub-agents running sequentially (extractor → analyzer → composer)
- Structured JSON artifacts saved per stage
- One generated mobile-friendly landing page (HTML)
- README with architecture + setup + usage instructions
- Example output folder with sample run
