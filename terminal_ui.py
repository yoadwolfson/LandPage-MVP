#!/usr/bin/env python
"""Modern terminal UI for LandPage landing page generator.

Provides an intuitive interface with clean visual hierarchy, better navigation,
and improved feedback on progress and results.
"""

import os
import sys
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

from agent.orchestrator import orchestrate_pipeline


DEMO_URLS: List[str] = [
    "https://play.google.com/store/apps/details?id=com.govil.mygov",
    "https://play.google.com/store/apps/details?id=com.paypal.android.p2pmobile",
    "https://play.google.com/store/apps/details?id=com.laketrustcreditunion.app",
    "https://play.google.com/store/apps/details?id=com.spotify.music",
    "https://play.google.com/store/apps/details?id=com.emelianov.audio",
    "https://play.google.com/store/apps/details?id=com.nfo.me.android",
]

QUALITY_PRESETS = {
    "fast": {"analysis_model": "gpt-4o-mini", "analysis_max_output_tokens": 900},
    "balanced": {"analysis_model": "gpt-4o-mini", "analysis_max_output_tokens": 1400},
    "best": {"analysis_model": "gpt-4o", "analysis_max_output_tokens": 1800},
}

MODEL_PRESETS = {
    "1": {"label": "Fast (gpt-4o-mini)", "model": "gpt-4o-mini"},
    "2": {"label": "Balanced (gpt-4o-mini)", "model": "gpt-4o-mini"},
    "3": {"label": "Best (gpt-4o)", "model": "gpt-4o"},
}


# ============================================================================
# SETTINGS & CONFIG
# ============================================================================

def _default_settings() -> dict:
    """Initialize default settings."""
    return {
        "quality_mode": "balanced",
        "analysis_model": None,
        "analysis_max_output_tokens": None,
        "open_html": False,
    }


def _apply_quality_mode(settings: dict, mode: str) -> None:
    """Apply a quality preset to settings."""
    settings["quality_mode"] = mode
    preset = QUALITY_PRESETS.get(mode, QUALITY_PRESETS["balanced"])
    settings["analysis_model"] = preset["analysis_model"]
    settings["analysis_max_output_tokens"] = preset["analysis_max_output_tokens"]


def _apply_model_preset(settings: dict, preset_key: str) -> None:
    """Apply a model preset to settings."""
    preset = MODEL_PRESETS.get(preset_key)
    if not preset:
        return
    settings["analysis_model"] = preset["model"]


def _reset_settings_to_defaults(settings: dict) -> None:
    """Reset all settings to factory defaults."""
    defaults = _default_settings()
    settings.update(defaults)


# ============================================================================
# VISUAL SYSTEM (SECTION RENDERING, FORMATTING)
# ============================================================================

def _print_divider(char: str = "=", width: int = 72) -> None:
    """Print a horizontal divider."""
    print(char * width)


def _print_header(title: str) -> None:
    """Print a section header with surrounding whitespace."""
    print()
    print(f"  {title}")
    print(f"  " + "-" * (len(title)))


def _print_config_block(settings: dict) -> None:
    """Print current configuration in a compact block."""
    model = settings["analysis_model"] or "gpt-4o-mini"
    tokens = settings["analysis_max_output_tokens"] or "default"
    auto_open = "on" if settings["open_html"] else "off"

    _print_header("Current Configuration")
    print(f"    Quality mode: {settings['quality_mode'].upper()}")
    print(f"    Analysis model: {model}")
    print(f"    Token budget: {tokens}")
    print(f"    Auto-open HTML: {auto_open}")


# ============================================================================
# MENU NAVIGATION & INPUT VALIDATION
# ============================================================================

def _get_menu_choice(prompt: str = "Choose option: ") -> str:
    """Safely get and validate menu input."""
    choice = input(f"  {prompt}").strip()
    return choice


def _print_menu(title: str, items: dict, show_back: bool = False) -> None:
    """Print a formatted menu with options."""
    _print_header(title)
    for key, label in items.items():
        print(f"    {key}  {label}")
    if show_back:
        print(f"    0  Back")


def _collect_urls_from_input() -> List[str]:
    """Collect and validate URLs from user input."""
    print()
    raw = _get_menu_choice("Paste one or more URLs (comma-separated): ")
    if not raw:
        print("  (No URLs provided)")
        return []

    urls = [u.strip() for u in raw.split(",") if u.strip()]
    valid_urls = [u for u in urls if u.startswith("https://play.google.com")]

    if len(valid_urls) != len(urls):
        invalid_count = len(urls) - len(valid_urls)
        print(f"  ⚠ Skipped {invalid_count} invalid URL(s)")

    return valid_urls


# ============================================================================
# PIPELINE EXECUTION & PROGRESS
# ============================================================================

def _run_urls(
    urls: List[str],
    open_html: bool = False,
    analysis_model: str | None = None,
    analysis_max_output_tokens: int | None = None,
) -> Tuple[int, int]:
    """
    Run the pipeline for multiple URLs. Returns (success_count, failure_count).
    """
    total = len(urls)
    success = 0
    failed = 0

    print()
    print(f"  Processing {total} app(s)...")
    _print_divider()

    for i, url in enumerate(urls, start=1):
        try:
            result = orchestrate_pipeline(
                url,
                analysis_model=analysis_model,
                analysis_max_output_tokens=analysis_max_output_tokens,
            )

            style = result.strategy.style_guide.get("bucket", "default") if result.strategy.style_guide else "default"
            success += 1

            # Progress line with app info
            print(f"  [{i}/{total}] {result.extracted_data.app_name}")
            print(f"         Style: {style} | ID: {result.run_id}")
            print(f"         HTML: {result.html_file}")

            if open_html:
                os.startfile(result.html_file)
                print(f"         ✓ Opened in browser")

        except Exception as exc:
            failed += 1
            print(f"  [{i}/{total}] FAILED")
            print(f"         Error: {str(exc)[:60]}")

    _print_divider()
    _print_summary(total, success, failed)

    return success, failed


def _print_summary(total: int, success: int, failed: int) -> None:
    """Print a clean summary of run results."""
    print()
    _print_header("Run Summary")
    print(f"    Total apps: {total}")
    print(f"    Successful: {success}")
    print(f"    Failed: {failed}")
    if success > 0:
        print(f"    Success rate: {100 * success // total}%")


# ============================================================================
# OUTPUT MANAGEMENT
# ============================================================================

def _open_latest_outputs(limit: int = 6) -> None:
    """Open the latest HTML outputs in the browser."""
    outputs_dir = Path("outputs")
    if not outputs_dir.exists():
        print("  No output folder found yet.")
        return

    files = sorted(
        outputs_dir.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True
    )[:limit]

    if not files:
        print("  No HTML outputs found yet.")
        return

    print()
    print(f"  Opening {len(files)} recent output(s)...")
    for path in reversed(files):
        os.startfile(str(path))
        print(f"    ✓ {path.name}")


# ============================================================================
# SETTINGS MENU (PHASE 5)
# ============================================================================

def _menu_settings(settings: dict) -> None:
    """Settings submenu for quality, model, token budget, and toggles."""
    while True:
        _print_config_block(settings)

        _print_menu(
            "Settings",
            {
                "1": "Quality mode (fast / balanced / best)",
                "2": "Analysis model",
                "3": "Token budget",
                "4": "Auto-open HTML",
                "5": "Reset to defaults",
            },
            show_back=True,
        )

        choice = _get_menu_choice()

        if choice == "0":
            return

        if choice == "1":
            _menu_quality_mode(settings)
            continue

        if choice == "2":
            _menu_analysis_model(settings)
            continue

        if choice == "3":
            _menu_token_budget(settings)
            continue

        if choice == "4":
            settings["open_html"] = not settings["open_html"]
            state = "on" if settings["open_html"] else "off"
            print(f"  ✓ Auto-open HTML is now {state}")
            input("  Press Enter to continue...")
            continue

        if choice == "5":
            confirm = _get_menu_choice("Reset settings to defaults? (y/n): ")
            if confirm.lower() == "y":
                _reset_settings_to_defaults(settings)
                print("  ✓ Settings reset to defaults")
                input("  Press Enter to continue...")
            continue

        print("  Invalid option. Try again.")


def _menu_quality_mode(settings: dict) -> None:
    """Submenu for setting quality mode."""
    _print_menu(
        "Quality Mode",
        {"1": "Fast (gpt-4o-mini, 900 tokens)", "2": "Balanced (gpt-4o-mini, 1400 tokens)", "3": "Best (gpt-4o, 1800 tokens)"},
        show_back=True,
    )

    choice = _get_menu_choice()

    if choice == "0":
        return
    if choice in ("1", "2", "3"):
        mode_map = {"1": "fast", "2": "balanced", "3": "best"}
        mode = mode_map[choice]
        _apply_quality_mode(settings, mode)
        print(f"  ✓ Quality mode set to {mode.upper()}")
        input("  Press Enter to continue...")
        return

    print("  Invalid option.")


def _menu_analysis_model(settings: dict) -> None:
    """Submenu for setting analysis model."""
    _print_menu(
        "Analysis Model",
        {
            "1": "Fast (gpt-4o-mini)",
            "2": "Balanced (gpt-4o-mini)",
            "3": "Best (gpt-4o)",
            "4": "Custom model name",
        },
        show_back=True,
    )

    choice = _get_menu_choice()

    if choice == "0":
        return
    if choice in MODEL_PRESETS:
        preset = MODEL_PRESETS[choice]
        settings["analysis_model"] = preset["model"]
        print(f"  ✓ Model set to {preset['model']}")
        input("  Press Enter to continue...")
        return
    if choice == "4":
        model_name = _get_menu_choice("Custom model name: ")
        if model_name:
            settings["analysis_model"] = model_name
            print(f"  ✓ Model set to {model_name}")
        else:
            print("  (Model name cannot be empty)")
        input("  Press Enter to continue...")
        return

    print("  Invalid option.")


def _menu_token_budget(settings: dict) -> None:
    """Submenu for setting token budget."""
    print()
    print("  Current token budget:", settings["analysis_max_output_tokens"] or "default")
    token_input = _get_menu_choice("New token budget (or empty for default): ")

    if not token_input:
        settings["analysis_max_output_tokens"] = None
        print("  ✓ Token budget reset to default")
    else:
        try:
            tokens = int(token_input)
            settings["analysis_max_output_tokens"] = tokens
            print(f"  ✓ Token budget set to {tokens}")
        except ValueError:
            print("  Invalid number. Token budget unchanged.")

    input("  Press Enter to continue...")


def _confirm_action(prompt: str = "Proceed? (y/n/b to go back): ") -> str:
    """
    Get confirmation from user with back option.
    Returns: 'y' for yes, 'n' for no, 'b' for back to main menu
    """
    response = _get_menu_choice(prompt).strip().lower()
    return response if response in ("y", "n", "b") else _confirm_action("Please enter y, n, or b: ")


# ============================================================================

def main() -> None:
    """Main terminal UI loop with redesigned information architecture."""
    load_dotenv()
    settings = _default_settings()

    while True:
        # Clear previous context and show current state
        print("\n" * 2)
        _print_divider(char="=", width=72)
        print()
        print("  LANDPAGE - AI-POWERED LANDING PAGE GENERATOR")
        print()
        _print_config_block(settings)
        print()

        # Main menu with minimal, clear options
        _print_menu(
            "Main Menu",
            {
                "1": "Generate one landing page",
                "2": "Generate multiple landing pages",
                "3": "Run 6-app demo",
                "4": "Open recent outputs",
                "5": "Settings",
                "0": "Exit",
            },
        )

        choice = _get_menu_choice()

        # Option 1: Single URL with auto-open enabled
        if choice == "1":
            print()
            url = _get_menu_choice("Google Play app URL: ")
            if not url:
                print("  (No URL provided)")
                input("  Press Enter to continue...")
                continue
            if not url.startswith("https://play.google.com"):
                print("  Invalid URL. Must be a Google Play store link.")
                input("  Press Enter to continue...")
                continue

            # Confirmation with back option
            print()
            print(f"  Generating landing page for:")
            print(f"  {url}")
            confirm = _confirm_action("  Proceed? (y/n/b to go back): ")
            
            if confirm == "b":
                print("  (Back to main menu)")
                continue
            if confirm != "y":
                print("  (Cancelled)")
                input("  Press Enter to continue...")
                continue

            success, _ = _run_urls(
                [url],
                open_html=True,
                analysis_model=settings["analysis_model"],
                analysis_max_output_tokens=settings["analysis_max_output_tokens"],
            )
            input("  Press Enter to continue...")
            continue

        # Option 2: Multiple URLs
        if choice == "2":
            urls = _collect_urls_from_input()
            if not urls:
                print("  No valid URLs provided.")
                input("  Press Enter to continue...")
                continue

            # Confirmation with back option
            print()
            print(f"  Will generate {len(urls)} landing page(s):")
            for i, url in enumerate(urls, 1):
                print(f"    {i}. {url[:50]}...")
            confirm = _confirm_action("  Proceed? (y/n/b to go back): ")
            
            if confirm == "b":
                print("  (Back to main menu)")
                continue
            if confirm != "y":
                print("  (Cancelled)")
                input("  Press Enter to continue...")
                continue

            _run_urls(
                urls,
                open_html=settings["open_html"],
                analysis_model=settings["analysis_model"],
                analysis_max_output_tokens=settings["analysis_max_output_tokens"],
            )
            input("  Press Enter to continue...")
            continue

        # Option 3: Demo set
        if choice == "3":
            print()
            print(f"  Running demo with {len(DEMO_URLS)} apps...")
            confirm = _confirm_action("  Proceed? (y/n/b to go back): ")
            
            if confirm == "b":
                print("  (Back to main menu)")
                continue
            if confirm != "y":
                print("  (Cancelled)")
                input("  Press Enter to continue...")
                continue

            _run_urls(
                DEMO_URLS,
                open_html=settings["open_html"],
                analysis_model=settings["analysis_model"],
                analysis_max_output_tokens=settings["analysis_max_output_tokens"],
            )
            input("  Press Enter to continue...")
            continue

        # Option 4: Open recent outputs
        if choice == "4":
            _open_latest_outputs()
            input("  Press Enter to continue...")
            continue

        # Option 5: Settings
        if choice == "5":
            _menu_settings(settings)
            continue

        # Option 0: Exit
        if choice == "0":
            print()
            print("  Thank you for using LandPage. Goodbye!")
            print()
            return

        # Invalid choice
        print("  Invalid option. Choose 0, 1, 2, 3, 4, or 5.")
        input("  Press Enter to continue...")





if __name__ == "__main__":
    main()

