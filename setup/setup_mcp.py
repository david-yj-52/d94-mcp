#!/usr/bin/env python3
"""d94 MCP 서버를 로컬 AI 도구들에 등록한다 (표준 라이브러리만 사용, Python 3.9+).

    python3 setup/setup_mcp.py                         # 대화형: 토큰 입력, 설치된 도구 자동 선택
    python3 setup/setup_mcp.py --clients codex,gemini  # 골라서
    python3 setup/setup_mcp.py --remove                # 등록 해제
    D94_MCP_TOKEN=d94_all_... python3 setup/setup_mcp.py --yes

토큰은 d94-web 설정 > API 토큰에서 발급 (DOCS+CIRA 를 함께 쓰려면 '전체(전역)' 토큰).
등록 후 각 도구를 재시작하면 d94 도구(docs_*, cira_*, workflow_*)가 보인다.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://api.tongsung.site/mcp"


# ── 도구별 설정 위치·형식 ──
# ponytail: 각 도구 문서 기준(2026-11). 형식이 바뀌면 해당 줄만 고친다

def _claude_desktop_path(home: Path) -> Path:
    system = platform.system()
    if system == "Darwin":
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Claude/claude_desktop_config.json"
    return home / ".config/Claude/claude_desktop_config.json"


def _antigravity_path(home: Path) -> Path:
    new, old = home / ".gemini/config/mcp_config.json", home / ".gemini/antigravity/mcp_config.json"
    return old if old.exists() and not new.exists() else new


def _toml(headers_key: str):
    return lambda url, auth: (f"url = {json.dumps(url)}\n"
                              f"{headers_key} = {{ \"Authorization\" = {json.dumps(auth)} }}\n")


# kind: json(경로, 상위 키, 항목) / toml(경로, 섹션 본문) / claude-cli
CLIENTS = {
    "claude-code": {"label": "Claude Code", "kind": "claude-cli", "cli": "claude",
                    "path": lambda h: h / ".claude.json", "key": "mcpServers",
                    "entry": lambda url, auth: {"type": "http", "url": url, "headers": {"Authorization": auth}}},
    "claude-desktop": {"label": "Claude Desktop (Node 필요: npx mcp-remote)", "kind": "json",
                       "path": _claude_desktop_path, "key": "mcpServers",
                       # 데스크톱 설정은 stdio 만 받는다 → mcp-remote 가 원격 서버로 중계
                       "entry": lambda url, auth: {"command": "npx",
                                                   "args": ["-y", "mcp-remote", url,
                                                            "--header", "Authorization:${D94_AUTH}"],
                                                   "env": {"D94_AUTH": auth}}},
    "cursor": {"label": "Cursor", "kind": "json", "cli": "cursor-agent",
               "path": lambda h: h / ".cursor/mcp.json", "key": "mcpServers",
               "entry": lambda url, auth: {"url": url, "headers": {"Authorization": auth}}},
    "gemini": {"label": "Gemini CLI", "kind": "json", "cli": "gemini",
               "path": lambda h: h / ".gemini/settings.json", "key": "mcpServers",
               "entry": lambda url, auth: {"httpUrl": url, "headers": {"Authorization": auth}}},
    "antigravity": {"label": "Antigravity", "kind": "json",
                    "path": _antigravity_path, "key": "mcpServers",
                    "entry": lambda url, auth: {"serverUrl": url, "headers": {"Authorization": auth}}},
    "codex": {"label": "Codex CLI", "kind": "toml", "cli": "codex",
              "path": lambda h: h / ".codex/config.toml",
              "body": _toml("http_headers")},
    "grok": {"label": "Grok CLI", "kind": "toml", "cli": "grok",
             "path": lambda h: h / ".grok/config.toml",
             "body": _toml("headers")},
    "opencode": {"label": "OpenCode", "kind": "json", "cli": "opencode",
                 "path": lambda h: h / ".config/opencode/opencode.json", "key": "mcp",
                 # oauth=false: 헤더 토큰 서버라 OAuth 자동 감지를 끈다
                 "entry": lambda url, auth: {"type": "remote", "url": url, "headers": {"Authorization": auth},
                                             "enabled": True, "oauth": False}},
}


def detected(cid: str, home: Path) -> bool:
    c = CLIENTS[cid]
    return bool(c.get("cli") and shutil.which(c["cli"])) or c["path"](home).parent.exists()


# ── 파일 편집 (백업 후, 읽을 수 없는 파일은 건드리지 않는다) ──

def _backup(path: Path) -> None:
    if path.exists() and path.stat().st_size:
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d%H%M%S')}"))


def _write(path: Path, text: str) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if new:
        path.chmod(0o600)  # 토큰이 들어 있다


def edit_json(path: Path, key: str, name: str, entry: dict | None) -> None:
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:  # JSONC(주석) 등 — 덮어쓰면 설정이 날아간다
        raise SystemExit(f"  ✗ {path} 를 JSON 으로 읽지 못해 건드리지 않았습니다 ({e}). 직접 추가해 주세요.")
    servers = data.setdefault(key, {})
    if entry is None:
        if servers.pop(name, None) is None:
            return
    else:
        servers[name] = entry
    _backup(path)
    _write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def edit_toml(path: Path, name: str, body: str | None) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    # [mcp_servers.<name>] 과 그 하위 테이블을 다음 다른 섹션 전까지 지운 뒤 새로 붙인다
    sect = re.escape(f"mcp_servers.{name}")
    cleaned = re.sub(rf"(?ms)^\[{sect}(\.[^\]]*)?\]\n.*?(?=^\[(?!{sect}[.\]])|\Z)", "", text)
    if body is not None:
        cleaned = cleaned.rstrip("\n") + ("\n\n" if cleaned.strip() else "") + f"[mcp_servers.{name}]\n{body}"
    if cleaned != text:
        _backup(path)
        _write(path, cleaned)


def apply(cid: str, home: Path, name: str, url: str, auth: str | None, dry_run: bool = False) -> str:
    """auth=None 이면 제거. 반환: 사람이 읽을 결과 한 줄"""
    c = CLIENTS[cid]
    path = c["path"](home)
    if dry_run:
        return f"(dry-run) {path}"
    if c["kind"] == "claude-cli" and shutil.which("claude"):
        subprocess.run(["claude", "mcp", "remove", "--scope", "user", name], capture_output=True)
        if auth is not None:
            r = subprocess.run(["claude", "mcp", "add", "--scope", "user", "--transport", "http", name, url,
                                "--header", f"Authorization: {auth}"], capture_output=True, text=True)
            if r.returncode:
                raise SystemExit(f"  ✗ claude mcp add 실패: {r.stderr.strip() or r.stdout.strip()}")
        return "claude mcp (user scope)"
    if c["kind"] == "toml":
        edit_toml(path, name, c["body"](url, auth) if auth is not None else None)
    else:
        edit_json(path, c["key"], name, c["entry"](url, auth) if auth is not None else None)
    return str(path)


# ── 서버 확인 ──

def _ssl_context() -> ssl.SSLContext:
    """python.org macOS 빌드는 CA 저장소가 비어 있다 → OS 번들(또는 certifi)로 보충. 검증은 끄지 않는다"""
    ctx = ssl.create_default_context()
    if not ctx.cert_store_stats()["x509_ca"]:
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except ImportError:
            for bundle in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
                if os.path.exists(bundle):
                    ctx.load_verify_locations(bundle)
                    break
    return ctx


def list_tools(url: str, token: str) -> list[str]:
    req = urllib.request.Request(url, method="POST", data=json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode(), headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as r:
            return [t["name"] for t in json.load(r)["result"]["tools"]]
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit("✗ 401: 토큰이 서버에 없습니다. 오타·폐기·만료를 확인하세요. "
                             "방금 발급했다면 서버 반영까지 최대 1시간 걸립니다.") from e
        raise SystemExit(f"✗ 서버 오류 {e.code}: {e.read()[:200]!r}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"✗ {url} 연결 실패: {e.reason}") from e


def main() -> None:
    p = argparse.ArgumentParser(description="d94 MCP 서버를 로컬 AI 도구에 등록")
    p.add_argument("--clients", help=f"쉼표 구분 ({','.join(CLIENTS)}) 또는 all. 생략하면 설치된 것")
    p.add_argument("--url", default=os.environ.get("D94_MCP_URL", DEFAULT_URL))
    p.add_argument("--name", default="d94", help="도구에 표시될 서버 이름")
    p.add_argument("--remove", action="store_true", help="등록 해제")
    p.add_argument("--skip-verify", action="store_true", help="서버에 tools/list 확인 생략")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-y", "--yes", action="store_true", help="확인 질문 없이 진행")
    a = p.parse_args()
    home = Path.home()

    if a.clients == "all":
        targets = list(CLIENTS)
    elif a.clients:
        targets = [c.strip() for c in a.clients.split(",")]
        unknown = [c for c in targets if c not in CLIENTS]
        if unknown:
            p.error(f"알 수 없는 도구: {', '.join(unknown)}")
    else:
        targets = [c for c in CLIENTS if detected(c, home)]
    if not targets:
        raise SystemExit("설치된 AI 도구를 찾지 못했습니다. --clients 로 지정하세요.")

    print(f"{'해제' if a.remove else '등록'} 대상 ({a.name} → {a.url}):")
    for c in targets:
        print(f"  - {CLIENTS[c]['label']:<44} {CLIENTS[c]['path'](home)}")

    auth = None
    if not a.remove:
        token = os.environ.get("D94_MCP_TOKEN") or getpass.getpass("d94 API 토큰 (d94_…, 입력 안 보임): ").strip()
        if not token.startswith("d94_"):
            raise SystemExit("✗ d94_ 로 시작하는 API 토큰이 필요합니다.")
        if not a.skip_verify:
            tools = list_tools(a.url, token)
            print(f"✓ 서버 확인: 도구 {len(tools)}개 ({', '.join(tools[:6])}{' …' if len(tools) > 6 else ''})")
        auth = f"Bearer {token}"

    if not (a.yes or a.dry_run) and input("진행할까요? [y/N] ").strip().lower() != "y":
        raise SystemExit("취소했습니다.")
    failed = 0
    for c in targets:
        try:
            print(f"  ✓ {CLIENTS[c]['label']}: {apply(c, home, a.name, a.url, auth, a.dry_run)}")
        except SystemExit as e:
            failed += 1
            print(e, file=sys.stderr)
    if not a.remove:
        print("완료. 각 도구를 재시작하면 d94 도구가 보입니다 (기존 파일은 .bak-* 로 백업).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
