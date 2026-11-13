from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from molochai_cli.config import (
    ConfigFile,
    config_dir,
    mask_key,
    normalize_base_url,
    resolve_settings,
    write_private_file,
)
from molochai_cli.errors import ConfigError, UsageError
from support import API_KEY, Router, Runner, models_response, stream_reply

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")


def write_config(directory: Path, data: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# -- location ---------------------------------------------------------------------------------


def test_config_dir_override(tmp_path: Path) -> None:
    assert config_dir({"MOLOCHAI_CONFIG_DIR": str(tmp_path)}) == tmp_path


def test_config_dir_windows(tmp_path: Path) -> None:
    env = {"APPDATA": str(tmp_path)}
    assert config_dir(env, platform="win32") == tmp_path / "molochai"
    fallback = config_dir({}, platform="win32")
    assert fallback == Path.home() / "AppData" / "Roaming" / "molochai"


def test_config_dir_posix(tmp_path: Path) -> None:
    xdg = tmp_path / "xdg"
    assert config_dir({"XDG_CONFIG_HOME": str(xdg)}, platform="linux") == xdg / "molochai"
    default = Path.home() / ".config" / "molochai"
    assert config_dir({}, platform="darwin") == default
    # A relative XDG_CONFIG_HOME is invalid per the spec and ignored.
    assert config_dir({"XDG_CONFIG_HOME": "relative"}, platform="linux") == default
    assert config_dir({"XDG_CONFIG_HOME": "  "}, platform="linux") == default


def test_config_path_command(bare_cli: Runner, config_dir: Path) -> None:
    result = bare_cli("config", "path")
    assert result.code == 0
    assert result.out.strip() == str(config_dir / "config.json")


# -- precedence -------------------------------------------------------------------------------


def test_flags_beat_environment_beat_file_beat_defaults(tmp_path: Path) -> None:
    config = ConfigFile(
        tmp_path / "c.json",
        {"api_key": "file-key", "model": "file-model", "base_url": "https://file.test/v1"},
    )
    env = {
        "MOLOCHAI_API_KEY": "env-key",
        "MOLOCHAI_MODEL": "env-model",
        "MOLOCHAI_BASE_URL": "https://env.test/v1/",
    }
    s = resolve_settings(
        environ=env, config=config, model_flag="flag-model", base_url_flag="https://flag.test/v1"
    )
    assert (s.model.value, s.model.source) == ("flag-model", "--model")
    assert (s.base_url.value, s.base_url.source) == ("https://flag.test/v1", "--base-url")
    assert (s.api_key.value, s.api_key.source) == ("env-key", "MOLOCHAI_API_KEY")

    s = resolve_settings(environ=env, config=config)
    assert (s.model.value, s.model.source) == ("env-model", "MOLOCHAI_MODEL")
    assert (s.base_url.value, s.base_url.source) == ("https://env.test/v1", "MOLOCHAI_BASE_URL")

    s = resolve_settings(environ={"MOLOCHAI_MODEL": "  "}, config=config)
    assert (s.model.value, s.model.source) == ("file-model", "config file")
    assert (s.api_key.value, s.api_key.source) == ("file-key", "config file")
    assert s.base_url.value == "https://file.test/v1"

    s = resolve_settings(environ={}, config=ConfigFile(tmp_path / "none.json"))
    assert (s.model.value, s.model.source) == ("glm-5.3-flash", "default")
    assert (s.base_url.value, s.base_url.source) == ("https://api.molochai.dev/api/v1", "default")
    assert (s.api_key.value, s.api_key.source) == (None, "not set")


def test_precedence_end_to_end(config_dir: Path) -> None:
    write_config(
        config_dir,
        {"api_key": "file-key-123456789", "model": "file-model", "base_url": "https://f.test/v1"},
    )
    runner = Runner(config_dir=config_dir)
    router = Router(stream_reply())
    result = runner("ask", "Hi", handler=router)
    assert result.code == 0
    settings = result.settings[0]
    assert settings.api_key.value == "file-key-123456789"
    assert router.chat_bodies()[0]["model"] == "file-model"
    assert str(router.requests[0].url) == "https://f.test/v1/chat/completions"

    router = Router(stream_reply())
    result = runner(
        "--base-url",
        "https://flag.test/api/v1",
        "ask",
        "Hi",
        "--model",
        "flag-model",
        handler=router,
        env={"MOLOCHAI_MODEL": "env-model", "MOLOCHAI_API_KEY": "env-key-123456789"},
    )
    assert result.settings[0].api_key.value == "env-key-123456789"
    assert router.chat_bodies()[0]["model"] == "flag-model"
    assert str(router.requests[0].url) == "https://flag.test/api/v1/chat/completions"


def test_base_url_flag_after_the_command(cli: Runner) -> None:
    router = Router(models=models_response())
    result = cli("models", "--base-url", "http://127.0.0.1:9/api/v1/", handler=router)
    assert result.code == 0
    assert str(router.requests[0].url) == "http://127.0.0.1:9/api/v1/models"


def test_invalid_base_url(cli: Runner) -> None:
    result = cli("models", env={"MOLOCHAI_BASE_URL": "api.molochai.dev"})
    assert result.code == 3
    assert "MOLOCHAI_BASE_URL must start with http:// or https://" in result.err
    result = cli("--base-url", "ftp://x", "models")
    assert result.code == 2


def test_normalize_base_url() -> None:
    assert normalize_base_url(" https://a.test/v1/ ") == "https://a.test/v1"
    with pytest.raises(ValueError, match="http"):
        normalize_base_url("https://")


def test_missing_key_is_a_config_error(bare_cli: Runner) -> None:
    result = bare_cli("ask", "Hi")
    assert result.code == 3
    assert "No API key." in result.err
    assert "molochai config set-key" in result.err
    assert "dash.molochai.dev/account?utm_source=github" in result.err


def test_invalid_sdk_setting_is_a_config_error(
    cli: Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOLOCHAI_TIMEOUT", "soon")
    result = cli("models")
    assert result.code == 3
    assert "MOLOCHAI_TIMEOUT" in result.err


def test_there_is_no_api_key_flag(cli: Runner) -> None:
    result = cli("ask", "Hi", "--api-key", "sk-oops")
    assert result.code == 2
    assert "unrecognized arguments" in result.err


# -- the file ---------------------------------------------------------------------------------


def test_invalid_json(bare_cli: Runner, config_dir: Path) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{nope", encoding="utf-8")
    result = bare_cli("config", "show")
    assert result.code == 3
    assert "is not valid JSON" in result.err


@pytest.mark.parametrize("data", [["a list"], {"model": 5}])
def test_wrong_shapes(bare_cli: Runner, config_dir: Path, data: object) -> None:
    write_config(config_dir, data)
    assert bare_cli("config", "show").code == 3


def test_empty_file_is_an_empty_config(bare_cli: Runner, config_dir: Path) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("", encoding="utf-8")
    assert bare_cli("config", "show").code == 0


def test_unreadable_file(bare_cli: Runner, config_dir: Path) -> None:
    (config_dir / "config.json").mkdir(parents=True)  # a directory where the file should be
    result = bare_cli("config", "show")
    assert result.code == 3
    assert "Could not read the config file" in result.err


def test_unknown_keys_survive_a_rewrite(bare_cli: Runner, config_dir: Path) -> None:
    path = write_config(config_dir, {"future_option": True, "model": "a"})
    assert bare_cli("config", "set", "model", "b").code == 0
    assert json.loads(path.read_text(encoding="utf-8")) == {"future_option": True, "model": "b"}


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "config.json"
    write_private_file(path, '{"a": 1}\n')
    write_private_file(path, '{"a": 2}\n')
    assert path.read_text(encoding="utf-8") == '{"a": 2}\n'
    assert [p.name for p in path.parent.iterdir()] == ["config.json"]


def test_write_failure_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(src: str, dst: str) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(ConfigError, match="Could not write"):
        write_private_file(tmp_path / "config.json", "{}")
    assert list(tmp_path.iterdir()) == []


def test_write_interrupted_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(src: str, dst: str) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        write_private_file(tmp_path / "config.json", "{}")
    assert list(tmp_path.iterdir()) == []


def test_cannot_create_directory(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="Could not create"):
        write_private_file(blocker / "sub" / "config.json", "{}")


def test_cannot_create_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tempfile

    def fail(**kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(tempfile, "mkstemp", fail)
    with pytest.raises(ConfigError, match="Could not write to"):
        write_private_file(tmp_path / "config.json", "{}")


@posix_only
def test_posix_permissions(bare_cli: Runner, config_dir: Path) -> None:
    old_umask = os.umask(0o022)
    try:
        result = bare_cli("config", "set-key", "--stdin", stdin=API_KEY + "\n")
    finally:
        os.umask(old_umask)
    assert result.code == 0
    path = config_dir / "config.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700


@posix_only
def test_posix_warns_about_readable_file(bare_cli: Runner, config_dir: Path) -> None:
    path = write_config(config_dir, {"model": "a"})
    os.chmod(path, 0o644)
    result = bare_cli("config", "show")
    assert result.code == 0
    assert "can be read by other users (mode 644)" in result.err
    assert "chmod 600" in result.err
    # Rewriting the file fixes the mode.
    assert bare_cli("config", "set", "model", "b").code == 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform != "win32", reason="Windows has no POSIX modes")
def test_windows_skips_the_mode_check(bare_cli: Runner, config_dir: Path) -> None:
    write_config(config_dir, {"model": "a"})
    assert bare_cli("config", "show").err == ""


# -- config commands --------------------------------------------------------------------------


def test_set_key_with_hidden_prompt(bare_cli: Runner, config_dir: Path) -> None:
    prompts: list[str] = []

    def fake_getpass(prompt: str) -> str:
        prompts.append(prompt)
        return "  " + API_KEY + "  "

    result = bare_cli("config", "set-key", stdin_tty=True, getpass=fake_getpass)
    assert result.code == 0
    assert prompts == ["API key (input hidden): "]
    assert API_KEY not in result.out
    assert "****mnop" in result.out
    data = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert data == {"api_key": API_KEY}


def test_set_key_from_stdin(bare_cli: Runner, config_dir: Path) -> None:
    result = bare_cli("config", "set-key", "--stdin", stdin=API_KEY + "\n")
    assert result.code == 0
    assert json.loads((config_dir / "config.json").read_text(encoding="utf-8"))["api_key"] == (
        API_KEY
    )
    # The saved key is used.
    router = Router(models=models_response())
    assert bare_cli("models", handler=router).code == 0
    assert router.requests[0].headers["authorization"] == f"Bearer {API_KEY}"


def test_set_key_refuses_a_pipe_without_the_flag(bare_cli: Runner) -> None:
    result = bare_cli("config", "set-key", stdin="sk-key\n")
    assert result.code == 2
    assert "--stdin" in result.err


@pytest.mark.parametrize("key", ["", "   \n", "two words"])
def test_set_key_rejects_bad_input(bare_cli: Runner, config_dir: Path, key: str) -> None:
    assert bare_cli("config", "set-key", "--stdin", stdin=key).code == 2
    assert not (config_dir / "config.json").exists()


def test_set_key_notes_an_overriding_environment_variable(cli: Runner) -> None:
    result = cli("config", "set-key", "--stdin", stdin="another-key-123456")
    assert result.code == 0
    assert "MOLOCHAI_API_KEY is set in your environment" in result.err


def test_set_model_and_base_url(bare_cli: Runner, config_dir: Path) -> None:
    assert bare_cli("config", "set", "model", "gemma4-26b-a4b-qat").code == 0
    result = bare_cli("config", "set", "base-url", "http://127.0.0.1:4010/api/v1/")
    assert result.code == 0
    assert "Base URL set to http://127.0.0.1:4010/api/v1" in result.out
    data = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert data == {"model": "gemma4-26b-a4b-qat", "base_url": "http://127.0.0.1:4010/api/v1"}


def test_set_notes_overriding_environment(bare_cli: Runner) -> None:
    result = bare_cli("config", "set", "model", "x", env={"MOLOCHAI_MODEL": "y"})
    assert "MOLOCHAI_MODEL is set in your environment" in result.err


def test_set_validation(bare_cli: Runner) -> None:
    result = bare_cli("config", "set", "api-key", "sk-in-history")
    assert result.code == 2
    assert "shell history" in result.err
    assert "config set-key" in result.err
    assert bare_cli("config", "set", "base-url", "not-a-url").code == 2
    assert bare_cli("config", "set", "model", "has space").code == 2
    result = bare_cli("config", "set", "colour", "blue")
    assert result.code == 2
    assert "Settings: api-key, base-url, model." in result.err


def test_set_accepts_underscore_names(bare_cli: Runner, config_dir: Path) -> None:
    assert bare_cli("config", "set", "base_url", "https://x.test/v1").code == 0


def test_unset(bare_cli: Runner, config_dir: Path) -> None:
    path = write_config(config_dir, {"model": "a", "api_key": "k"})
    result = bare_cli("config", "unset", "model")
    assert result.code == 0
    assert "Removed model" in result.out
    assert json.loads(path.read_text(encoding="utf-8")) == {"api_key": "k"}
    result = bare_cli("config", "unset", "base-url")
    assert "base-url is not set" in result.out
    assert bare_cli("config", "unset", "api-key").code == 0
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_show_masks_the_key_and_names_sources(bare_cli: Runner, config_dir: Path) -> None:
    write_config(config_dir, {"api_key": "sk-secret-value-1234", "model": "file-model"})
    result = bare_cli("config", "show", env={"MOLOCHAI_BASE_URL": "http://127.0.0.1:4010/api/v1"})
    assert result.code == 0
    assert "sk-secret-value-1234" not in result.out
    lines = {line.split("  ")[0]: line for line in result.out.splitlines()}
    assert "****1234" in lines["API key"]
    assert "(config file)" in lines["API key"]
    assert "http://127.0.0.1:4010/api/v1" in lines["Base URL"]
    assert "(MOLOCHAI_BASE_URL)" in lines["Base URL"]
    assert "file-model  (config file)" in lines["Model"]


def test_show_without_anything(bare_cli: Runner) -> None:
    result = bare_cli("config", "show")
    assert "(not created yet)" in result.out
    assert "not set  (not set)" in result.out
    assert "glm-5.3-flash  (default)" in result.out


def test_mask_key() -> None:
    assert mask_key("sk-abcdefghijkl") == "****ijkl"
    assert mask_key("short") == "****"


def test_config_set_error_types() -> None:
    assert issubclass(UsageError, Exception)
    assert ConfigError("x").exit_code == 3
    assert UsageError("x").exit_code == 2


def test_model_from_config_used_by_chat(config_dir: Path) -> None:
    write_config(config_dir, {"api_key": API_KEY, "model": "llama-3.3-70b-instruct-abliterated"})
    router = Router(stream_reply(["Hi."], reasoning=[]))
    result = Runner(config_dir=config_dir)("chat", handler=router, lines=["Hello"])
    assert result.code == 0
    assert router.chat_bodies()[0]["model"] == "llama-3.3-70b-instruct-abliterated"


def test_set_key_from_stdin_drops_a_byte_order_mark(bare_cli: Runner, config_dir: Path) -> None:
    assert bare_cli("config", "set-key", "--stdin", stdin="﻿" + API_KEY + "\r\n").code == 0
    data = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert data["api_key"] == API_KEY
