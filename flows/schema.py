"""Workflow data model: WorkflowStep and WorkflowModel."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WorkflowStep:
    """A single step in a workflow."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    action: str = ""  # navigate, click, input, wait, screenshot, ocr, extract, if, loop, data_driven
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "action": self.action,
            "params": self.params,
            "description": self.description,
            "enabled": self.enabled,
        }
        # Recursively serialize nested steps (for if/loop)
        if "thenSteps" in d["params"]:
            d["params"]["thenSteps"] = [
                s.to_dict() if isinstance(s, WorkflowStep) else s
                for s in d["params"]["thenSteps"]
            ]
        if "elseSteps" in d["params"]:
            d["params"]["elseSteps"] = [
                s.to_dict() if isinstance(s, WorkflowStep) else s
                for s in d["params"]["elseSteps"]
            ]
        if "bodySteps" in d["params"]:
            d["params"]["bodySteps"] = [
                s.to_dict() if isinstance(s, WorkflowStep) else s
                for s in d["params"]["bodySteps"]
            ]
        if "steps" in d["params"]:
            d["params"]["steps"] = [
                s.to_dict() if isinstance(s, WorkflowStep) else s
                for s in d["params"]["steps"]
            ]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowStep":
        params = data.get("params", {})
        # Recursively deserialize nested steps
        for key in ("thenSteps", "elseSteps", "bodySteps", "steps"):
            if key in params:
                params[key] = [cls.from_dict(s) for s in params[key]]
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            action=data.get("action", ""),
            params=params,
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
        )


@dataclass
class WorkflowModel:
    """A complete workflow containing an ordered list of steps."""

    name: str = "Untitled"
    version: str = "1.0"
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    modified: str = field(default_factory=lambda: datetime.now().isoformat())
    variables: dict[str, Any] = field(default_factory=dict)
    steps: list[WorkflowStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "created": self.created,
            "modified": datetime.now().isoformat(),
            "variables": self.variables,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowModel":
        return cls(
            name=data.get("name", "Untitled"),
            version=data.get("version", "1.0"),
            created=data.get("created", datetime.now().isoformat()),
            modified=data.get("modified", datetime.now().isoformat()),
            variables=data.get("variables", {}),
            steps=[WorkflowStep.from_dict(s) for s in data.get("steps", [])],
        )

    def save(self, filepath: str) -> None:
        """Save workflow to a JSON file."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, filepath: str) -> "WorkflowModel":
        """Load workflow from a JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def add_step(self, step: WorkflowStep) -> None:
        self.steps.append(step)

    def remove_step(self, index: int) -> None:
        if 0 <= index < len(self.steps):
            self.steps.pop(index)

    def move_step(self, from_idx: int, to_idx: int) -> None:
        if 0 <= from_idx < len(self.steps) and 0 <= to_idx < len(self.steps):
            step = self.steps.pop(from_idx)
            self.steps.insert(to_idx, step)
