"""Prompt template loader.

All LLM prompts live as .md files under ``backend/prompts/``.
Use load_prompt(name, **kwargs) to load and format a prompt.
"""

from pathlib import Path

# Prompts directory is at backend/prompts/ (sibling of app/)
_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(name: str, **kwargs: object) -> str:
    """Load *name*.md from the prompts directory and format with *kwargs*.

    Curly-brace literals in the template must be escaped as {{ and }}.
    """
    path = _DIR / f"{name}.md"
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)
