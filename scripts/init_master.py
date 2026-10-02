#!/usr/bin/env python3
"""
Master account initialization script for OpenAgent.
Run this script to securely initialize the platform master account.
"""
import asyncio
import getpass
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from openagent.db.session import Base
from openagent.db.models import (
    User, UserStatus,
    PlatformOwner, PlatformOwnerStatus,
)
from openagent.core.security import hash_password
from openagent.core.config import get_settings


async def initialize_master_account():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        # Check if master account already exists
        from sqlalchemy import select
        result = await session.execute(
            select(PlatformOwner)
            .join(User, PlatformOwner.user_id == User.id)
            .where(PlatformOwner.status == PlatformOwnerStatus.ACTIVE)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            print("❌ Master account already exists!")
            print(f"   User ID: {existing.user_id}")
            return False
        
        print("🔐 OpenAgent Master Account Initialization")
        print("=" * 50)
        
        # Get master account details
        if settings.MASTER_ACCOUNT_EMAIL:
            email = settings.MASTER_ACCOUNT_EMAIL
            print(f"📧 Email: {email} (from environment)")
        else:
            email = input("📧 Master account email: ").strip().lower()
        
        if not email:
            print("❌ Email is required")
            return False
        
        if settings.MASTER_ACCOUNT_PASSWORD:
            password = settings.MASTER_ACCOUNT_PASSWORD
            print("🔑 Password: [from environment]")
        else:
            while True:
                password = getpass.getpass("🔑 Master account password (min 10 chars): ")
                confirm = getpass.getpass("🔑 Confirm password: ")
                
                if password != confirm:
                    print("❌ Passwords do not match. Try again.")
                    continue
                
                if len(password) < 10:
                    print("❌ Password must be at least 10 characters. Try again.")
                    continue
                
                break
        
        if settings.MASTER_ACCOUNT_DISPLAY_NAME:
            display_name = settings.MASTER_ACCOUNT_DISPLAY_NAME
            print(f"👤 Display name: {display_name} (from environment)")
        else:
            display_name = input("👤 Display name [Platform Owner]: ").strip() or "Platform Owner"
        
        print("\n🔄 Creating master account...")
        
        # Create master user
        password_hash = hash_password(password)
        
        user = User(
            id=uuid.uuid4(),
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
            email_verified=True,
            is_superadmin=True,
        )
        session.add(user)
        await session.flush()
        
        # Create platform owner record
        platform_owner = PlatformOwner(
            id=uuid.uuid4(),
            user_id=user.id,
            status=PlatformOwnerStatus.ACTIVE,
            mfa_enabled=False,
        )
        session.add(platform_owner)
        
        await session.commit()
        
        print("✅ Master account created successfully!")
        print(f"   User ID: {user.id}")
        print(f"   Email: {user.email}")
        print(f"   Display Name: {user.display_name}")
        print(f"   Super Admin: {user.is_superadmin}")
        print(f"   Email Verified: {user.email_verified}")
        print()
        print("⚠️  IMPORTANT SECURITY NOTES:")
        print("   1. Save the master account credentials securely")
        print("   2. Enable MFA as soon as possible after first login")
        print("   3. Do not share master credentials with anyone")
        print("   4. Use this account only for platform administration")
        print()
        print("🚀 You can now log in at /login with the master credentials")
        
        return True


async def reset_master_account():
    """Emergency master account reset (use with extreme caution)."""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        from sqlalchemy import select, delete
        
        print("⚠️  EMERGENCY MASTER ACCOUNT RESET")
        print("This will DELETE the existing master account!")
        print("=" * 50)
        
        confirm = input("Type 'RESET MASTER' to confirm: ").strip()
        if confirm != "RESET MASTER":
            print("❌ Reset cancelled")
            return False
        
        # Delete existing platform owner and user
        result = await session.execute(
            select(PlatformOwner)
            .join(User, PlatformOwner.user_id == User.id)
            .where(PlatformOwner.status == PlatformOwnerStatus.ACTIVE)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            user_id = existing.user_id
            await session.execute(delete(PlatformOwner).where(PlatformOwner.user_id == user_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            print("✅ Existing master account deleted")
        else:
            print("ℹ️  No existing master account found")
        
        return True


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        asyncio.run(reset_master_account())
    else:
        asyncio.run(initialize_master_account())