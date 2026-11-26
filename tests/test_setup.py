"""setup/setup_mcp.py: 기존 설정 보존·재실행 멱등·해제, 읽을 수 없는 파일 보호."""

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("setup_mcp", Path(__file__).parents[1] / "setup/setup_mcp.py")
setup_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_mcp)

URL, AUTH = "https://api.example/mcp", "Bearer d94_all_x"


def test_json_merge_idempotent_and_remove(tmp_path):
    cfg = tmp_path / ".gemini/settings.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"security": {"a": 1}, "mcpServers": {"other": {"httpUrl": "o"}}}))

    for _ in range(2):
        setup_mcp.apply("gemini", tmp_path, "d94", URL, AUTH)
    data = json.loads(cfg.read_text())
    assert data["security"] == {"a": 1} and data["mcpServers"]["other"] == {"httpUrl": "o"}
    assert data["mcpServers"]["d94"] == {"httpUrl": URL, "headers": {"Authorization": AUTH}}
    assert list(cfg.parent.glob("settings.json.bak-*"))

    setup_mcp.apply("gemini", tmp_path, "d94", URL, None)
    assert "d94" not in json.loads(cfg.read_text())["mcpServers"]


def test_new_file_is_private(tmp_path):
    setup_mcp.apply("opencode", tmp_path, "d94", URL, AUTH)
    cfg = tmp_path / ".config/opencode/opencode.json"
    assert json.loads(cfg.read_text())["mcp"]["d94"]["type"] == "remote"
    assert cfg.stat().st_mode & 0o777 == 0o600


def test_toml_replaces_only_own_section(tmp_path):
    cfg = tmp_path / ".codex/config.toml"
    cfg.parent.mkdir()
    cfg.write_text('model = "x"\n\n[mcp_servers.d94]\nurl = "old"\n\n[mcp_servers.d94.env]\nA = "1"\n\n'
                   '[mcp_servers.other]\nurl = "o"\n')

    for _ in range(2):
        setup_mcp.apply("codex", tmp_path, "d94", URL, AUTH)
    text = cfg.read_text()
    assert text.count("[mcp_servers.d94]") == 1 and "old" not in text and "d94.env" not in text
    assert 'model = "x"' in text and '[mcp_servers.other]\nurl = "o"' in text
    assert f'http_headers = {{ "Authorization" = "{AUTH}" }}' in text

    setup_mcp.apply("codex", tmp_path, "d94", URL, None)
    assert "mcp_servers.d94" not in cfg.read_text() and "mcp_servers.other" in cfg.read_text()


def test_unparseable_json_is_left_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_mcp.shutil, "which", lambda _: None)  # claude CLI 없음 → ~/.claude.json 직접
    cfg = tmp_path / ".claude.json"
    cfg.write_text('{ // comment\n "x": 1 }')
    with pytest.raises(SystemExit):
        setup_mcp.apply("claude-code", tmp_path, "d94", URL, AUTH)
    assert cfg.read_text() == '{ // comment\n "x": 1 }'
