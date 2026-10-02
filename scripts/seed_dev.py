#!/usr/bin/env python3
"""
Development seed script for OpenAgent database.
Run after migrations to populate development data.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from openagent.db.session import Base
from openagent.db.models import (
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
    Agent, AgentVersion, AgentType, AgentStatus,
    Workflow, WorkflowVersion, WorkflowStatus,
    ApiKey,
)
from openagent.core.config import get_settings


async def seed_database():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        # Create development organization
        org = Organization(
            id=uuid.uuid4(),
            name="Development Organization",
            slug="development",
            description="Development organization for testing",
            status=OrganizationStatus.ACTIVE,
            settings={"environment": "development"},
        )
        session.add(org)
        
        # Create development user
        user = User(
            id=uuid.uuid4(),
            email="dev@openagent.local",
            display_name="Development User",
            status=UserStatus.ACTIVE,
            is_superadmin=True,
        )
        session.add(user)
        
        await session.flush()
        
        # Create membership
        membership = Membership(
            id=uuid.uuid4(),
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
        session.add(membership)
        
        # Create sample agent
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Sample Chat Agent",
            slug="sample-chat-agent",
            description="A sample chat agent for development",
            status=AgentStatus.ACTIVE,
            agent_type=AgentType.CHAT,
            metadata={"model": "gpt-4", "temperature": 0.7},
        )
        session.add(agent)
        
        await session.flush()
        
        # Create agent version
        agent_version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=agent.id,
            version="1.0.0",
            name="Initial Version",
            instructions="You are a helpful assistant.",
            configuration={"model": "gpt-4", "temperature": 0.7, "max_tokens": 2000},
            status="published",
            created_by=user.id,
        )
        session.add(agent_version)
        
        # Create sample workflow
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Sample Workflow",
            slug="sample-workflow",
            description="A sample workflow for development",
            status=WorkflowStatus.ACTIVE,
            metadata={"trigger": "manual"},
        )
        session.add(workflow)
        
        await session.flush()
        
        # Create workflow version
        workflow_version = WorkflowVersion(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            version="1.0.0",
            definition={
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {"id": "agent", "type": "agent", "config": {"agent_id": str(agent.id)}},
                    {"id": "end", "type": "end", "config": {}}
                ],
                "edges": [
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "end"}
                ]
            },
            status="published",
            created_by=user.id,
        )
        session.add(workflow_version)
        
        # Create development API key
        api_key = ApiKey(
            id=uuid.uuid4(),
            name="Development API Key",
            key_hash="dev_key_hash_placeholder",
            key_prefix="oa_dev",
            user_id=user.id,
            organization_id=org.id,
            permissions=["read", "write", "admin"],
        )
        session.add(api_key)
        
        await session.commit()
        print("Development seed data created successfully!")
        print(f"Organization: {org.name} ({org.slug})")
        print(f"User: {user.email}")
        print(f"Agent: {agent.name} ({agent.slug})")
        print(f"Workflow: {workflow.name} ({workflow.slug})")
        print(f"API Key: {api_key.name} ({api_key.key_prefix})")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_database())