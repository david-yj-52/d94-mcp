"""LangChain 워크플로우 + 25초 가드 비동기 job.

MCP 도구 함수를 그대로 LangChain StructuredTool 로 감싸 재사용한다 (스키마는 함수 시그니처 하나).
SYNC_WAIT 안에 끝나면 결과를, 넘으면 job_id 를 돌려주고 백그라운드에서 계속 실행한다.
"""

import asyncio
import hashlib
import os
import time
import uuid
from contextvars import ContextVar
from typing import Any

from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.tools import StructuredTool
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

SYNC_WAIT = float(os.environ.get("D94_WORKFLOW_SYNC_SECONDS", "25"))
JOB_TTL = 3600

# ponytail: 메모리 job 저장소 — 재시작하면 사라지고 workers=1 전제. 여러 프로세스면 Redis 로
_jobs: dict[str, dict[str, Any]] = {}


def _gc() -> None:
    now = time.monotonic()
    for jid in [j for j, v in _jobs.items() if v["task"].done() and now - v["at"] > JOB_TTL]:
        del _jobs[jid]


def build_workflows(tools: dict[str, StructuredTool]) -> dict[str, Runnable]:
    async def open_tasks_of_note(inp: dict) -> dict:
        tasks = await tools["docs_list_tasks"].ainvoke({"status": inp.get("status", "todo"), "limit": 100})
        return {**inp, "tasks": [t for t in tasks if t["noteId"] == inp["note_id"]]}

    async def create_issues(inp: dict) -> dict:
        created = []
        for t in inp["tasks"]:
            issue = await tools["cira_create_issue"].ainvoke({
                "project_id": inp["project_id"], "title": t["text"],
                "content": f"DOCS 노트 '{t['noteTitle']}' {t['lineNo']}번 줄에서 생성"})
            created.append({"lineNo": t["lineNo"], "issueId": issue.get("id"), "title": t["text"]})
        return {"note_id": inp["note_id"], "created": created}

    return {
        # input: {note_id, project_id, status?=todo} — 노트의 체크박스 Task 를 CIRA 이슈로 일괄 생성
        "docs_tasks_to_cira": RunnableLambda(open_tasks_of_note) | RunnableLambda(create_issues),
    }


def register(mcp: MCPServer, tool_fns: list, auth_header: ContextVar) -> None:
    tools = {f.__name__: StructuredTool.from_function(coroutine=f) for f in tool_fns}
    workflows = build_workflows(tools)

    def owner() -> str:
        return hashlib.sha256((auth_header.get() or "").encode()).hexdigest()

    @mcp.tool()
    async def workflow_run(name: str, input: dict) -> dict:
        """LangChain 워크플로우 실행. 25초 안에 끝나면 {status:done,result}, 넘으면 {status:running,job_id}
        → workflow_status 로 조회. 워크플로우: docs_tasks_to_cira {note_id, project_id, status?}
        (DOCS·CIRA 둘 다 부르므로 전역(all) 토큰이 필요)."""
        wf = workflows.get(name)
        if wf is None:
            raise ToolError(f"알 수 없는 워크플로우: {name} (가능: {', '.join(workflows)})")
        _gc()
        task = asyncio.create_task(wf.ainvoke(input))  # 컨텍스트(토큰) 복사됨
        try:
            return {"status": "done", "result": await asyncio.wait_for(asyncio.shield(task), SYNC_WAIT)}
        except TimeoutError:
            job_id = uuid.uuid4().hex
            _jobs[job_id] = {"task": task, "owner": owner(), "at": time.monotonic()}
            return {"status": "running", "job_id": job_id}

    @mcp.tool()
    async def workflow_status(job_id: str) -> dict:
        """workflow_run 이 돌려준 job_id 의 상태·결과."""
        job = _jobs.get(job_id)
        if job is None or job["owner"] != owner():  # 남의 job 은 없는 것과 같다
            raise ToolError(f"404 job 없음: {job_id}")
        task: asyncio.Task = job["task"]
        if not task.done():
            return {"status": "running", "job_id": job_id}
        if task.exception():
            return {"status": "failed", "job_id": job_id, "error": str(task.exception())}
        return {"status": "done", "job_id": job_id, "result": task.result()}
