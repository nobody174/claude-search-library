import os

import pytest
import yaml

from src import config as config_module


VALID_YAML = """
api:
  anthropic_api_key: ${{ANTHROPIC_API_KEY}}

storage:
  data_dir: {data_dir}
  db_path: {data_dir}/library.db
  chromadb_path: {data_dir}/chromadb
  raw_chats_dir: {data_dir}/raw_chats

sync:
  github_repo: github.com/someone/repo
  sync_interval: 300
  github_token: ${{GITHUB_TOKEN}}

processing:
  batch_size: 10
  max_workers: 1
  rate_limit_per_min: 10
  timeout_per_chat: 30

redaction:
  flag_for_review_threshold: 3
  enable_logging: true

server:
  port: 7654
  host: localhost
  allowed_origins: ["localhost", "127.0.0.1"]

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
"""


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in config_module.ENV_OVERRIDES:
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def config_file(tmp_path):
    data_dir = tmp_path / "data"
    path = tmp_path / "config.yaml"
    path.write_text(VALID_YAML.format(data_dir=str(data_dir)), encoding="utf-8")
    return path, data_dir


def test_load_config_parses_yaml(config_file, monkeypatch):
    path, data_dir = config_file
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")

    config = config_module.load_config(str(path))

    assert config["sync"]["github_repo"] == "github.com/someone/repo"
    assert config["processing"]["batch_size"] == 10
    assert config["server"]["port"] == 7654


def test_load_config_substitutes_env_vars(config_file, monkeypatch):
    path, data_dir = config_file
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-substituted-key")

    config = config_module.load_config(str(path))
    assert config["api"]["anthropic_api_key"] == "sk-substituted-key"


def test_load_config_missing_required_field_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    incomplete_yaml = "storage:\n  data_dir: /tmp/x\n"
    path = tmp_path / "config.yaml"
    path.write_text(incomplete_yaml, encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid configuration"):
        config_module.load_config(str(path))


def test_load_config_missing_api_key_raises(config_file):
    path, data_dir = config_file
    # No ANTHROPIC_API_KEY set -> substitution leaves it blank -> should fail validation.
    with pytest.raises(ValueError):
        config_module.load_config(str(path))


def test_env_override_takes_precedence_over_yaml(config_file, monkeypatch):
    path, data_dir = config_file
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-yaml-substitution")
    monkeypatch.setenv("GITHUB_REPO", "github.com/overridden/repo")

    config = config_module.load_config(str(path))
    assert config["sync"]["github_repo"] == "github.com/overridden/repo"


def test_env_override_db_path(config_file, monkeypatch, tmp_path):
    path, data_dir = config_file
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    override_path = str(tmp_path / "custom.db")
    monkeypatch.setenv("DB_PATH", override_path)

    config = config_module.load_config(str(path))
    assert config["storage"]["db_path"] == str(__import__("pathlib").Path(override_path).expanduser())


def test_load_config_expands_user_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    yaml_content = VALID_YAML.format(data_dir="~/fake-claude-search-test-dir")
    path = tmp_path / "config.yaml"
    path.write_text(yaml_content, encoding="utf-8")

    config = config_module.load_config(str(path))
    assert not config["storage"]["data_dir"].startswith("~")


def test_load_config_falls_back_to_template_when_no_path_given(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.chdir(tmp_path)  # no ./config.yaml here
    monkeypatch.setattr(config_module.Path, "home", lambda: tmp_path / "fake-home")

    config = config_module.load_config()
    assert "storage" in config
    assert config["sync"]["github_repo"]


def test_load_config_prefers_cwd_config_over_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    data_dir = tmp_path / "cwd-data"
    (cwd_dir / "config.yaml").write_text(VALID_YAML.format(data_dir=str(data_dir)), encoding="utf-8")

    monkeypatch.chdir(cwd_dir)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr(config_module.Path, "home", lambda: fake_home)

    config = config_module.load_config()
    assert str(data_dir) in config["storage"]["data_dir"]


def test_validate_config_reports_missing_fields():
    errors = config_module.validate_config({})
    assert any("data_dir" in e for e in errors)
    assert any("anthropic_api_key" in e for e in errors)


def test_validate_config_valid_returns_empty(tmp_path):
    config = {
        "api": {"anthropic_api_key": "sk-test"},
        "storage": {
            "data_dir": str(tmp_path / "data"),
            "db_path": str(tmp_path / "data" / "lib.db"),
            "chromadb_path": str(tmp_path / "data" / "chromadb"),
            "raw_chats_dir": str(tmp_path / "data" / "raw"),
        },
        "sync": {"github_repo": "github.com/x/y"},
    }
    errors = config_module.validate_config(config)
    assert errors == []


def test_create_directories_creates_all_expected_dirs(tmp_path):
    data_dir = tmp_path / "data"
    config = {
        "storage": {
            "data_dir": str(data_dir),
            "chromadb_path": str(data_dir / "chromadb"),
            "raw_chats_dir": str(data_dir / "raw_chats"),
        }
    }

    result = config_module.create_directories(config)

    assert result is True
    assert data_dir.exists()
    assert (data_dir / "chromadb").exists()
    assert (data_dir / "raw_chats").exists()
    assert (data_dir / "logs").exists()


def test_create_directories_idempotent(tmp_path):
    data_dir = tmp_path / "data"
    config = {"storage": {"data_dir": str(data_dir)}}
    assert config_module.create_directories(config) is True
    assert config_module.create_directories(config) is True  # no error on second call
