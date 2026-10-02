#!/usr/bin/env python3
"""
RBAC seed script for OpenAgent database.
Run after migrations to populate default permissions and system roles.
"""
import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from openagent.db.session import Base
from openagent.db.models import (
    Permission, PermissionAction, PermissionResource, PermissionScope,
    Role, RoleType, RolePermission,
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
    PlatformOwner, PlatformOwnerStatus,
)
from openagent.core.security import hash_password
from openagent.core.config import get_settings


async def seed_rbac():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        # Check if permissions already exist
        result = await session.execute(select(Permission).limit(1))
        if result.scalar_one_or_none():
            print("RBAC data already exists, skipping seed")
            return
        
        print("Seeding RBAC permissions and roles...")
        
        # Create all permissions
        permissions = {}
        for perm_data in Permission.get_default_permissions():
            perm = Permission(
                id=uuid.uuid4(),
                name=perm_data["name"],
                resource=PermissionResource(perm_data["resource"]),
                action=PermissionAction(perm_data["action"]),
                scope=PermissionScope(perm_data.get("scope", "organization")),
                description=perm_data["description"],
                is_system=perm_data["is_system"],
                danger_level=perm_data["danger_level"],
            )
            session.add(perm)
            permissions[perm_data["name"]] = perm
        
        await session.flush()
        print(f"Created {len(permissions)} permissions")
        
        # Create system roles
        roles = {}
        for role_data in Role.get_default_roles():
            role = Role(
                id=uuid.uuid4(),
                organization_id=None,  # System roles have no organization
                name=role_data["name"],
                display_name=role_data["display_name"],
                description=role_data["description"],
                role_type=RoleType.SYSTEM,
                is_system=True,
                priority=role_data["priority"],
            )
            session.add(role)
            roles[role_data["name"]] = role
        
        await session.flush()
        print(f"Created {len(roles)} system roles")
        
        # Assign permissions to roles
        for role_data in Role.get_default_roles():
            role = roles[role_data["name"]]
            for perm_name in role_data["permissions"]:
                if perm_name in permissions:
                    rp = RolePermission(
                        role_id=role.id,
                        permission_id=permissions[perm_name].id,
                    )
                    session.add(rp)
        
        await session.commit()
        print("Assigned permissions to roles")
        
        print("RBAC seed completed successfully!")


if __name__ == "__main__":
    asyncio.run(seed_rbac())