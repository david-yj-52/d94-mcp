# d94-mcp

delap 의 MCP 서버(Stateless Streamable HTTP, `POST /mcp`) + API 토큰 allowlist 동기화 배치.
설계: `d94-note` MCP 설계서 · 토큰: `d94-note/feature/user/3_api_token/api-token-plan.md`

```
AI 도구 ─POST /mcp, Bearer d94_─▶ Server UMD (Redis allowlist 확인) ─Stream─▶ Local UMD (/mcp → d94-mcp:8095)
  ─▶ d94-mcp ─Bearer 그대로─▶ gateway:10001/tsh/api/v1 ─▶ d94-query (최종 인증·권한)
token-sync: SN_API_TOKEN ⋈ GS_USER 활성 해시 → AP-02 Redis d94:api-token:active:{sha256} (1시간)
```

| 파일 | 내용 |
|---|---|
| `d94_mcp/server.py` | MCP 앱 조립, 요청별 Authorization 미들웨어, `/health` |
| `d94_mcp/client.py` | gateway → d94-query 호출 (토큰 그대로 전달, 401/403/404/409 메시지, 목록 상한 100) |
| `d94_mcp/docs.py` | DOCS 도구 19개 — 폴더·노트(조회·생성·수정·이동·이력·백링크·파생·계보)·Task |
| `d94_mcp/cira.py` | CIRA 도구 43개 — 프로젝트·이슈(상태 전이)·댓글·스프린트·보드·마일스톤·버전·위키·사용자 검색 |
| `d94_mcp/workflows.py` | 같은 도구를 LangChain `StructuredTool` 로 재사용, `workflow_run`/`workflow_status` (25초 넘으면 job_id) |
| `d94_mcp/token_sync.py` | allowlist 동기화 (`--loop 3600`) |
| `setup/setup_mcp.py` | 로컬 AI 도구에 MCP 서버 등록 (표준 라이브러리만) |

## 실행

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
GATEWAY_URL=http://localhost:10001 .venv/bin/uvicorn d94_mcp.server:app --port 8095
```

delap `~/data/app/mcp`: `.env` (token-sync 용 DB·Redis) → `docker compose pull && docker compose up -d`. 이미지는 `deploy` push 시 GHCR `latest` 로 발행 (main 은 개발 브랜치 머지용).
토큰 발급 직후 바로 쓰려면 `docker compose run --rm token-sync python -m d94_mcp.token_sync` 로 1회 동기화.

| 환경 변수 | 기본값 | 대상 |
|---|---|---|
| `GATEWAY_URL` | `http://gateway-cloud-gateway-1:10001` | d94-mcp |
| `D94_TIMEOUT_SECONDS` | `25` | d94-mcp → d94-query 호출 상한 |
| `D94_WORKFLOW_SYNC_SECONDS` | `25` | workflow_run 이 동기로 기다리는 시간 |
| `DB_*`, `REDIS_*` | `.env.example` | token-sync |

## 클라이언트 설정 (로컬 PC)

```bash
git clone https://github.com/david-yj-52/d94-mcp.git && cd d94-mcp
python3 setup/setup_mcp.py            # 토큰 입력(화면에 안 보임) → 서버 확인 → 설치된 AI 도구에 등록
```

| 옵션 | 내용 |
|---|---|
| `--clients codex,gemini` / `all` | 대상 지정. 생략하면 설치된 도구만 (CLI 가 PATH 에 있거나 설정 폴더가 있음) |
| `--remove` | 등록 해제 |
| `--dry-run`, `-y` | 미리 보기 / 확인 없이 진행 |
| `--url`, `--name` | 기본 `https://api.tongsung.site/mcp`, `d94` |
| `D94_MCP_TOKEN` | 토큰을 환경 변수로 (자동화용) |

| 도구 | 등록 위치 |
|---|---|
| Claude Code | `claude mcp add --scope user` (CLI 없으면 `~/.claude.json`) |
| Claude Desktop | `claude_desktop_config.json` — 원격 서버는 `npx mcp-remote` 로 중계 (Node 필요) |
| Cursor | `~/.cursor/mcp.json` |
| Gemini CLI | `~/.gemini/settings.json` (`httpUrl`). 신뢰하지 않은 폴더에서는 Gemini 가 MCP 를 끈다 → 폴더 trust 필요 |
| Antigravity | `~/.gemini/config/mcp_config.json` (`serverUrl`) |
| Codex CLI | `~/.codex/config.toml` `[mcp_servers.d94]` (`http_headers`) |
| Grok CLI | `~/.grok/config.toml` `[mcp_servers.d94]` (`headers`) |
| OpenCode | `~/.config/opencode/opencode.json` (`mcp.d94`, `type: remote`) |

- 기존 설정은 다른 항목을 보존한 채 `d94` 항목만 추가·교체하고, 바꾸기 전 `.bak-<시각>` 으로 백업한다. 다시 실행하면 같은 항목을 덮어쓴다 (토큰 교체도 같은 명령).
- 주석이 든 JSON 처럼 읽을 수 없는 파일은 건드리지 않고 알려 준다. 새로 만드는 파일은 권한 600 (토큰이 들어 있음).
- 토큰: d94-web 설정 > API 토큰. `docs`/`cira` 는 해당 도구만, 전역 `all` 은 둘 다(워크플로우 포함). READ 토큰으로 쓰기 도구 → 403.
- 새 토큰은 token-sync 주기 때문에 최대 1시간 뒤 통과 (스크립트가 401 로 알려 줌). 등록 후 각 도구를 재시작.

## 제약

- 삭제 도구와 관리 기능(워크플로우·필드·자동화 규칙 편집, 멤버 권한 변경)은 두지 않는다 — d94-web 에서.

- `uvicorn --workers 1` 고정: workflow job 은 프로세스 메모리에 있고 재시작하면 사라진다.
- 워크플로우는 LLM 없이 도구를 엮는다(호출하는 AI 가 추론 담당). 서버 쪽 LLM 단계가 필요하면 `build_workflows` 에 Runnable 추가.
