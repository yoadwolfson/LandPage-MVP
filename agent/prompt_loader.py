from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt file by base name, e.g. 'analyzer' -> prompts/analyzer.prompt.md."""
    path = PROMPTS_DIR / f"{name}.prompt.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
