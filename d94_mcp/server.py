"""d94-mcp: Stateless Streamable HTTP MCP 서버 (POST /mcp).

클라이언트의 `Authorization: Bearer d94_...` 를 gateway → d94-query 로 그대로 넘긴다 (client.py).
권한·테넌트·폐기 검증은 d94-query 가 한다. 여기서는 토큰을 보관·검증하지 않는다.
"""

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from d94_mcp import cira, docs, workflows
from d94_mcp.client import auth_header

TOOLS = docs.TOOLS + cira.TOOLS


async def _auth_middleware(ctx, call_next):
    request = ctx.request
    header = request.headers.get("authorization") if request is not None else None
    reset = auth_header.set(header)
    try:
        return await call_next(ctx)
    finally:
        auth_header.reset(reset)


mcp = MCPServer("d94", instructions=(
    "d94 DOCS(개인 노트·폴더·Task)와 CIRA(프로젝트·이슈·댓글·스프린트·보드·마일스톤·버전·위키) 조회·생성·수정. "
    "id 를 모르면 목록·검색 도구로 먼저 찾는다. 상태 변경은 cira_get_available_transitions → cira_change_issue_status. "
    "DOCS 노트 수정은 docs_get_note 의 version 이 필요하다. 삭제 도구는 없다."), middleware=[_auth_middleware])
for _fn in TOOLS:
    mcp.tool()(_fn)

workflows.register(mcp, TOOLS, auth_header)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "UP"})


# ponytail: 단일 프로세스(uvicorn workers=1) 전제 — job_store 가 메모리에 있다
app = mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")
