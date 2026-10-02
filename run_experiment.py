#!/usr/bin/env python3
"""Run the first independent Relationship Agent experiment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from relationship_agent.cli import main


if __name__ == "__main__":
    main()
