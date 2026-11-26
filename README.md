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
| `d94_mcp/server.py` | MCP 앱, `/health`, d94-query 호출, DOCS·CIRA 도구 14개 |
| `d94_mcp/workflows.py` | 같은 도구를 LangChain `StructuredTool` 로 재사용, `workflow_run`/`workflow_status` (25초 넘으면 job_id) |
| `d94_mcp/token_sync.py` | allowlist 동기화 (`--loop 3600`) |

## 실행

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
GATEWAY_URL=http://localhost:10001 .venv/bin/uvicorn d94_mcp.server:app --port 8095
```

delap: `cp .env.example .env` (token-sync 용 DB·Redis) → `docker compose up -d --build`.
토큰 발급 직후 바로 쓰려면 `docker compose run --rm token-sync python -m d94_mcp.token_sync` 로 1회 동기화.

| 환경 변수 | 기본값 | 대상 |
|---|---|---|
| `GATEWAY_URL` | `http://gateway-cloud-gateway-1:10001` | d94-mcp |
| `D94_TIMEOUT_SECONDS` | `25` | d94-mcp → d94-query 호출 상한 |
| `D94_WORKFLOW_SYNC_SECONDS` | `25` | workflow_run 이 동기로 기다리는 시간 |
| `DB_*`, `REDIS_*` | `.env.example` | token-sync |

## 클라이언트 설정

```bash
claude mcp add --transport http d94 https://{UMD_HOST}/mcp --header "Authorization: Bearer d94_all_..."
```

- 토큰 서비스: `docs`/`cira` 는 해당 도구만, 전역 `all` 은 둘 다(워크플로우 포함). READ 토큰으로 쓰기 도구 → 403.
- 새 토큰은 token-sync 주기 때문에 UMD 통과까지 최대 1시간.

## 제약

- `uvicorn --workers 1` 고정: workflow job 은 프로세스 메모리에 있고 재시작하면 사라진다.
- 워크플로우는 LLM 없이 도구를 엮는다(호출하는 AI 가 추론 담당). 서버 쪽 LLM 단계가 필요하면 `build_workflows` 에 Runnable 추가.
