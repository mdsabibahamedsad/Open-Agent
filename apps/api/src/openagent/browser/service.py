"""Browser domain service: sessions, pages, tasks, actions, profiles, policies, events, artifacts.

Persistence is database-backed (PostgreSQL via SQLAlchemy). Actual Chromium
driving happens in the worker / TS browser package via Playwright; this service
owns tenancy, policy, risk, audit, and task state machine so crashes recover safely.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.browser.observations import compress_observation
from openagent.browser.security import (
    classify_risk,
    detect_challenge,
    detect_loop,
    detect_prompt_injection,
    fingerprint_state,
    is_retry_safe,
    label_untrusted,
    redact_dict,
    redact_text,
    requires_approval,
    sanitize_url,
    validate_url,
)
from openagent.db.models.browser import (
    BrowserAction,
    BrowserActionType,
    BrowserArtifact,
    BrowserContext,
    BrowserDomainPolicy,
    BrowserEvent,
    BrowserObservation,
    BrowserPage,
    BrowserProfile,
    BrowserProviderType,
    BrowserSession,
    BrowserSessionLease,
    BrowserSessionStatus,
    BrowserStateFingerprint,
    BrowserTask,
    BrowserTaskStatus,
)

logger = structlog.get_logger("browser.service")

SESSION_TIMEOUT = timedelta(minutes=30)
SESSION_IDLE_TIMEOUT = timedelta(minutes=5)
MAX_SESSIONS_PER_ORG = 50
MAX_SESSIONS_PER_USER = 10
MAX_PAGES_PER_SESSION = 20
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_UPLOAD_MIME_PREFIXES = ("image/", "application/pdf", "text/", "application/json",
                                "application/zip", "video/", "audio/")
BLOCKED_UPLOAD_EXTS = {".exe", ".bat", ".cmd", ".ps1", ".sh", ".dll", ".so", ".dylib", ".msi"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}_{uuid.uuid4().hex[:8]}"


class BrowserSecurityError(Exception):
    pass


class BrowserPolicyDenied(BrowserSecurityError):
    pass


class BrowserNotFound(Exception):
    pass


class BrowserService:
    """Tenant-scoped browser orchestration. All methods enforce organization_id."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -- internal helpers -------------------------------------------------
    async def _emit(self, organization_id: UUID, etype: str, *,
                    session_id: Optional[UUID] = None, task_id: Optional[UUID] = None,
                    page_id: Optional[UUID] = None, payload: Optional[dict] = None) -> BrowserEvent:
        ev = BrowserEvent(
            event_id=_sid("evt"), type=etype, organization_id=organization_id,
            session_id=session_id, task_id=task_id, page_id=page_id,
            payload=redact_dict(payload or {}), meta={}, timestamp=_now(),
        )
        self.db.add(ev)
        await self.db.flush()
        return ev

    async def _audit(self, organization_id: UUID, actor: Optional[UUID], action: str,
                     resource: str, resource_id: Optional[UUID], meta: Optional[dict] = None) -> None:
        from openagent.db.models.audit_log import AuditLog
        self.db.add(AuditLog(
            organization_id=organization_id, actor_user_id=actor, action=action,
            resource_type=resource, resource_id=resource_id, metadata=redact_dict(meta or {}),
        ))
        await self.db.flush()

    async def _policies(self, organization_id: UUID) -> list[dict[str, Any]]:
        res = await self.db.execute(
            select(BrowserDomainPolicy).where(
                (BrowserDomainPolicy.organization_id == organization_id)
                | (BrowserDomainPolicy.organization_id.is_(None))
            ).order_by(BrowserDomainPolicy.priority.desc())
        )
        return [{"domain": p.domain, "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                 "priority": p.priority} for p in res.scalars().all()]

    async def _get_session(self, session_id: str | UUID, organization_id: UUID) -> BrowserSession:
        q = select(BrowserSession).where(BrowserSession.organization_id == organization_id)
        if isinstance(session_id, UUID) or (isinstance(session_id, str) and len(session_id) == 36):
            try:
                uid = session_id if isinstance(session_id, UUID) else UUID(session_id)
                q = q.where((BrowserSession.id == uid) | (BrowserSession.session_id == str(session_id)))
            except ValueError:
                q = q.where(BrowserSession.session_id == str(session_id))
        else:
            q = q.where(BrowserSession.session_id == str(session_id))
        res = await self.db.execute(q)
        s = res.scalars().first()
        if not s:
            raise BrowserNotFound("Session not found")
        return s

    async def _get_task(self, task_id: str | UUID, organization_id: UUID) -> BrowserTask:
        q = select(BrowserTask).where(BrowserTask.organization_id == organization_id)
        try:
            uid = task_id if isinstance(task_id, UUID) else UUID(str(task_id))
            q = q.where((BrowserTask.id == uid) | (BrowserTask.task_id == str(task_id)))
        except ValueError:
            q = q.where(BrowserTask.task_id == str(task_id))
        res = await self.db.execute(q)
        t = res.scalars().first()
        if not t:
            raise BrowserNotFound("Task not found")
        return t

    # -- sessions ----------------------------------------------------------
    async def create_session(self, *, organization_id: UUID, user_id: Optional[UUID] = None,
                             agent_id: Optional[UUID] = None, workflow_execution_id: Optional[UUID] = None,
                             browser_profile_id: Optional[UUID] = None,
                             provider_config: Optional[dict] = None, headless: Optional[bool] = None,
                             metadata: Optional[dict] = None) -> BrowserSession:
        count = await self.db.scalar(
            select(func.count()).select_from(BrowserSession).where(
                BrowserSession.organization_id == organization_id,
                BrowserSession.status.notin_([BrowserSessionStatus.CLOSED, BrowserSessionStatus.EXPIRED]),
                BrowserSession.deleted_at.is_(None)))
        if (count or 0) >= MAX_SESSIONS_PER_ORG:
            raise BrowserSecurityError(f"Organization session limit exceeded ({MAX_SESSIONS_PER_ORG})")
        if user_id:
            ucount = await self.db.scalar(
                select(func.count()).select_from(BrowserSession).where(
                    BrowserSession.organization_id == organization_id, BrowserSession.user_id == user_id,
                    BrowserSession.status.notin_([BrowserSessionStatus.CLOSED, BrowserSessionStatus.EXPIRED]),
                    BrowserSession.deleted_at.is_(None)))
            if (ucount or 0) >= MAX_SESSIONS_PER_USER:
                raise BrowserSecurityError("User session limit exceeded")

        provider = (provider_config or {}).get("type", "playwright")
        try:
            prov = BrowserProviderType(provider)
        except ValueError:
            prov = BrowserProviderType.playwright
        now = _now()
        session = BrowserSession(
            session_id=_sid("session"), organization_id=organization_id, user_id=user_id,
            agent_id=agent_id, workflow_execution_id=workflow_execution_id,
            browser_profile_id=browser_profile_id, provider=prov,
            provider_config=redact_dict(provider_config or {}),
            status=BrowserSessionStatus.READY, headless=headless if headless is not None else True,
            last_activity_at=now, expires_at=now + SESSION_TIMEOUT, meta=redact_dict(metadata or {}),
        )
        self.db.add(session)
        await self.db.flush()
        ctx = BrowserContext(
            context_id=_sid("ctx"), session_id=session.id, cookies=[], local_storage={},
            session_storage={}, permissions=[], viewport=(provider_config or {}).get("viewport"),
            user_agent=(provider_config or {}).get("user_agent"),
            locale=(provider_config or {}).get("locale"),
            timezone_id=(provider_config or {}).get("timezone_id"),
            proxy=(provider_config or {}).get("proxy"),
            offline=False, storage_state=None,
        )
        self.db.add(ctx)
        await self.db.flush()
        await self._emit(organization_id, "browser.session.created", session_id=session.id)
        await self._emit(organization_id, "browser.session.ready", session_id=session.id)
        await self._audit(organization_id, user_id, "browser.session.created", "browser_session", session.id,
                          {"provider": prov.value})
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def list_sessions(self, *, organization_id: UUID, status: Optional[str] = None,
                            limit: int = 50, offset: int = 0) -> list[BrowserSession]:
        q = select(BrowserSession).where(
            BrowserSession.organization_id == organization_id, BrowserSession.deleted_at.is_(None))
        if status:
            q = q.where(BrowserSession.status == status)
        q = q.order_by(BrowserSession.created_at.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(q)).scalars().all())

    async def get_session(self, session_id: str, organization_id: UUID) -> Optional[BrowserSession]:
        try:
            return await self._get_session(session_id, organization_id)
        except BrowserNotFound:
            return None

    async def update_session(self, session_id: str, organization_id: UUID, status: Optional[str]) -> Optional[BrowserSession]:
        s = await self._get_session(session_id, organization_id)
        if status:
            s.status = BrowserSessionStatus(status)
            s.last_activity_at = _now()
        await self.db.commit()
        await self.db.refresh(s)
        return s

    async def pause_session(self, session_id: str, organization_id: UUID) -> None:
        s = await self._get_session(session_id, organization_id)
        s.status = BrowserSessionStatus.PAUSED
        s.last_activity_at = _now()
        await self.db.commit()

    async def resume_session(self, session_id: str, organization_id: UUID) -> None:
        s = await self._get_session(session_id, organization_id)
        if s.status == BrowserSessionStatus.PAUSED:
            s.status = BrowserSessionStatus.READY
        s.last_activity_at = _now()
        await self.db.commit()

    async def close_session(self, session_id: str, organization_id: UUID, force: bool = False) -> None:
        s = await self._get_session(session_id, organization_id)
        s.status = BrowserSessionStatus.CLOSED
        s.last_activity_at = _now()
        await self._emit(organization_id, "browser.session.closed", session_id=s.id)
        await self._audit(organization_id, s.user_id, "browser.session.terminated", "browser_session", s.id, {})
        await self.db.commit()

    async def heartbeat(self, session_id: str, organization_id: UUID) -> None:
        s = await self._get_session(session_id, organization_id)
        s.last_activity_at = _now()
        await self.db.commit()

    async def acquire_lease(self, session_id: str, organization_id: UUID, holder_id: str,
                            holder_type: str, purpose: str, duration_s: int = 60) -> BrowserSessionLease:
        s = await self._get_session(session_id, organization_id)
        now = _now()
        existing = (await self.db.execute(
            select(BrowserSessionLease).where(BrowserSessionLease.session_id == s.id,
                                              BrowserSessionLease.expires_at > now))).scalars().all()
        for lease in existing:
            if lease.holder_id != holder_id:
                raise BrowserSecurityError(f"Session leased to {lease.holder_id}")
        lease = BrowserSessionLease(lease_id=_sid("lease"), session_id=s.id, holder_id=holder_id,
                                    holder_type=holder_type, acquired_at=now,
                                    expires_at=now + timedelta(seconds=duration_s), purpose=purpose)
        self.db.add(lease)
        await self.db.commit()
        await self.db.refresh(lease)
        return lease

    # -- pages --------------------------------------------------------------
    async def _default_context(self, session: BrowserSession) -> BrowserContext:
        res = await self.db.execute(
            select(BrowserContext).where(BrowserContext.session_id == session.id).limit(1))
        ctx = res.scalars().first()
        if not ctx:
            raise BrowserNotFound("Browser context not found")
        return ctx

    async def create_page(self, *, session_id: str, organization_id: UUID, url: Optional[str] = None,
                          is_popup: bool = False, opener_page_id: Optional[UUID] = None) -> BrowserPage:
        s = await self._get_session(session_id, organization_id)
        if s.status == BrowserSessionStatus.PAUSED:
            raise BrowserSecurityError("Session is paused")
        pages = await self.list_pages(s.session_id, organization_id)
        if len(pages) >= MAX_PAGES_PER_SESSION:
            raise BrowserSecurityError(f"Page limit exceeded ({MAX_PAGES_PER_SESSION})")
        ctx = await self._default_context(s)
        if url:
            policies = await self._policies(organization_id)
            v = validate_url(url, policies)
            if not v.valid:
                await self._emit(organization_id, "browser.policy.denied", session_id=s.id,
                                 payload={"url": sanitize_url(url), "reason": v.reason})
                raise BrowserPolicyDenied(v.reason)
            url = v.sanitized_url or url
        page = BrowserPage(page_id=_sid("page"), session_id=s.id, context_id=ctx.id,
                           url=url or "about:blank", title=None, status="READY",
                           is_popup=is_popup, opener_page_id=opener_page_id,
                           last_activity_at=_now())
        self.db.add(page)
        s.last_activity_at = _now()
        await self.db.flush()
        await self._emit(organization_id, "browser.page.created", session_id=s.id, page_id=page.id,
                         payload={"url": sanitize_url(page.url)})
        await self.db.commit()
        await self.db.refresh(page)
        return page

    async def list_pages(self, session_id: str, organization_id: UUID) -> list[BrowserPage]:
        s = await self._get_session(session_id, organization_id)
        res = await self.db.execute(select(BrowserPage).where(BrowserPage.session_id == s.id))
        return list(res.scalars().all())

    async def close_page(self, session_id: str, page_id: UUID, organization_id: UUID) -> None:
        s = await self._get_session(session_id, organization_id)
        res = await self.db.execute(
            select(BrowserPage).where(BrowserPage.session_id == s.id, BrowserPage.id == page_id))
        p = res.scalars().first()
        if not p:
            raise BrowserNotFound("Page not found")
        p.status = "CLOSED"
        await self._emit(organization_id, "browser.page.closed", session_id=s.id, page_id=p.id)
        await self.db.commit()

    # -- tasks ---------------------------------------------------------------
    async def create_task(self, *, organization_id: UUID, agent_id: Optional[UUID] = None,
                          browser_session_id: UUID, objective: str, max_steps: int = 100,
                          timeout: int = 300000, risk_policy: Optional[dict] = None,
                          metadata: Optional[dict] = None) -> BrowserTask:
        # resolve session (by PK or session_id string)
        res = await self.db.execute(select(BrowserSession).where(BrowserSession.id == browser_session_id))
        session = res.scalars().first()
        if not session:
            res = await self.db.execute(
                select(BrowserSession).where(BrowserSession.session_id == str(browser_session_id)))
            session = res.scalars().first()
        if not session or session.organization_id != organization_id:
            raise BrowserNotFound("Browser session not found")
        task = BrowserTask(
            task_id=_sid("task"), organization_id=organization_id, agent_id=agent_id,
            browser_session_id=session.id, status=BrowserTaskStatus.RUNNING,
            objective=redact_text(objective)[:4000], current_step=0,
            max_steps=min(max_steps, 500), timeout=min(timeout, 3600000),
            risk_policy=risk_policy or {"allowedRiskLevels": ["LOW", "MEDIUM"],
                                        "maxRiskLevel": "MEDIUM",
                                        "requireApprovalFor": ["HIGH", "CRITICAL"],
                                        "blockedActions": []},
            meta=redact_dict(metadata or {}),
        )
        self.db.add(task)
        session.last_activity_at = _now()
        await self.db.flush()
        await self._emit(organization_id, "browser.action.started", session_id=session.id, task_id=task.id,
                         payload={"objective": redact_text(objective)[:500]})
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def list_tasks(self, *, organization_id: UUID, status: Optional[str] = None,
                         browser_session_id: Optional[UUID] = None,
                         limit: int = 50, offset: int = 0) -> list[BrowserTask]:
        q = select(BrowserTask).where(BrowserTask.organization_id == organization_id)
        if status:
            q = q.where(BrowserTask.status == status)
        if browser_session_id:
            q = q.where(BrowserTask.browser_session_id == browser_session_id)
        q = q.order_by(BrowserTask.created_at.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(q)).scalars().all())

    async def get_task(self, task_id: UUID, organization_id: UUID) -> Optional[BrowserTask]:
        try:
            return await self._get_task(task_id, organization_id)
        except BrowserNotFound:
            return None

    async def cancel_task(self, task_id: UUID, organization_id: UUID) -> None:
        t = await self._get_task(task_id, organization_id)
        t.status = BrowserTaskStatus.CANCELLED
        t.completed_at = _now()
        await self._emit(organization_id, "browser.action.failed", task_id=t.id, payload={"reason": "cancelled"})
        await self.db.commit()

    async def pause_task(self, task_id: UUID, organization_id: UUID) -> None:
        t = await self._get_task(task_id, organization_id)
        t.status = BrowserTaskStatus.PAUSED
        await self.db.commit()

    async def resume_task(self, task_id: UUID, organization_id: UUID) -> None:
        t = await self._get_task(task_id, organization_id)
        if t.status == BrowserTaskStatus.PAUSED:
            t.status = BrowserTaskStatus.RUNNING
        await self.db.commit()

    async def request_human(self, task_id: UUID, organization_id: UUID, reason: str) -> BrowserTask:
        t = await self._get_task(task_id, organization_id)
        t.status = BrowserTaskStatus.WAITING_FOR_HUMAN
        await self._emit(organization_id, "browser.human_required", task_id=t.id,
                         payload={"reason": redact_text(reason)[:500]})
        await self.db.commit()
        await self.db.refresh(t)
        return t

    # -- action execution (policy gate; actual CDP driving happens in worker) --
    async def execute_task_action(self, *, task_id: UUID, organization_id: UUID, action_type: str,
                                  page_id: UUID, input_data: dict, approved: bool = False,
                                  approval_id: Optional[UUID] = None) -> dict[str, Any]:
        t = await self._get_task(task_id, organization_id)
        action_type = action_type.upper()
        try:
            atype = BrowserActionType(action_type)
        except ValueError:
            raise BrowserSecurityError(f"Unknown action type: {action_type}")
        if t.status in (BrowserTaskStatus.SUCCEEDED, BrowserTaskStatus.FAILED,
                        BrowserTaskStatus.CANCELLED, BrowserTaskStatus.TIMED_OUT):
            raise BrowserSecurityError(f"Task is already {t.status.value}")
        if t.current_step >= t.max_steps:
            t.status = BrowserTaskStatus.TIMED_OUT
            await self.db.commit()
            raise BrowserSecurityError("Task step budget exhausted")
        risk_policy = t.risk_policy or {}
        if action_type in set(risk_policy.get("blockedActions", [])):
            raise BrowserPolicyDenied(f"Action {action_type} is blocked by task risk policy")
        risk = classify_risk(action_type)
        allowed = set(risk_policy.get("allowedRiskLevels", ["LOW", "MEDIUM"]))
        max_risk = str(risk_policy.get("maxRiskLevel", "MEDIUM"))
        order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        risk_gate = risk not in allowed or order.index(risk) > order.index(max_risk)
        explicit_gate = requires_approval(action_type, risk_policy)
        if risk_gate or explicit_gate:
            # MP19: a client boolean is never proof of approval. Execution
            # requires a persisted, human-granted approval bound to this exact
            # action (verified via ApprovalEngine.begin_execution).
            verified = False
            if approval_id is not None:
                from openagent.approvals.integrations import consume_approval
                ok, _ = await consume_approval(
                    self.db, approval_id=approval_id, organization_id=organization_id,
                    action_type=f"browser.{action_type.lower()}",
                    action_category="BROWSER_EXTERNAL_ACTION",
                    target_type="browser_task", target_id=str(t.id),
                    params={"action": action_type, "page_id": str(page_id)},
                    environment="development")
                verified = ok
            if not verified:
                from openagent.approvals.integrations import park_for_approval
                parked = await park_for_approval(
                    self.db, organization_id=organization_id,
                    action_type=f"browser.{action_type.lower()}",
                    action_category="BROWSER_EXTERNAL_ACTION",
                    target_type="browser_task", target_id=str(t.id),
                    params={"action": action_type, "page_id": str(page_id)},
                    environment="development",
                    impact_summary=f"Browser action {action_type} (risk={risk})",
                    requester_type="agent", task_id=str(t.id))
                await self._emit(organization_id, "browser.policy.denied", task_id=t.id,
                                 payload={"action": action_type, "risk": risk,
                                          "approval_id": str(parked.id) if parked else None})
                if approved:
                    logger.warning("browser.approval.boolean_ignored",
                                   task_id=str(t.id), action=action_type)
                reason = ("risk policy" if risk_gate else "approval_required")
                return {"success": False, "requiresApproval": True, "riskLevel": risk,
                        "approval_id": str(parked.id) if parked else None,
                        "status": "WAITING_FOR_APPROVAL",
                        "reason": reason,
                        "message": f"Action {action_type} (risk={risk}) requires human approval"}

        res = await self.db.execute(select(BrowserPage).where(BrowserPage.id == page_id))
        page = res.scalars().first()
        if not page:
            raise BrowserNotFound("Page not found")
        sres = await self.db.execute(select(BrowserSession).where(BrowserSession.id == page.session_id))
        session = sres.scalars().first()
        if not session or session.organization_id != organization_id:
            raise BrowserSecurityError("Cross-tenant page access denied")

        clean_input = redact_dict(dict(input_data or {}))
        # Navigation policy gate
        if action_type == "NAVIGATE":
            url = str(input_data.get("url", ""))
            policies = await self._policies(organization_id)
            v = validate_url(url, policies)
            if not v.valid:
                await self._emit(organization_id, "browser.policy.denied", session_id=session.id,
                                 task_id=t.id, page_id=page.id,
                                 payload={"url": sanitize_url(url), "reason": v.reason})
                raise BrowserPolicyDenied(v.reason)
            if v.policy_action == "CONFIRM" and not approved:
                return {"success": False, "requiresApproval": True, "riskLevel": risk,
                        "message": f"Domain requires confirmation: {sanitize_url(url)}"}
            clean_input["url"] = v.sanitized_url
        # Credential boundary: only references, never raw secrets
        if action_type in ("AUTHENTICATE", "FILL", "TYPE"):
            for fk in ("password", "secret", "token", "api_key"):
                if fk in input_data and not str(fk).endswith("_ref"):
                    logger.warning("browser.credential.raw_rejected",
                                   task_id=t.task_id, field=fk)
                    clean_input[fk] = "[REDACTED]"
        # Upload hardening
        if action_type in ("UPLOAD", "SET_INPUT_FILES"):
            for f in (input_data.get("files") or []):
                name = str(f.get("name", ""))
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext in BLOCKED_UPLOAD_EXTS:
                    raise BrowserPolicyDenied(f"Upload blocked: extension {ext}")
                if int(f.get("size", 0)) > MAX_UPLOAD_BYTES:
                    raise BrowserPolicyDenied("Upload exceeds size limit")

        action = BrowserAction(
            action_id=_sid("action"), task_id=t.id, session_id=session.id, page_id=page.id,
            type=atype, input=clean_input, risk_level=risk, status="PENDING", retry_count=0,
            idempotency_key=str(input_data.get("idempotencyKey") or input_data.get("idempotency_key") or ""),
            created_at=_now(),
        )
        if action.idempotency_key:
            dup = await self.db.scalar(select(func.count()).select_from(BrowserAction).where(
                BrowserAction.task_id == t.id, BrowserAction.idempotency_key == action.idempotency_key))
            if dup:
                return {"success": False, "duplicate": True, "message": "Duplicate action (idempotency key seen)"}
        self.db.add(action)
        t.current_step += 1
        t.current_page_id = page.id
        if action_type == "NAVIGATE":
            t.current_url = str(clean_input.get("url", ""))
            page.url = t.current_url
        session.last_activity_at = _now()
        page.last_activity_at = _now()
        await self.db.flush()
        await self._emit(organization_id, "browser.action.started", session_id=session.id,
                         task_id=t.id, page_id=page.id,
                         payload={"action": action_type, "risk": risk})
        # NOTE: real CDP execution is performed by the worker/browser-uplink.
        # Record queued intent; mark retry-safe reads as succeeded with empty observation
        # so agent loops can proceed; mutating actions stay PENDING for the worker.
        if is_retry_safe(action_type):
            action.status = "SUCCEEDED"
            action.result = {"queued": False, "note": "validated read-only action"}
            action.completed_at = _now()
        else:
            action.status = "PENDING"
            action.result = {"queued": True, "retrySafe": False,
                             "note": "queued for browser worker; will not auto-replay after crash"}
        await self._emit(organization_id, "browser.action.completed", session_id=session.id,
                         task_id=t.id, page_id=page.id,
                         payload={"action": action_type, "status": action.status})
        await self.db.commit()
        await self.db.refresh(action)
        return {"success": True, "actionId": action.action_id, "status": action.status,
                "riskLevel": risk, "retrySafe": is_retry_safe(action_type),
                "result": action.result or {}}

    async def record_observation(self, *, task_id: UUID, organization_id: UUID, action_id: Optional[UUID],
                                 url: str, title: str = "",
                                 elements: Optional[list] = None, text: str = "",
                                 strategy: str = "standard") -> dict[str, Any]:
        t = await self._get_task(task_id, organization_id)
        elements = elements or []
        injections = detect_prompt_injection(f"{title}\n{text}")
        challenge = detect_challenge(text, title)
        obs = BrowserObservation(
            task_id=t.id, action_id=action_id, url=sanitize_url(url)[:2000], title=title[:500],
            interactive_elements=elements[:200], text_content=redact_text(text)[:50000],
            meta={"strategy": strategy, "promptInjectionSignals": len(injections),
                  "challenge": challenge}, created_at=_now(),
        )
        self.db.add(obs)
        fp = fingerprint_state(url, title, text, elements)
        self.db.add(BrowserStateFingerprint(task_id=t.id, url=url[:2000], title=title[:500],
                                            text_hash=fp["text_hash"], dom_hash=fp["dom_hash"],
                                            interactive_elements_hash=fp["interactive_elements_hash"],
                                            timestamp=_now()))
        if challenge:
            t.status = BrowserTaskStatus.WAITING_FOR_HUMAN
            await self._emit(organization_id, "browser.challenge.detected", task_id=t.id,
                             payload={"challenge": challenge})
        # loop detection
        fps = (await self.db.execute(
            select(BrowserStateFingerprint).where(BrowserStateFingerprint.task_id == t.id)
            .order_by(BrowserStateFingerprint.timestamp.desc()).limit(10))).scalars().all()
        loop = detect_loop([{"url": f.url, "dom_hash": f.dom_hash,
                             "interactive_elements_hash": f.interactive_elements_hash} for f in fps])
        compressed = compress_observation(url, title,
                                          [e for e in elements if isinstance(e, dict)],
                                          label_untrusted(text) if injections else text,
                                          strategy=strategy)  # type: ignore[arg-type]
        await self.db.commit()
        return {"observation": compressed, "promptInjectionDetected": bool(injections),
                "signals": injections[:5], "challenge": challenge, "loop": loop}

    # -- profiles -------------------------------------------------------------
    async def create_profile(self, *, organization_id: UUID, owner_id: UUID, display_name: str,
                             browser_type: str = "chromium", profile_type: str = "EPHEMERAL",
                             storage_state: Optional[dict] = None, policy: Optional[dict] = None) -> BrowserProfile:
        from openagent.db.models.browser import BrowserProfileType as PT, BrowserType as BT
        if profile_type != "EPHEMERAL" and not policy:
            raise BrowserSecurityError("Persistent profiles require explicit policy authorization")
        p = BrowserProfile(organization_id=organization_id, owner_id=owner_id,
                           display_name=display_name[:255],
                           browser_type=BT(browser_type), profile_type=PT(profile_type),
                           storage_state=storage_state, policy=policy or {})
        self.db.add(p)
        await self.db.flush()
        await self._audit(organization_id, owner_id, "browser.profile.created", "browser_profile", p.id,
                          {"profile_type": profile_type})
        await self.db.commit()
        await self.db.refresh(p)
        return p

    async def list_profiles(self, organization_id: UUID) -> list[BrowserProfile]:
        res = await self.db.execute(select(BrowserProfile).where(
            BrowserProfile.organization_id == organization_id, BrowserProfile.deleted_at.is_(None)))
        return list(res.scalars().all())

    async def get_profile(self, profile_id: UUID, organization_id: UUID) -> Optional[BrowserProfile]:
        res = await self.db.execute(select(BrowserProfile).where(
            BrowserProfile.id == profile_id, BrowserProfile.organization_id == organization_id,
            BrowserProfile.deleted_at.is_(None)))
        return res.scalars().first()

    async def update_profile(self, profile_id: UUID, organization_id: UUID, patch: dict) -> Optional[BrowserProfile]:
        p = await self.get_profile(profile_id, organization_id)
        if not p:
            return None
        patch = dict(patch)
        patch.pop("storage_state", None)  # storage state rotation via dedicated flow only
        for k in ("display_name", "policy"):
            if k in patch:
                setattr(p, k, patch[k])
        await self.db.commit()
        await self.db.refresh(p)
        return p

    async def delete_profile(self, profile_id: UUID, organization_id: UUID) -> None:
        p = await self.get_profile(profile_id, organization_id)
        if p:
            from datetime import timezone as _tz
            p.deleted_at = datetime.now(_tz.utc)
            await self.db.commit()

    # -- domain policies --------------------------------------------------------
    async def create_domain_policy(self, *, organization_id: UUID, domain: str, action: str = "ALLOW",
                                   priority: int = 0, reason: Optional[str] = None) -> BrowserDomainPolicy:
        from openagent.db.models.browser import BrowserDomainPolicyAction as A
        pol = BrowserDomainPolicy(organization_id=organization_id, domain=domain.lower().strip(),
                                  action=A(action), priority=priority, reason=reason)
        self.db.add(pol)
        await self.db.flush()
        await self._audit(organization_id, None, "browser.policy.created", "browser_domain_policy", pol.id,
                          {"domain": domain, "action": action})
        await self.db.commit()
        await self.db.refresh(pol)
        return pol

    async def list_domain_policies(self, organization_id: UUID) -> list[BrowserDomainPolicy]:
        res = await self.db.execute(select(BrowserDomainPolicy).where(
            (BrowserDomainPolicy.organization_id == organization_id)
            | (BrowserDomainPolicy.organization_id.is_(None))))
        return list(res.scalars().all())

    async def update_domain_policies(self, organization_id: UUID, policies: list[dict]) -> None:
        existing = await self.list_domain_policies(organization_id)
        for e in existing:
            if e.organization_id == organization_id:
                await self.db.delete(e)
        for p in policies:
            from openagent.db.models.browser import BrowserDomainPolicyAction as A
            self.db.add(BrowserDomainPolicy(
                organization_id=organization_id, domain=str(p["domain"]).lower().strip(),
                action=A(p.get("action", "ALLOW")), priority=int(p.get("priority", 0)),
                reason=p.get("reason")))
        await self.db.commit()

    async def get_session_events(self, session_id: str, organization_id: UUID, limit: int = 100) -> list[BrowserEvent]:
        s = await self._get_session(session_id, organization_id)
        res = await self.db.execute(select(BrowserEvent).where(
            BrowserEvent.session_id == s.id, BrowserEvent.organization_id == organization_id)
            .order_by(BrowserEvent.timestamp.desc()).limit(min(limit, 500)))
        return list(res.scalars().all())

    # -- artifacts ----------------------------------------------------------------
    async def create_artifact(self, *, organization_id: UUID, name: str, type: str, size: int,
                              mime_type: str, storage_ref: str,
                              task_id: Optional[UUID] = None, session_id: Optional[UUID] = None,
                              expires_at: Optional[datetime] = None) -> BrowserArtifact:
        from openagent.db.models.browser import BrowserArtifactType as AT
        if size > MAX_DOWNLOAD_BYTES:
            raise BrowserSecurityError("Artifact exceeds size limit")
        a = BrowserArtifact(artifact_id=_sid("art"), organization_id=organization_id, task_id=task_id,
                            session_id=session_id, type=AT(type), name=name[:255], size=size,
                            mime_type=mime_type, storage_ref=storage_ref, meta={},
                            created_at=_now(), expires_at=expires_at)
        self.db.add(a)
        await self.db.flush()
        await self._emit(organization_id, "browser.artifact.created", session_id=session_id,
                         task_id=task_id, payload={"artifact": a.artifact_id, "type": type, "size": size})
        await self.db.commit()
        await self.db.refresh(a)
        return a


async def sweep_expired_sessions(db: AsyncSession) -> dict[str, int]:
    """Scheduler/worker hook: expire timed-out or idle sessions, fail stale tasks.

    Crash recovery rule: only retry-safe *reads* may be re-driven; mutating
    actions left PENDING are marked FAILED (never silently replayed) so an
    operator can decide explicitly.
    """
    from openagent.browser.security import is_retry_safe

    now = _now()
    expired = (await db.execute(select(BrowserSession).where(
        BrowserSession.deleted_at.is_(None),
        BrowserSession.status.notin_([BrowserSessionStatus.CLOSED, BrowserSessionStatus.EXPIRED]),
        ((BrowserSession.expires_at <= now)
         | (BrowserSession.last_activity_at <= now - SESSION_IDLE_TIMEOUT))))).scalars().all()
    sessions = 0
    for s in expired:
        s.status = BrowserSessionStatus.EXPIRED
        db.add(BrowserEvent(event_id=_sid("evt"), type="browser.session.expired",
                            organization_id=s.organization_id, session_id=s.id,
                            payload={}, meta={}, timestamp=now))
        sessions += 1
    stale_tasks = (await db.execute(select(BrowserTask).where(
        BrowserTask.status.in_([BrowserTaskStatus.RUNNING, BrowserTaskStatus.STARTING]),
        BrowserTask.updated_at <= now - timedelta(minutes=30)))).scalars().all()
    tasks = 0
    for t in stale_tasks:
        pending = (await db.execute(select(BrowserAction).where(
            BrowserAction.task_id == t.id, BrowserAction.status == "PENDING"))).scalars().all()
        unsafe = [a for a in pending
                  if not is_retry_safe(str(a.type.value if hasattr(a.type, "value") else a.type))]
        for a in pending:
            a.status = "FAILED"
            a.error = {"code": "WORKER_LOST",
                       "message": "Browser worker lost; unsafe actions are never auto-replayed" if a in unsafe
                       else "Browser worker lost; re-drive explicitly",
                       "retryable": False}
            a.completed_at = now
        t.status = BrowserTaskStatus.FAILED
        t.completed_at = now
        db.add(BrowserEvent(event_id=_sid("evt"), type="browser.session.crashed",
                            organization_id=t.organization_id, task_id=t.id,
                            payload={"unsafePending": len(unsafe)}, meta={}, timestamp=now))
        tasks += 1
    await db.commit()
    logger.info("browser.sweep", sessions=sessions, tasks=tasks)
    return {"sessions": sessions, "tasks": tasks}
