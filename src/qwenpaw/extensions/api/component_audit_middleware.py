# -*- coding: utf-8 -*-
"""Propagate verified mutation identity to the persistence layer."""

from starlette.middleware.base import BaseHTTPMiddleware

from ...governance.component_events import actor


class ComponentAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)
        identity = getattr(request.state, "access_identity", None)
        local_user = getattr(request.state, "user", None)
        subject = (
            f"inoe:{identity.user_id}"
            if identity and identity.user_id
            else f"local:{local_user}" if local_user else "未验证主体"
        )
        token = actor.set(subject)
        try:
            return await call_next(request)
        finally:
            actor.reset(token)
