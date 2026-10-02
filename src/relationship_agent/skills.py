"""Versioned stage instructions and JSON contracts used by the harness.

These are local workflow skills, not Codex SKILL.md plugins.
"""
from .schemas import SCHEMAS, INSTRUCTIONS
SKILL_VERSION = "2"
SKILLS = {name: {"instructions": INSTRUCTIONS[name], "schema": schema} for name, schema in SCHEMAS.items()}
