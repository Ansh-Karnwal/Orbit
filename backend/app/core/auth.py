"""Owner: Victor. Sign-in seam (roadmap E).

Today this is a demo sign-in: a display name, no password, a random session cookie. Every route
already depends on current_user() and every task has an owner, so swapping in a real identity
provider means changing how sessions are created — nothing else.

ORBIT_AUTH_MODE=demo (default): anonymous requests act as `demo_user`.
ORBIT_AUTH_MODE=required: anonymous requests get 401 `unauthorized`."""
from __future__ import annotations

import re

from fastapi import APIRouter, Request, Response

from app.core import repo
from app.core.config import get_settings
from app.core.errors import OrbitError
from app.core.repo import NotFound
from app.core.schemas import LoginIn, Task, UserInfo

COOKIE = "orbit_session"
COOKIE_MAX_AGE_S = 7 * 24 * 3600
DEMO_USER_ID = "demo_user"

router = APIRouter(prefix="/auth")


def current_user(request: Request) -> UserInfo:
    mode = get_settings().orbit_auth_mode
    token = request.cookies.get(COOKIE)
    if token:
        found = repo.get_session(token)
        if found:
            return UserInfo(user_id=found[0], display_name=found[1], authenticated=True,
                            auth_mode=mode)
    if mode == "required":
        raise OrbitError(401, "unauthorized", "Sign in to continue.")
    return UserInfo(user_id=DEMO_USER_ID, display_name="Demo user", authenticated=False,
                    auth_mode=mode)


def owned_task(task_id: str, user: UserInfo) -> Task:
    """The task, if this user owns it. Other users' tasks are reported as missing (404)."""
    task = repo.get_task(task_id)
    if task.owner_id != user.user_id:
        raise NotFound(f"task {task_id!r} not found")
    return task


def _user_id(display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", display_name.strip().lower()).strip("-")[:40]
    if not slug:
        raise OrbitError(422, "invalid_request", "Use letters or numbers in your name.",
                         field="display_name")
    return "u_" + slug


@router.get("/me", response_model=UserInfo)
def me(request: Request) -> UserInfo:
    return current_user(request)


@router.post("/login", response_model=UserInfo)
def login(body: LoginIn, response: Response) -> UserInfo:
    """Demo sign-in. A real identity provider replaces this endpoint, not its callers."""
    user_id = _user_id(body.display_name)
    token = repo.create_session(user_id, body.display_name.strip())
    response.set_cookie(COOKIE, token, max_age=COOKIE_MAX_AGE_S, httponly=True, samesite="lax",
                        path="/")
    return UserInfo(user_id=user_id, display_name=body.display_name.strip(), authenticated=True,
                    auth_mode=get_settings().orbit_auth_mode)


@router.post("/logout", response_model=UserInfo)
def logout(request: Request, response: Response) -> UserInfo:
    token = request.cookies.get(COOKIE)
    if token:
        repo.delete_session(token)
    response.delete_cookie(COOKIE, path="/")
    mode = get_settings().orbit_auth_mode
    return UserInfo(user_id=DEMO_USER_ID, display_name="Demo user", authenticated=False,
                    auth_mode=mode)
