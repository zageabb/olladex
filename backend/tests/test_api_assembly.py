from backend.app.api import app


def test_task_and_pr_review_routes_are_mounted():
    paths = {route.path for route in app.routes}
    assert "/api/tasks/{task_id}/worktree" in paths
    assert "/api/tasks/{task_id}/worktree/commit" in paths
    assert "/api/tasks/{task_id}/worktree/push" in paths
    assert "/api/tasks/{task_id}/worktree/pull-request" in paths
    assert "/api/tasks/{task_id}/lifecycle" in paths
    assert "/api/tasks/{task_id}/worktree/cleanup" in paths
    assert "/api/projects/{project_id}/github/pull-requests/review" in paths
    assert "/api/projects/{project_id}/github/pull-requests/{number}/diff" in paths
    assert "/api/projects/{project_id}/github/pull-requests/{number}/comments" in paths
    assert "/api/projects/{project_id}/github/pull-requests/{number}/reviews" in paths
    assert "/api/projects/{project_id}/orchestration" in paths
    assert "/api/projects/{project_id}/orchestration/tasks" in paths
    assert "/api/projects/{project_id}/orchestration/lead" in paths
    assert "/api/tasks/{parent_task_id}/children" in paths
    assert "/api/tasks/{task_id}/review-bundle" in paths
    assert "/api/tasks/{lead_task_id}/integration/preflight" in paths
    assert "/api/tasks/{lead_task_id}/integration" in paths
    assert "/api/tasks/{lead_task_id}/integration/checks" in paths
    assert "/api/tasks/{lead_task_id}/integration/push" in paths
    assert "/api/tasks/{lead_task_id}/integration/pull-request" in paths
