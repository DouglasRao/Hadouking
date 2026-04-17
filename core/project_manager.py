"""
Project directory management (Hadouking).
Structure: Projects/Project_XX
"""

import os
import re
from pathlib import Path

_MODULE_ROOT = Path(__file__).resolve().parent.parent


class ProjectManager:
    def __init__(self, base_dir: str = "Projects"):
        p = Path(base_dir)
        # Resolve relative paths against the project root, not the current working directory.
        if not p.is_absolute():
            p = _MODULE_ROOT / p
        self.base_dir = p
        self.current_project_dir = None

    def ensure_base_dir(self):
        """Ensure the base Projects directory exists."""
        if not self.base_dir.exists():
            self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_next_project_number(self) -> int:
        """Scan existing projects and determine the next project number."""
        self.ensure_base_dir()

        max_num = 0
        pattern = re.compile(r"Project_(\d+)")

        for entry in self.base_dir.iterdir():
            if entry.is_dir():
                match = pattern.match(entry.name)
                if match:
                    num = int(match.group(1))
                    if num > max_num:
                        max_num = num

        return max_num + 1

    def create_new_project(self) -> str:
        """Create a new project directory (e.g., Project_01) and return its path."""
        next_num = self.get_next_project_number()
        project_name = f"Project_{next_num:02d}"
        self.current_project_dir = self.base_dir / project_name

        self.current_project_dir.mkdir(parents=True, exist_ok=True)
        return str(self.current_project_dir.absolute())

    def get_current_project_dir(self) -> str:
        """Return the current project directory path."""
        if not self.current_project_dir:
            return self.create_new_project()
        return str(self.current_project_dir.absolute())
