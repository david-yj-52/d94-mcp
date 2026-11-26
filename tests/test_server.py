"""POST /mcp 전체 경로: 토큰 전달, 오류 매핑, 25초 가드(job_id) — gateway 는 httpx.MockTransport."""

import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from d94_mcp import server, workflows

TOKEN = "Bearer d94_all_test"
calls: list[httpx.Request] = []


async def gateway(req: httpx.Request) -> httpx.Response:
    calls.append(req)
    if req.url.path == "/tsh/api/v1/projects/P1/issues":
        body = json.loads(req.content)
        return httpx.Response(200, json={"success": True, "data": {"id": "I-" + body["title"]}})
    if req.url.path == "/tsh/api/v1/docs/notes" and req.method == "POST":
        return httpx.Response(403, json={"success": False, "code": "FORBIDDEN", "message": "READ token"})
    if req.url.path == "/tsh/api/v1/docs/tasks":
        await asyncio.sleep(0.3)  # 가드보다 오래 걸리는 워크플로우
        return httpx.Response(200, json={"success": True, "data": [
            {"noteId": "N1", "noteTitle": "회의", "lineNo": 3, "text": "a", "status": "todo"},
            {"noteId": "N2", "noteTitle": "x", "lineNo": 1, "text": "skip", "status": "todo"}]})
    return httpx.Response(404, json={"success": False, "message": "no route"})


@pytest.fixture
def client(monkeypatch):
    calls.clear()
    monkeypatch.setattr(server, "_http", httpx.AsyncClient(
        base_url="http://gw/tsh/api/v1", transport=httpx.MockTransport(gateway)))
    monkeypatch.setattr(workflows, "SYNC_WAIT", 0.05)
    # session manager 는 1회용 → 테스트마다 새 앱
    app = server.mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")
    with TestClient(app) as c:
        yield c


def rpc(client, method, params=None, token=TOKEN):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = token
    r = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                                   "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()


def tool(client, name, args, token=TOKEN):
    res = rpc(client, "tools/call", {"name": name, "arguments": args}, token)["result"]
    text = res["content"][0]["text"] if res["content"] else ""
    if res.get("isError"):
        return True, text
    return False, json.loads(text)


def test_health_and_tools_list(client):
    assert client.get("/health").json() == {"status": "UP"}
    names = {t["name"] for t in rpc(client, "tools/list")["result"]["tools"]}
    assert {"docs_list_notes", "cira_create_issue", "workflow_run", "workflow_status"} <= names


def test_token_passthrough_and_errors(client):
    err, out = tool(client, "cira_create_issue", {"project_id": "P1", "title": "t1"})
    assert not err and out == {"id": "I-t1"}
    assert calls[-1].headers["authorization"] == TOKEN

    err, out = tool(client, "docs_create_note", {"title": "x"})
    assert err and "403" in out and "READ token" in out

    err, out = tool(client, "cira_list_projects", {}, token=None)
    assert err and "401" in out and not any(c.url.path.endswith("/projects") for c in calls)


def test_workflow_switches_to_job_and_is_owner_scoped(client):
    err, out = tool(client, "workflow_run", {"name": "docs_tasks_to_cira",
                                             "input": {"note_id": "N1", "project_id": "P1"}})
    assert not err and out["status"] == "running"
    job = out["job_id"]

    err, other = tool(client, "workflow_status", {"job_id": job}, token="Bearer d94_all_other")
    assert err and "404" in other

    for _ in range(50):
        err, st = tool(client, "workflow_status", {"job_id": job})
        if st["status"] != "running":
            break
        client.portal.call(asyncio.sleep, 0.05)
    assert st["status"] == "done", st
    assert st["result"]["created"] == [{"lineNo": 3, "issueId": "I-a", "title": "a"}]
    assert all(c.headers["authorization"] == TOKEN for c in calls)  # 백그라운드에서도 같은 토큰
