"""gateway → d94-query 호출. 요청자의 Authorization 을 그대로 넘긴다 (토큰 보관·검증은 d94-query)."""

import os
from contextvars import ContextVar
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway-cloud-gateway-1:10001")
# UMD request-timeout 30s 보다 짧게 — 넘으면 504 로 끊긴다
TIMEOUT = float(os.environ.get("D94_TIMEOUT_SECONDS", "25"))
# UMD max-response-body 5MB 보호용 목록 상한
MAX_LIMIT = 100

# 요청별 Authorization 헤더. 미들웨어가 넣고, 도구·워크플로우(create_task 는 컨텍스트 복사)가 읽는다
auth_header: ContextVar[str | None] = ContextVar("auth_header", default=None)

_http = httpx.AsyncClient(base_url=f"{GATEWAY_URL}/tsh/api/v1", timeout=TIMEOUT)

_REASON = {
    400: "잘못된 요청",
    401: "인증 실패 (토큰 없음·만료·폐기·소유자 정지)",
    403: "권한 없음 (서비스 범위 밖이거나 READ 토큰으로 쓰기, 또는 프로젝트 권한 부족)",
    404: "대상 없음",
    409: "충돌 (다른 곳에서 먼저 수정됨 — 다시 조회 후 version 을 맞추세요)",
}


def drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


async def call(method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
    header = auth_header.get()
    if not header or not header.startswith("Bearer "):
        raise ToolError("401 Authorization: Bearer d94_... 헤더가 필요합니다")
    try:
        r = await _http.request(method, path, params=drop_none(params or {}), json=json,
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


def cap(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def page(data: Any) -> Any:
    """Spring Page → 필요한 필드만 (응답 크기 절약)"""
    if isinstance(data, dict) and "content" in data:
        return {"items": data["content"], "total": data.get("totalElements"),
                "page": data.get("number"), "size": data.get("size")}
    return data
