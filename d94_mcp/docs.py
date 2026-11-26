"""DOCS 도구 (/api/v1/docs) — 로그인 사용자의 개인 vault. 남의 폴더·노트는 404.

ponytail: 삭제 도구는 두지 않는다 (AI 실수로 되돌릴 수 없는 손실 방지). 필요하면 d94-web 에서.
"""

from d94_mcp.client import call, cap

# ── 폴더 ──


async def docs_list_folders() -> list[dict]:
    """DOCS 폴더 목록 (id, parentId, name, sortOrder)."""
    return await call("GET", "/docs/folders")


async def docs_create_folder(name: str, parent_id: str | None = None) -> dict:
    """DOCS 폴더 생성. parent_id 없으면 최상위."""
    return await call("POST", "/docs/folders", json={"name": name, "parentId": parent_id})


async def docs_rename_folder(folder_id: str, name: str) -> dict:
    """DOCS 폴더 이름 변경."""
    return await call("PUT", f"/docs/folders/{folder_id}", json={"name": name})


async def docs_move_folder(folder_id: str, parent_id: str | None = None, sort_order: int | None = None) -> dict:
    """DOCS 폴더 이동. parent_id 없으면 최상위로."""
    return await call("PUT", f"/docs/folders/{folder_id}/move", json={"parentId": parent_id, "sortOrder": sort_order})


# ── 노트 ──


async def docs_list_notes(q: str | None = None, folder_id: str | None = None, kind: str | None = None,
                          stream: str | None = None, tag: str | None = None, origin: str | None = None,
                          limit: int = 50) -> list[dict]:
    """DOCS 노트 목록. q=제목·본문 검색, folder_id=""이면 최상위만, 생략하면 전체. 최대 100건."""
    data = await call("GET", "/docs/notes", params={"q": q, "folderId": folder_id, "kind": kind,
                                                    "stream": stream, "tag": tag, "origin": origin})
    return data[:cap(limit)]


async def docs_list_note_titles(prefix: str | None = None) -> list[str]:
    """DOCS 노트 제목 목록 ([[링크]] 자동완성용). prefix 로 시작하는 것만."""
    return await call("GET", "/docs/notes/titles", params={"prefix": prefix})


async def docs_get_note(note_id: str) -> dict:
    """DOCS 노트 하나 (본문·version 포함). 수정 전에 version 을 확인하세요."""
    return await call("GET", f"/docs/notes/{note_id}")


async def docs_get_note_by_title(title: str) -> dict:
    """제목으로 DOCS 노트 조회 (제목은 사용자 vault 안에서 유일)."""
    return await call("GET", "/docs/notes/by-title", params={"title": title})


async def docs_create_note(title: str, content: str = "", folder_id: str | None = None) -> dict:
    """DOCS 노트 생성. 본문은 Markdown, `- [ ] 할 일` 줄은 Task, `[[제목]]` 은 노트 링크."""
    return await call("POST", "/docs/notes", json={"title": title, "content": content, "folderId": folder_id})


async def docs_update_note(note_id: str, version: int, title: str | None = None,
                           content: str | None = None, folder_id: str | None = None) -> dict:
    """DOCS 노트 수정. version 은 docs_get_note 의 값 (다르면 409). 주지 않은 필드는 그대로."""
    return await call("PUT", f"/docs/notes/{note_id}",
                      json={"title": title, "content": content, "folderId": folder_id, "version": version})


async def docs_move_note(note_id: str, folder_id: str | None = None) -> dict:
    """DOCS 노트를 다른 폴더로 이동. folder_id 없으면 최상위로."""
    return await call("PUT", f"/docs/notes/{note_id}/move", json={"folderId": folder_id})


async def docs_list_note_versions(note_id: str) -> list[dict]:
    """DOCS 노트 수정 이력 (version, title, content, editedBy, editedAt)."""
    return await call("GET", f"/docs/notes/{note_id}/versions")


async def docs_list_backlinks(note_id: str) -> list[dict]:
    """이 노트를 [[링크]] 로 가리키는 노트들."""
    return await call("GET", f"/docs/notes/{note_id}/backlinks")


# ── 진화 (파생·종류·계보) ──


async def docs_derive_note(note_id: str, title: str, stream: str | None = None, kind: str | None = None) -> dict:
    """기존 노트에서 새 노트 파생 (원본과 계보로 연결). 새 노트를 돌려준다."""
    return await call("POST", f"/docs/notes/{note_id}/derive", json={"title": title, "stream": stream, "kind": kind})


async def docs_change_note_kind(note_id: str, kind: str) -> dict:
    """DOCS 노트 종류(kind) 변경."""
    return await call("PUT", f"/docs/notes/{note_id}/kind", json={"kind": kind})


async def docs_get_note_lineage(note_id: str) -> list[dict]:
    """노트 계보 (파생 원본·자손)."""
    return await call("GET", f"/docs/notes/{note_id}/lineage")


# ── Task (노트 안 체크박스) ──


async def docs_list_tasks(status: str | None = None, tag: str | None = None, stream: str | None = None,
                          due_before: str | None = None, limit: int = 50) -> list[dict]:
    """DOCS 노트 안의 체크박스 Task 목록. status=todo|doing|done, due_before=YYYY-MM-DD. 최대 100건."""
    data = await call("GET", "/docs/tasks", params={"status": status, "tag": tag, "stream": stream,
                                                    "dueBefore": due_before})
    return data[:cap(limit)]


async def docs_update_task_status(note_id: str, line_no: int, status: str) -> dict:
    """DOCS Task 상태 변경. status=todo|doing|done, note_id·line_no 는 docs_list_tasks 값."""
    return await call("PUT", f"/docs/tasks/{note_id}/{line_no}", json={"status": status})


async def docs_promote_task(note_id: str, line_no: int) -> dict:
    """DOCS Task 줄을 별도 노트로 승격하고 새 노트를 돌려준다."""
    return await call("POST", f"/docs/tasks/{note_id}/{line_no}/promote")


TOOLS = [
    docs_list_folders, docs_create_folder, docs_rename_folder, docs_move_folder,
    docs_list_notes, docs_list_note_titles, docs_get_note, docs_get_note_by_title,
    docs_create_note, docs_update_note, docs_move_note, docs_list_note_versions, docs_list_backlinks,
    docs_derive_note, docs_change_note_kind, docs_get_note_lineage,
    docs_list_tasks, docs_update_task_status, docs_promote_task,
]
