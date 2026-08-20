"""Prompt template loader.

All LLM prompts live as resource files inside this package
(``inflow_core/prompts/``). Use load_prompt(name, **kwargs) to load and
format a prompt.
"""

from pathlib import Path

# Prompts live inside the package itself (path-independent of cwd).
PROMPTS_DIR = Path(__file__).parent
_DIR = PROMPTS_DIR


def load_prompt(name: str, **kwargs: object) -> str:
    """Load *name*.md from the prompts directory and format with *kwargs*.

    Curly-brace literals in the template must be escaped as {{ and }}.
    """
    path = _DIR / f"{name}.md"
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)
