"""d94-mcp: Stateless Streamable HTTP MCP 서버 (POST /mcp).

클라이언트의 `Authorization: Bearer d94_...` 를 gateway → d94-query 로 그대로 넘긴다.
권한·테넌트·폐기 검증은 d94-query 가 한다. 여기서는 토큰을 보관·검증하지 않는다.
"""

import os
from contextvars import ContextVar
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from d94_mcp import workflows

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway-cloud-gateway-1:10001")
# UMD request-timeout 30s 보다 짧게 — 넘으면 504 로 끊긴다
TIMEOUT = float(os.environ.get("D94_TIMEOUT_SECONDS", "25"))
# UMD max-response-body 5MB 보호용 목록 상한
MAX_LIMIT = 100

# 요청별 Authorization 헤더. 미들웨어가 넣고, 도구·워크플로우(create_task 는 컨텍스트 복사)가 읽는다
auth_header: ContextVar[str | None] = ContextVar("auth_header", default=None)

_http = httpx.AsyncClient(base_url=f"{GATEWAY_URL}/tsh/api/v1", timeout=TIMEOUT)

_REASON = {
    401: "인증 실패 (토큰 없음·만료·폐기·소유자 정지)",
    403: "권한 없음 (서비스 범위 밖이거나 READ 토큰으로 쓰기)",
    404: "대상 없음",
    409: "충돌 (다른 곳에서 먼저 수정됨 — 다시 조회 후 version 을 맞추세요)",
}


async def call(method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
    header = auth_header.get()
    if not header or not header.startswith("Bearer "):
        raise ToolError("401 Authorization: Bearer d94_... 헤더가 필요합니다")
    params = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        r = await _http.request(method, path, params=params, json=json,
                                headers={"Authorization": header})
    except httpx.TimeoutException as e:
        raise ToolError(f"504 d94-query 응답 시간 초과 ({TIMEOUT:.0f}s)") from e
    except httpx.TransportError as e:
        raise ToolError(f"502 gateway 연결 실패 ({GATEWAY_URL}): {type(e).__name__}") from e
    body = r.json() if r.content and "json" in r.headers.get("content-type", "") else None
    if r.status_code >= 400:
        msg = body.get("message") if isinstance(body, dict) else r.text[:200]
        raise ToolError(f"{r.status_code} {_REASON.get(r.status_code, '요청 실패')}: {msg or ''}".strip())
    return body.get("data") if isinstance(body, dict) and "data" in body else body


def _cap(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def _page(data: Any) -> Any:
    """Spring Page → 필요한 필드만 (응답 크기 절약)"""
    if isinstance(data, dict) and "content" in data:
        return {"items": data["content"], "total": data.get("totalElements"),
                "page": data.get("number"), "size": data.get("size")}
    return data


# ── DOCS (/api/v1/docs) — 로그인 사용자의 개인 vault ──

async def docs_list_notes(q: str | None = None, folder_id: str | None = None, kind: str | None = None,
                          tag: str | None = None, limit: int = 50) -> list[dict]:
    """DOCS 노트 목록. q=제목·본문 검색, folder_id=""이면 최상위만. 최대 100건."""
    data = await call("GET", "/docs/notes", params={"q": q, "folderId": folder_id, "kind": kind, "tag": tag})
    return data[:_cap(limit)]


async def docs_get_note(note_id: str) -> dict:
    """DOCS 노트 하나 (본문·version 포함). 수정 전에 version 을 확인하세요."""
    return await call("GET", f"/docs/notes/{note_id}")


async def docs_create_note(title: str, content: str = "", folder_id: str | None = None) -> dict:
    """DOCS 노트 생성. 본문은 Markdown, `- [ ] 할 일` 줄은 Task 로 인식된다."""
    return await call("POST", "/docs/notes", json={"title": title, "content": content, "folderId": folder_id})


async def docs_update_note(note_id: str, version: int, title: str | None = None,
                           content: str | None = None, folder_id: str | None = None) -> dict:
    """DOCS 노트 수정. version 은 docs_get_note 의 값 (다르면 409)."""
    return await call("PUT", f"/docs/notes/{note_id}",
                      json={"title": title, "content": content, "folderId": folder_id, "version": version})


async def docs_list_tasks(status: str | None = None, tag: str | None = None,
                          due_before: str | None = None, limit: int = 50) -> list[dict]:
    """DOCS 노트 안의 체크박스 Task 목록. status=todo|doing|done, due_before=YYYY-MM-DD. 최대 100건."""
    data = await call("GET", "/docs/tasks", params={"status": status, "tag": tag, "dueBefore": due_before})
    return data[:_cap(limit)]


async def docs_update_task_status(note_id: str, line_no: int, status: str) -> dict:
    """DOCS Task 상태 변경. status=todo|doing|done, note_id·line_no 는 docs_list_tasks 값."""
    return await call("PUT", f"/docs/tasks/{note_id}/{line_no}", json={"status": status})


async def docs_promote_task(note_id: str, line_no: int) -> dict:
    """DOCS Task 줄을 별도 노트로 승격하고 새 노트를 돌려준다."""
    return await call("POST", f"/docs/tasks/{note_id}/{line_no}/promote")


# ── CIRA (/api/v1/{projects,issues,comments,search}) ──

async def cira_list_projects() -> list[dict]:
    """CIRA 프로젝트 목록."""
    return await call("GET", "/projects")


async def cira_get_project(project_id: str) -> dict:
    """CIRA 프로젝트 하나."""
    return await call("GET", f"/projects/{project_id}")


async def cira_search_issues(q: str | None = None, project_id: list[str] | None = None,
                             status: list[str] | None = None, assignee_id: str | None = None,
                             priority: str | None = None, sprint_id: str | None = None,
                             page: int = 0, limit: int = 20) -> dict:
    """CIRA 이슈 검색 (전체 프로젝트). 결과는 {items,total,page,size}. limit 최대 100."""
    return _page(await call("GET", "/search/issues", params={
        "q": q, "projectId": project_id, "status": status, "assigneeId": assignee_id,
        "priority": priority, "sprintId": sprint_id, "page": page, "size": _cap(limit)}))


async def cira_get_issue(issue_id: str) -> dict:
    """CIRA 이슈 하나."""
    return await call("GET", f"/issues/{issue_id}")


async def cira_create_issue(project_id: str, title: str, content: str | None = None,
                            issue_type_id: str | None = None, priority: str | None = None,
                            assignee_id: str | None = None, sprint_id: str | None = None,
                            due_dt: str | None = None, parent_issue_ids: list[str] | None = None) -> dict:
    """CIRA 이슈 생성. due_dt=YYYY-MM-DD, parent_issue_ids 를 주면 하위 작업."""
    return await call("POST", f"/projects/{project_id}/issues", json={
        "title": title, "content": content, "issueTypeId": issue_type_id, "priority": priority,
        "assigneeId": assignee_id, "sprintId": sprint_id, "dueDt": due_dt, "parentIssueIds": parent_issue_ids})


async def cira_update_issue(issue_id: str, title: str | None = None, content: str | None = None,
                            status_id: str | None = None, priority: str | None = None,
                            assignee_id: str | None = None, sprint_id: str | None = None,
                            due_dt: str | None = None) -> dict:
    """CIRA 이슈 수정. 주지 않은 필드는 바뀌지 않는다."""
    return await call("PUT", f"/issues/{issue_id}", json={
        "title": title, "content": content, "statusId": status_id, "priority": priority,
        "assigneeId": assignee_id, "sprintId": sprint_id, "dueDt": due_dt})


async def cira_add_comment(issue_id: str, content: str, parent_id: str | None = None) -> dict:
    """CIRA 이슈에 댓글 추가."""
    return await call("POST", f"/issues/{issue_id}/comments", json={"content": content, "parentId": parent_id})


TOOLS = [
    docs_list_notes, docs_get_note, docs_create_note, docs_update_note,
    docs_list_tasks, docs_update_task_status, docs_promote_task,
    cira_list_projects, cira_get_project, cira_search_issues, cira_get_issue,
    cira_create_issue, cira_update_issue, cira_add_comment,
]


async def _auth_middleware(ctx, call_next):
    request = ctx.request
    header = request.headers.get("authorization") if request is not None else None
    reset = auth_header.set(header)
    try:
        return await call_next(ctx)
    finally:
        auth_header.reset(reset)


mcp = MCPServer("d94", instructions="d94 DOCS(개인 노트·Task)와 CIRA(프로젝트·이슈) 조회·생성·수정.",
                middleware=[_auth_middleware])
for _fn in TOOLS:
    mcp.tool()(_fn)

workflows.register(mcp, TOOLS, auth_header)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "UP"})


# ponytail: 단일 프로세스(uvicorn workers=1) 전제 — job_store 가 메모리에 있다
app = mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")
