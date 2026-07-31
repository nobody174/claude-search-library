"""Configuration management for Claude Search Library.

Loads config.yaml (with ${VAR_NAME} environment variable substitution),
applies environment-variable overrides for common fields, validates
required fields, and creates the on-disk directory layout.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "config_template.yaml"

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Maps env var name -> (section, key) for direct overrides, per SPEC.
ENV_OVERRIDES = {
    "ANTHROPIC_API_KEY": ("api", "anthropic_api_key"),
    "DATA_DIR": ("storage", "data_dir"),
    "DB_PATH": ("storage", "db_path"),
    "CHROMADB_PATH": ("storage", "chromadb_path"),
    "SYNC_INTERVAL": ("sync", "sync_interval"),
    "GITHUB_REPO": ("sync", "github_repo"),
    "GITHUB_TOKEN": ("sync", "github_token"),
}

REQUIRED_FIELDS = [
    ("storage", "data_dir"),
    ("storage", "db_path"),
    ("storage", "chromadb_path"),
    ("storage", "raw_chats_dir"),
    ("sync", "github_repo"),
]


def _substitute_env_vars(value):
    """Recursively replace ${VAR_NAME} references with environment values.

    A reference to an unset variable is replaced with an empty string,
    same as this behaving as a template — validation catches the resulting
    missing/blank required fields separately.
    """
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            return os.environ.get(match.group(1), "")
        return _VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(v) for v in value]
    return value


def _find_config_path(config_path: Optional[str] = None) -> Optional[Path]:
    """Resolve which config file to load, honoring the priority order:
    explicit path > ./config.yaml > ~/.claude-search-library/config.yaml > None (use template).
    """
    if config_path:
        return Path(config_path)

    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        return cwd_config

    home_config = Path.home() / ".claude-search-library" / "config.yaml"
    if home_config.exists():
        return home_config

    return None


def _apply_env_overrides(config: dict) -> dict:
    for env_var, (section, key) in ENV_OVERRIDES.items():
        if env_var in os.environ:
            config.setdefault(section, {})[key] = os.environ[env_var]
    return config


def _expand_paths(config: dict) -> dict:
    storage = config.get("storage", {})
    for key in ("data_dir", "db_path", "chromadb_path", "raw_chats_dir"):
        if key in storage and storage[key]:
            storage[key] = str(Path(storage[key]).expanduser())
    return config


def load_config(config_path: Optional[str] = None) -> dict:
    """Load configuration from YAML, applying env-var substitution and overrides.

    Resolution order: explicit `config_path` > ./config.yaml >
    ~/.claude-search-library/config.yaml > built-in template. Raises
    ValueError if required fields are missing after loading.
    """
    resolved_path = _find_config_path(config_path)
    source_path = resolved_path if resolved_path is not None else TEMPLATE_PATH

    with open(source_path, "r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f) or {}

    config = _substitute_env_vars(raw_config)
    config = _apply_env_overrides(config)
    config = _expand_paths(config)

    errors = validate_config(config)
    if errors:
        raise ValueError(f"Invalid configuration: {'; '.join(errors)}")

    return config


def validate_config(config: dict) -> list:
    """Check required fields are present and non-empty, and that API key is set.

    Returns a list of human-readable error strings; empty list means valid.
    File-writability checks are best-effort (a missing directory is not an
    error here — create_directories() is responsible for creating it).
    """
    errors = []

    for section, key in REQUIRED_FIELDS:
        value = config.get(section, {}).get(key)
        if not value:
            errors.append(f"Missing required field: {section}.{key}")

    api_key = config.get("api", {}).get("anthropic_api_key")
    if not api_key:
        errors.append("Missing required field: api.anthropic_api_key (set ANTHROPIC_API_KEY)")

    for section, key in [("storage", "data_dir"), ("storage", "raw_chats_dir"), ("storage", "chromadb_path")]:
        value = config.get(section, {}).get(key)
        if value:
            path = Path(value)
            existing_ancestor = path
            while not existing_ancestor.exists() and existing_ancestor != existing_ancestor.parent:
                existing_ancestor = existing_ancestor.parent
            if existing_ancestor.exists() and not os.access(existing_ancestor, os.W_OK):
                errors.append(f"Path not writable: {section}.{key} ({value})")

    return errors


def create_directories(config: dict) -> bool:
    """Create all required directories from config if they don't already exist."""
    storage = config.get("storage", {})

    dirs_to_create = []
    if storage.get("data_dir"):
        dirs_to_create.append(Path(storage["data_dir"]))
    if storage.get("raw_chats_dir"):
        dirs_to_create.append(Path(storage["raw_chats_dir"]))
    if storage.get("chromadb_path"):
        dirs_to_create.append(Path(storage["chromadb_path"]))
    if storage.get("data_dir"):
        dirs_to_create.append(Path(storage["data_dir"]) / "logs")

    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)

    return True


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Claude Search Library configuration")
    parser.add_argument("--check", action="store_true", help="Load and validate config, print result")
    args = parser.parse_args()

    if args.check:
        try:
            config = load_config()
        except ValueError as e:
            print(f"✗ Config invalid: {e}")
            raise SystemExit(1)
        print("✓ Config loaded and valid")
        create_directories(config)
        print("✓ Directories created")


if __name__ == "__main__":
    main()
