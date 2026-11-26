"""CIRA 도구 (/api/v1/{projects,issues,comments,sprints,boards,milestones,versions,wiki,search,users/search}).

토큰 소유자의 CIRA 권한 그대로 동작한다 (변경은 프로젝트 권한 검사).
ponytail: 삭제·워크플로우/필드/자동화 규칙 편집 같은 관리 기능은 두지 않는다 — 필요하면 d94-web 에서.
날짜는 모두 YYYY-MM-DD. 수정 도구는 주지 않은 필드를 바꾸지 않는다.
"""

from d94_mcp.client import call, cap, page

# ── 프로젝트 ──


async def cira_list_projects() -> list[dict]:
    """CIRA 프로젝트 목록."""
    return await call("GET", "/projects")


async def cira_get_project(project_id: str) -> dict:
    """CIRA 프로젝트 하나."""
    return await call("GET", f"/projects/{project_id}")


async def cira_create_project(key: str, name: str, description: str | None = None,
                              project_type_id: str | None = None) -> dict:
    """CIRA 프로젝트 생성. key 는 이슈 번호 접두어 (예: DOCS → DOCS-1). 만든 사람이 ADMIN."""
    return await call("POST", "/projects", json={"key": key, "name": name, "description": description,
                                                 "projectTypeId": project_type_id})


async def cira_update_project(project_id: str, name: str | None = None, description: str | None = None,
                              project_type_id: str | None = None) -> dict:
    """CIRA 프로젝트 수정 (프로젝트 ADMIN)."""
    return await call("PUT", f"/projects/{project_id}", json={"name": name, "description": description,
                                                              "projectTypeId": project_type_id})


async def cira_list_project_members(project_id: str) -> list[dict]:
    """프로젝트 멤버 (assignee_id 로 쓸 사용자 id 확인용)."""
    return await call("GET", f"/projects/{project_id}/members")


async def cira_list_statuses(project_id: str) -> list[dict]:
    """프로젝트 워크플로우 상태 목록 (status_id 확인용)."""
    return await call("GET", f"/projects/{project_id}/workflow/statuses")


async def cira_list_issue_types() -> list[dict]:
    """이슈 유형 목록 (issue_type_id 확인용)."""
    return await call("GET", "/issue-types")


async def cira_search_users(keyword: str) -> list[dict]:
    """이름·이메일로 사용자 검색 (담당자 지정용)."""
    return await call("GET", "/users/search", params={"keyword": keyword})


# ── 이슈 ──


async def cira_list_issues(project_id: str, status: list[str] | None = None, priority: str | None = None,
                           assignee_id: str | None = None, issue_type: str | None = None,
                           sprint_id: str | None = None, keyword: str | None = None,
                           page_no: int = 0, limit: int = 20) -> dict:
    """프로젝트 이슈 목록 (필터). 결과 {items,total,page,size}. limit 최대 100."""
    return page(await call("GET", f"/projects/{project_id}/issues", params={
        "status": status, "priority": priority, "assigneeId": assignee_id, "issueType": issue_type,
        "sprintId": sprint_id, "keyword": keyword, "page": page_no, "size": cap(limit)}))


async def cira_search_issues(q: str | None = None, project_id: list[str] | None = None,
                             status: list[str] | None = None, assignee_id: str | None = None,
                             priority: str | None = None, sprint_id: str | None = None,
                             page_no: int = 0, limit: int = 20) -> dict:
    """CIRA 이슈 검색 (전체 프로젝트). 결과 {items,total,page,size}. limit 최대 100."""
    return page(await call("GET", "/search/issues", params={
        "q": q, "projectId": project_id, "status": status, "assigneeId": assignee_id,
        "priority": priority, "sprintId": sprint_id, "page": page_no, "size": cap(limit)}))


async def cira_get_issue(issue_id: str) -> dict:
    """CIRA 이슈 하나."""
    return await call("GET", f"/issues/{issue_id}")


async def cira_create_issue(project_id: str, title: str, content: str | None = None,
                            issue_type_id: str | None = None, status_id: str | None = None,
                            priority: str | None = None, story_points: float | None = None,
                            assignee_id: str | None = None, sprint_id: str | None = None,
                            due_dt: str | None = None, parent_issue_ids: list[str] | None = None) -> dict:
    """CIRA 이슈 생성. parent_issue_ids 를 주면 하위 작업."""
    return await call("POST", f"/projects/{project_id}/issues", json={
        "title": title, "content": content, "issueTypeId": issue_type_id, "statusId": status_id,
        "priority": priority, "storyPnt": story_points, "assigneeId": assignee_id, "sprintId": sprint_id,
        "dueDt": due_dt, "parentIssueIds": parent_issue_ids})


async def cira_update_issue(issue_id: str, title: str | None = None, content: str | None = None,
                            priority: str | None = None, story_points: float | None = None,
                            assignee_id: str | None = None, sprint_id: str | None = None,
                            due_dt: str | None = None) -> dict:
    """CIRA 이슈 수정. 상태 변경은 cira_change_issue_status."""
    return await call("PUT", f"/issues/{issue_id}", json={
        "title": title, "content": content, "priority": priority, "storyPnt": story_points,
        "assigneeId": assignee_id, "sprintId": sprint_id, "dueDt": due_dt})


async def cira_get_available_transitions(issue_id: str) -> list[dict]:
    """이 이슈가 지금 옮겨갈 수 있는 상태 목록 (워크플로우 전이 규칙 적용)."""
    return await call("GET", f"/issues/{issue_id}/available-transitions")


async def cira_change_issue_status(issue_id: str, status_id: str) -> dict:
    """이슈 상태 변경. status_id 는 cira_get_available_transitions 의 값 (허용 안 된 전이는 400)."""
    return await call("PUT", f"/issues/{issue_id}/status", json={"statusId": status_id})


# ── 댓글 ──


async def cira_list_comments(issue_id: str) -> list[dict]:
    """이슈 댓글 목록."""
    return await call("GET", f"/issues/{issue_id}/comments")


async def cira_add_comment(issue_id: str, content: str, parent_id: str | None = None) -> dict:
    """이슈에 댓글 추가. parent_id 를 주면 답글."""
    return await call("POST", f"/issues/{issue_id}/comments", json={"content": content, "parentId": parent_id})


async def cira_update_comment(comment_id: str, content: str) -> dict:
    """댓글 수정 (작성자만)."""
    return await call("PUT", f"/comments/{comment_id}", json={"content": content})


# ── 스프린트 ──


async def cira_list_sprints(project_id: str) -> list[dict]:
    """프로젝트 스프린트 목록."""
    return await call("GET", f"/projects/{project_id}/sprints")


async def cira_get_active_sprint(project_id: str) -> dict:
    """진행 중인 스프린트."""
    return await call("GET", f"/projects/{project_id}/sprints/active")


async def cira_get_sprint(sprint_id: str) -> dict:
    """스프린트 하나."""
    return await call("GET", f"/sprints/{sprint_id}")


async def cira_list_backlog(project_id: str, page_no: int = 0, limit: int = 20) -> dict:
    """스프린트에 없는 이슈(백로그). 결과 {items,total,page,size}."""
    return page(await call("GET", f"/projects/{project_id}/backlog", params={"page": page_no, "size": cap(limit)}))


async def cira_create_sprint(project_id: str, name: str, goal: str | None = None,
                             start_dt: str | None = None, end_dt: str | None = None) -> dict:
    """스프린트 생성."""
    return await call("POST", f"/projects/{project_id}/sprints",
                      json={"sprintNm": name, "goal": goal, "startDt": start_dt, "endDt": end_dt})


async def cira_update_sprint(sprint_id: str, name: str | None = None, goal: str | None = None,
                             start_dt: str | None = None, end_dt: str | None = None) -> dict:
    """스프린트 수정."""
    return await call("PUT", f"/sprints/{sprint_id}",
                      json={"sprintNm": name, "goal": goal, "startDt": start_dt, "endDt": end_dt})


async def cira_start_sprint(sprint_id: str) -> dict:
    """스프린트 시작."""
    return await call("POST", f"/sprints/{sprint_id}/start")


async def cira_complete_sprint(sprint_id: str, incomplete_issue_action: str = "BACKLOG",
                               next_sprint_id: str | None = None) -> dict:
    """스프린트 완료. 남은 이슈: incomplete_issue_action=BACKLOG|NEXT_SPRINT (NEXT_SPRINT 면 next_sprint_id)."""
    return await call("POST", f"/sprints/{sprint_id}/complete",
                      json={"incompleteIssueAction": incomplete_issue_action, "nextSprintId": next_sprint_id})


async def cira_add_issue_to_sprint(sprint_id: str, issue_id: str) -> dict:
    """이슈를 스프린트에 넣는다."""
    return await call("POST", f"/sprints/{sprint_id}/issues/{issue_id}")


# ── 보드 ──


async def cira_list_boards(project_id: str) -> list[dict]:
    """프로젝트 보드 목록."""
    return await call("GET", f"/projects/{project_id}/boards")


async def cira_get_board(board_id: str) -> dict:
    """보드 하나 (컬럼과 카드)."""
    return await call("GET", f"/boards/{board_id}")


async def cira_move_board_issue(board_id: str, issue_id: str, target_column_id: str,
                                after_issue_id: str | None = None, before_issue_id: str | None = None) -> dict:
    """보드에서 카드를 다른 컬럼·순서로 이동 (컬럼에 연결된 상태로 바뀜)."""
    return await call("PUT", f"/boards/{board_id}/issues/{issue_id}/move", json={
        "targetColumnId": target_column_id, "afterIssueId": after_issue_id, "beforeIssueId": before_issue_id})


# ── 마일스톤 ──


async def cira_list_milestones(project_id: str) -> list[dict]:
    """프로젝트 마일스톤 목록."""
    return await call("GET", f"/projects/{project_id}/milestones")


async def cira_get_milestone(milestone_id: str) -> dict:
    """마일스톤 하나."""
    return await call("GET", f"/milestones/{milestone_id}")


async def cira_create_milestone(project_id: str, name: str, description: str | None = None,
                                due_date: str | None = None, status: str | None = None) -> dict:
    """마일스톤 생성."""
    return await call("POST", f"/projects/{project_id}/milestones",
                      json={"name": name, "description": description, "dueDate": due_date, "status": status})


async def cira_update_milestone(milestone_id: str, name: str | None = None, description: str | None = None,
                                due_date: str | None = None, status: str | None = None) -> dict:
    """마일스톤 수정."""
    return await call("PUT", f"/milestones/{milestone_id}",
                      json={"name": name, "description": description, "dueDate": due_date, "status": status})


async def cira_add_issue_to_milestone(milestone_id: str, issue_id: str) -> dict:
    """이슈를 마일스톤에 연결."""
    return await call("POST", f"/milestones/{milestone_id}/issues/{issue_id}")


# ── 버전(릴리스) ──


async def cira_list_versions(project_id: str) -> list[dict]:
    """프로젝트 버전 목록."""
    return await call("GET", f"/projects/{project_id}/versions")


async def cira_create_version(project_id: str, name: str, description: str | None = None,
                              status: str | None = None, planned_release_dt: str | None = None) -> dict:
    """버전 생성."""
    return await call("POST", f"/projects/{project_id}/versions", json={
        "versionNm": name, "descr": description, "status": status, "planRelDt": planned_release_dt})


async def cira_update_version(version_id: str, name: str | None = None, description: str | None = None,
                              status: str | None = None, planned_release_dt: str | None = None) -> dict:
    """버전 수정."""
    return await call("PUT", f"/versions/{version_id}", json={
        "versionNm": name, "descr": description, "status": status, "planRelDt": planned_release_dt})


async def cira_add_issue_to_version(version_id: str, issue_id: str, type: str = "FIX_VERSION") -> dict:
    """이슈를 버전에 연결. type=FIX_VERSION(기본)|AFFECTS_VERSION."""
    return await call("POST", f"/versions/{version_id}/issues/{issue_id}", params={"type": type})


# ── 위키 ──


async def cira_list_wiki_pages(project_id: str) -> list[dict]:
    """프로젝트 위키 페이지 목록 (트리)."""
    return await call("GET", f"/projects/{project_id}/wiki")


async def cira_get_wiki_page(page_id: str) -> dict:
    """위키 페이지 하나 (본문 포함)."""
    return await call("GET", f"/wiki/{page_id}")


async def cira_create_wiki_page(project_id: str, title: str, content: str = "", parent_id: str | None = None,
                                sort_order: int | None = None) -> dict:
    """위키 페이지 생성 (Markdown). parent_id 를 주면 하위 페이지."""
    return await call("POST", f"/projects/{project_id}/wiki", json={
        "title": title, "content": content, "parentId": parent_id, "sortOrder": sort_order})


async def cira_update_wiki_page(page_id: str, title: str | None = None, content: str | None = None,
                                sort_order: int | None = None) -> dict:
    """위키 페이지 수정 (이전 내용은 이력으로 남는다). 주지 않은 제목·본문은 그대로."""
    if title is None or content is None:  # 백엔드는 title·content 를 그대로 덮어쓴다 → 현재 값으로 채움
        cur = await call("GET", f"/wiki/{page_id}")
        title = cur.get("title") if title is None else title
        content = cur.get("content") if content is None else content
    return await call("PUT", f"/wiki/{page_id}", json={"title": title, "content": content, "sortOrder": sort_order})


TOOLS = [
    cira_list_projects, cira_get_project, cira_create_project, cira_update_project,
    cira_list_project_members, cira_list_statuses, cira_list_issue_types, cira_search_users,
    cira_list_issues, cira_search_issues, cira_get_issue, cira_create_issue, cira_update_issue,
    cira_get_available_transitions, cira_change_issue_status,
    cira_list_comments, cira_add_comment, cira_update_comment,
    cira_list_sprints, cira_get_active_sprint, cira_get_sprint, cira_list_backlog,
    cira_create_sprint, cira_update_sprint, cira_start_sprint, cira_complete_sprint, cira_add_issue_to_sprint,
    cira_list_boards, cira_get_board, cira_move_board_issue,
    cira_list_milestones, cira_get_milestone, cira_create_milestone, cira_update_milestone,
    cira_add_issue_to_milestone,
    cira_list_versions, cira_create_version, cira_update_version, cira_add_issue_to_version,
    cira_list_wiki_pages, cira_get_wiki_page, cira_create_wiki_page, cira_update_wiki_page,
]
