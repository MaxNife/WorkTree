"""Activity discovery from the built-in package and the configured extra folder."""

from __future__ import annotations

import importlib.util
import inspect
import pkgutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import activities as activities_package
from app.domain.activity import Activity
from app.logging_setup import get_logger


class ActivitySpec(dict[str, Any]):
    """Plain JSON-serialisable description for the API and the Studio palette."""


class ActivityRegistry:
    def __init__(self, extra_folder: Path | None = None) -> None:
        self.extra_folder = extra_folder
        self._activities: dict[str, Activity[Any]] = {}
        self._sources: dict[str, str] = {}

    def discover(self) -> ActivityRegistry:
        self._activities.clear()
        self._sources.clear()
        for module in _iter_modules(activities_package.__path__, "activities"):
            if module.name.rsplit(".", 1)[-1].startswith("_"):
                continue
            self._load_module(module.name, source="builtin", import_path=module.name)
        if self.extra_folder is not None and self.extra_folder.exists():
            for path in sorted(self.extra_folder.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                module_name = f"uaf_extra_{path.stem}"
                self._load_module(module_name, source=str(path), import_path=str(path))
        return self

    def _load_module(self, module_name: str, *, source: str, import_path: str) -> None:
        try:
            if import_path.endswith(".py"):
                spec = importlib.util.spec_from_file_location(module_name, import_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"cannot load {import_path}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            else:
                module = __import__(import_path, fromlist=["*"])
            self._register_from_module(module, source)
        except Exception as exc:  # a broken drop-in must not take the platform down
            get_logger(__name__).warning(
                "activity_discovery_failed", module=module_name, error=str(exc)
            )

    def _register_from_module(self, module: ModuleType, source: str) -> None:
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if not issubclass(candidate, Activity) or candidate is Activity:
                continue
            if candidate.__module__ != module.__name__:
                continue
            if not candidate.name or inspect.isabstract(candidate):
                continue
            instance = candidate()
            if instance.name in self._activities:
                get_logger(__name__).warning(
                    "duplicate_activity_name",
                    activity=instance.name,
                    ignored_source=source,
                )
                continue
            self._activities[instance.name] = instance
            self._sources[instance.name] = source

    def get(self, name: str) -> Activity[Any] | None:
        return self._activities.get(name)

    def require(self, name: str) -> Activity[Any]:
        from app.errors import ActivityNotFound

        activity = self.get(name)
        if activity is None:
            raise ActivityNotFound(f"unknown activity: {name}")
        return activity

    def all(self) -> list[Activity[Any]]:
        return [self._activities[name] for name in sorted(self._activities)]

    def names(self) -> set[str]:
        return set(self._activities)

    def source_of(self, name: str) -> str:
        return self._sources.get(name, "")

    def specs(self) -> list[dict[str, Any]]:
        return [self.spec(activity) for activity in self.all()]

    def spec(self, activity: Activity[Any]) -> dict[str, Any]:
        schema = activity.input_model.model_json_schema()
        return {
            "name": activity.name,
            "category": activity.category,
            "version": activity.version,
            "description": activity.description or inspect.getdoc(activity) or "",
            "input_schema": schema,
            "output_fields": list(activity.output_fields),
            "sensitive_fields": list(activity.sensitive_fields),
            "requires_admin_author": activity.requires_admin_author,
            "option_fields": sorted(activity.option_providers),
            "source": self.source_of(activity.name),
        }


def _iter_modules(paths: Any, prefix: str) -> list[Any]:
    return list(pkgutil.iter_modules(paths, prefix + "."))
