import pytest
import pytest_asyncio
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openagent.db.models import (
    ScheduledJob, ScheduledJobRun, ScheduleStatus, ScheduleTriggerType,
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
)
from openagent.core.scheduler import SchedulerService, ScheduleConfig


@pytest_asyncio.fixture
async def org(db_session: AsyncSession):
    org = Organization(
        name="Test Org Scheduler",
        slug="test-org-scheduler",
        status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org):
    from openagent.db.repositories import UserRepository, MembershipRepository
    from openagent.db.models import Membership, MembershipRole, MembershipStatus
    from openagent.core.security import hash_password
    
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        email="test-scheduler@example.com",
        display_name="Test User",
        password_hash="hashed_password",
        status=UserStatus.ACTIVE,
        email_verified=True,
    )
    
    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def scheduler_service(db_session: AsyncSession):
    return SchedulerService(db_session)


class TestSchedulerService:
    async def test_create_one_time_job(self, db_session: AsyncSession, org, user, scheduler_service):
        config = ScheduleConfig(
            trigger_type="one_time",
            run_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        
        job = await scheduler_service.create_job(
            organization_id=org.id,
            name="One-time Job",
            job_type="test_job",
            payload={"action": "test"},
            config=config,
        )
        
        assert job.id is not None
        assert job.name == "One-time Job"
        assert job.job_type == "test_job"
        assert job.trigger_type == "one_time"
        assert job.run_at is not None
        assert job.next_run_at is not None
        assert job.status == "active"

    async def test_create_interval_job(self, db_session: AsyncSession, org, user, scheduler_service):
        config = ScheduleConfig(
            trigger_type="interval",
            interval_seconds=3600,  # 1 hour
        )
        
        job = await scheduler_service.create_job(
            organization_id=org.id,
            name="Interval Job",
            job_type="interval_job",
            payload={"action": "repeat"},
            config=config,
        )
        
        assert job.id is not None
        assert job.trigger_type == "interval"
        assert job.interval_seconds == 3600
        assert job.next_run_at is not None

    async def test_create_cron_job(self, db_session: AsyncSession, org, user, scheduler_service):
        config = ScheduleConfig(
            trigger_type="cron",
            cron_expression="0 * * * *",  # Every hour
            timezone="UTC",
        )
        
        job = await scheduler_service.create_job(
            organization_id=org.id,
            name="Cron Job",
            job_type="cron_job",
            payload={"action": "cron"},
            config=config,
        )
        
        assert job.id is not None
        assert job.trigger_type == "cron"
        assert job.cron_expression == "0 * * * *"

    async def test_create_job_invalid_cron(self, db_session: AsyncSession, org, user, scheduler_service):
        config = ScheduleConfig(
            trigger_type="cron",
            cron_expression="invalid cron",
        )
        
        with pytest.raises(Exception):
            await scheduler_service.create_job(
                organization_id=org.id,
                name="Invalid Cron",
                job_type="bad_cron",
                payload={},
                config=config,
            )

    async def test_update_job(self, db_session: AsyncSession, org, user, scheduler_service):
        config = ScheduleConfig(
            trigger_type="interval",
            interval_seconds=3600,
        )
        
        job = await scheduler_service.create_job(
            organization_id=org.id,
            name="Original Name",
            job_type="update_test",
            payload={},
            config=config,
        )
        
        # Update job
        updated = await scheduler_service.update_job(
            job_id=job.id,
            organization_id=org.id,
            name="Updated Name",
            description="Updated description",
        )
        
        assert updated.name == "Updated Name"
        assert updated.description == "Updated description"
        
        # Update status
        paused = await scheduler_service.update_job(
            job_id=job.id,
            organization_id=org.id,
            status="paused",
        )
        
        assert paused.status == "paused"

    async def test_delete_job(self, db_session: AsyncSession, org, user, scheduler_service):
        config = ScheduleConfig(
            trigger_type="one_time",
            run_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        
        job = await scheduler_service.create_job(
            organization_id=org.id,
            name="To Delete",
            job_type="delete_test",
            payload={},
            config=config,
        )
        
        success = await scheduler_service.delete_job(job.id, org.id)
        assert success is True
        
        # Verify soft delete
        result = await db_session.execute(
            select(ScheduledJob).where(ScheduledJob.id == job.id)
        )
        deleted = result.scalar_one_or_none()
        assert deleted.status == "deleted"

    async def test_list_jobs(self, db_session: AsyncSession, org, user, scheduler_service):
        # Create multiple jobs
        for i in range(5):
            config = ScheduleConfig(
                trigger_type="interval",
                interval_seconds=3600 * (i + 1),
            )
            await scheduler_service.create_job(
                organization_id=org.id,
                name=f"Job {i}",
                job_type=f"type_{i}",
                payload={},
                config=config,
            )
        
        jobs = await scheduler_service.list_jobs(organization_id=org.id, limit=10)
        assert len(jobs) == 5
        
        # Filter by status
        active_jobs = await scheduler_service.list_jobs(
            organization_id=org.id,
            status=ScheduleStatus.ACTIVE,
        )
        assert len(active_jobs) == 5
        
        # Filter by job type
        type_jobs = await scheduler_service.list_jobs(
            organization_id=org.id,
            job_type="type_0",
        )
        assert len(type_jobs) == 1
        assert type_jobs[0].job_type == "type_0"

    async def test_trigger_job_manually(self, db_session: AsyncSession, org, user, scheduler_service):
        # Register handler
        called = []
        
        async def handler(payload):
            called.append(payload)
            return {"result": "ok"}
        
        scheduler_service.register_handler("manual_test", handler)
        
        config = ScheduleConfig(
            trigger_type="one_time",
            run_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        
        job = await scheduler_service.create_job(
            organization_id=org.id,
            name="Manual Trigger",
            job_type="manual_test",
            payload={"test": "data"},
            config=config,
        )
        
        # Trigger manually
        run = await scheduler_service.trigger_job(job.id, org.id)
        
        assert run is not None
        assert run.job_id == job.id
        assert run.status == "completed"
        assert len(called) == 1
        assert called[0]["test"] == "data"

    async def test_job_retry_logic(self, db_session: AsyncSession, org, user, scheduler_service):
        attempt_count = []
        
        async def failing_handler(payload):
            attempt_count.append(1)
            if len(attempt_count) < 3:
                raise Exception("Temporary failure")
            return {"success": True}
        
        scheduler_service.register_handler("retry_test", failing_handler)
        
        config = ScheduleConfig(
            trigger_type="one_time",
            run_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            max_retries=3,
            retry_delay_seconds=1,
        )
        
        job = await scheduler_service.create_job(
            organization_id=org.id,
            name="Retry Test",
            job_type="retry_test",
            payload={},
            config=config,
        )
        
        await db_session.commit()
        
        # Trigger the job - it will fail and retry
        run = await scheduler_service.trigger_job(job.id, org.id)
        
        # Wait for retries
        await asyncio.sleep(5)
        
        # Check run status
        result = await db_session.execute(
            select(ScheduledJobRun).where(ScheduledJobRun.job_id == job.id)
            .order_by(ScheduledJobRun.attempt.desc())
        )
        latest_run = result.scalar_one_or_none()
        
        # Should have retried
        assert latest_run is not None


class TestScheduledJobModel:
    async def test_scheduled_job_model(self, db_session: AsyncSession, org):
        from openagent.db.models import ScheduledJob, ScheduleStatus, ScheduleTriggerType
        
        job = ScheduledJob(
            organization_id=org.id,
            name="Test Job",
            job_type="test",
            payload={"key": "value"},
            trigger_type=ScheduleTriggerType.INTERVAL,
            interval_seconds=3600,
            status=ScheduleStatus.ACTIVE,
            next_run_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)
        
        assert job.id is not None
        assert job.name == "Test Job"
        assert job.trigger_type == ScheduleTriggerType.INTERVAL
        assert job.interval_seconds == 3600
        assert job.status == ScheduleStatus.ACTIVE

    async def test_scheduled_job_run_model(self, db_session: AsyncSession, org):
        from openagent.db.models import ScheduledJob, ScheduledJobRun, ScheduleStatus, ScheduleTriggerType, ScheduleRunStatus
        
        job = ScheduledJob(
            organization_id=org.id,
            name="Test Job",
            job_type="test",
            payload={},
            trigger_type=ScheduleTriggerType.ONE_TIME,
            run_at=datetime.now(timezone.utc) + timedelta(hours=1),
            status=ScheduleStatus.ACTIVE,
        )
        db_session.add(job)
        await db_session.flush()
        
        run = ScheduledJobRun(
            job_id=job.id,
            status=ScheduleRunStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            attempt=1,
        )
        db_session.add(run)
        await db_session.commit()
        
        assert run.id is not None
        assert run.job_id == job.id
        assert run.status == ScheduleRunStatus.RUNNING
        assert run.attempt == 1


class TestScheduleConfig:
    def test_schedule_config_one_time(self):
        config = ScheduleConfig(
            trigger_type="one_time",
            run_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        
        assert config.trigger_type == "one_time"
        assert config.run_at is not None
        assert config.interval_seconds is None

    def test_schedule_config_interval(self):
        config = ScheduleConfig(
            trigger_type="interval",
            interval_seconds=3600,
        )
        
        assert config.trigger_type == "interval"
        assert config.interval_seconds == 3600
        assert config.run_at is None

    def test_schedule_config_cron(self):
        config = ScheduleConfig(
            trigger_type="cron",
            cron_expression="0 * * * *",
            timezone="America/New_York",
        )
        
        assert config.trigger_type == "cron"
        assert config.cron_expression == "0 * * * *"
        assert config.timezone == "America/New_York"

    def test_default_values(self):
        config = ScheduleConfig(
            trigger_type="interval",
            interval_seconds=3600,
        )
        
        assert config.timezone == "UTC"
        assert config.max_concurrent == 1
        assert config.timeout_seconds == 300
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 60


from datetime import datetime, timezone, timedelta