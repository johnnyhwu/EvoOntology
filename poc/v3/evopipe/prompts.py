"""Prompt files live in evopipe/prompts/*.md; ``{{name}}`` placeholders are substituted verbatim."""
import os
import re

from . import config

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def render(name: str, **values: str) -> str:
    text = open(os.path.join(PROMPT_DIR, name), encoding="utf-8").read()
    missing = set(re.findall(r"\{\{(\w+)\}\}", text)) - set(values)
    if missing:
        raise KeyError("prompt %s needs %s" % (name, sorted(missing)))
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, str(value))
    return text


def read_repo_text(path: str) -> str:
    """Repo skill / reference documents are passed to the LLM verbatim so behaviour follows the repo's own rules."""
    return open(path, encoding="utf-8").read()


def section(markdown: str, start: str, end: str = None) -> str:
    """Slice ``markdown`` from the line starting with ``start`` up to (not including) the line starting with ``end``."""
    lines = markdown.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith(start))
    last = len(lines)
    if end is not None:
        last = next(i for i, l in enumerate(lines) if i > first and l.startswith(end))
    return "\n".join(lines[first:last]).strip()
