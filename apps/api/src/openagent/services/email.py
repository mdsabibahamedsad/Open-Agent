from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel, EmailStr


class EmailMessage(BaseModel):
    to: EmailStr
    subject: str
    html_content: str
    text_content: Optional[str] = None
    from_email: Optional[EmailStr] = None
    from_name: Optional[str] = None
    reply_to: Optional[EmailStr] = None


class EmailProvider(ABC):
    """Abstract base class for email providers."""
    
    @abstractmethod
    async def send(self, message: EmailMessage) -> bool:
        """Send an email. Returns True if successful."""
        pass
    
    @abstractmethod
    async def send_batch(self, messages: list[EmailMessage]) -> list[bool]:
        """Send multiple emails. Returns list of success statuses."""
        pass


class DevelopmentEmailProvider(EmailProvider):
    """Development email provider that logs emails to console."""
    
    async def send(self, message: EmailMessage) -> bool:
        print(f"\n{'='*60}")
        print(f"DEVELOPMENT EMAIL")
        print(f"{'='*60}")
        print(f"To: {message.to}")
        print(f"Subject: {message.subject}")
        print(f"From: {message.from_name or ''} <{message.from_email or 'noreply@openagent.local'}>")
        print(f"Reply-To: {message.reply_to or 'noreply@openagent.local'}")
        print(f"Text Content:")
        print(f"{message.text_content or message.html_content}")
        print(f"{'='*60}\n")
        return True
    
    async def send_batch(self, messages: list[EmailMessage]) -> list[bool]:
        results = []
        for message in messages:
            result = await self.send(message)
            results.append(result)
        return results


class SMTPEmailProvider(EmailProvider):
    """SMTP email provider for production use."""
    
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool = True,
        default_from_email: str = "noreply@openagent.local",
        default_from_name: str = "OpenAgent",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.default_from_email = default_from_email
        self.default_from_name = default_from_name
    
    async def send(self, message: EmailMessage) -> bool:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = message.subject
            msg["From"] = f"{message.from_name or self.default_from_name} <{message.from_email or self.default_from_email}>"
            msg["To"] = message.to
            
            if message.reply_to:
                msg["Reply-To"] = message.reply_to
            
            if message.text_content:
                msg.attach(MIMEText(message.text_content, "plain"))
            if message.html_content:
                msg.attach(MIMEText(message.html_content, "html"))
            
            with smtplib.SMTP(self.host, self.port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False
    
    async def send_batch(self, messages: list[EmailMessage]) -> list[bool]:
        results = []
        for message in messages:
            result = await self.send(message)
            results.append(result)
        return results


class EmailService:
    """High-level email service that uses a provider."""
    
    def __init__(self, provider: EmailProvider, default_from_email: str = "noreply@openagent.local", default_from_name: str = "OpenAgent"):
        self.provider = provider
        self.default_from_email = default_from_email
        self.default_from_name = default_from_name
    
    async def send_email(
        self,
        to: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> bool:
        message = EmailMessage(
            to=to,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            from_email=from_email or self.default_from_email,
            from_name=from_name or self.default_from_name,
            reply_to=reply_to,
        )
        return await self.provider.send(message)
    
    async def send_verification_email(self, to: str, verification_url: str, display_name: Optional[str] = None) -> bool:
        """Send email verification email."""
        name = display_name or "User"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Verify your email</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">OpenAgent</h1>
            </div>
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #eee;">
                <h2 style="color: #333; margin-top: 0;">Verify your email address</h2>
                <p>Hi {name},</p>
                <p>Thank you for registering with OpenAgent. Please click the button below to verify your email address:</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{verification_url}" style="background: #667eea; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Verify Email</a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #667eea;">{verification_url}</p>
                <p>This link will expire in 24 hours.</p>
                <p>If you didn't create an account, you can safely ignore this email.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">OpenAgent - AI Workforce Operating System</p>
            </div>
        </body>
        </html>
        """
        text_content = f"""
        Verify your email address - OpenAgent
        
        Hi {name},
        
        Thank you for registering with OpenAgent. Please visit the following link to verify your email address:
        
        {verification_url}
        
        This link will expire in 24 hours.
        
        If you didn't create an account, you can safely ignore this email.
        
        OpenAgent - AI Workforce Operating System
        """
        return await self.send_email(
            to=to,
            subject="Verify your email address - OpenAgent",
            html_content=html_content,
            text_content=text_content,
        )
    
    async def send_password_reset_email(self, to: str, reset_url: str, display_name: Optional[str] = None) -> bool:
        """Send password reset email."""
        name = display_name or "User"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Reset your password</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">OpenAgent</h1>
            </div>
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #eee;">
                <h2 style="color: #333; margin-top: 0;">Reset your password</h2>
                <p>Hi {name},</p>
                <p>You requested a password reset for your OpenAgent account. Click the button below to set a new password:</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="background: #e53e3e; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Reset Password</a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #e53e3e;">{reset_url}</p>
                <p>This link will expire in 1 hour.</p>
                <p>If you didn't request a password reset, you can safely ignore this email.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">OpenAgent - AI Workforce Operating System</p>
            </div>
        </body>
        </html>
        """
        text_content = f"""
        Reset your password - OpenAgent
        
        Hi {name},
        
        You requested a password reset for your OpenAgent account. Please visit the following link to set a new password:
        
        {reset_url}
        
        This link will expire in 1 hour.
        
        If you didn't request a password reset, you can safely ignore this email.
        
        OpenAgent - AI Workforce Operating System
        """
        return await self.send_email(
            to=to,
            subject="Reset your password - OpenAgent",
            html_content=html_content,
            text_content=text_content,
        )
    
    async def send_password_changed_notification(self, to: str, display_name: Optional[str] = None) -> bool:
        """Send notification that password was changed."""
        name = display_name or "User"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Password changed</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #48bb78 0%, #38a169 100%); padding: 30px; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">OpenAgent</h1>
            </div>
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #eee;">
                <h2 style="color: #333; margin-top: 0;">Password changed successfully</h2>
                <p>Hi {name},</p>
                <p>Your password has been changed successfully. If you didn't make this change, please contact support immediately.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">OpenAgent - AI Workforce Operating System</p>
            </div>
        </body>
        </html>
        """
        return await self.send_email(
            to=to,
            subject="Your password has been changed - OpenAgent",
            html_content=html_content,
        )


def create_email_provider_from_settings() -> EmailProvider:
    """Create an email provider based on environment settings."""
    from openagent.core.config import get_settings
    
    settings = get_settings()
    
    if settings.OPENAGENT_ENV == "development":
        return DevelopmentEmailProvider()
    
    # Check if SMTP settings are available
    smtp_host = getattr(settings, "SMTP_HOST", None)
    smtp_port = getattr(settings, "SMTP_PORT", None)
    smtp_username = getattr(settings, "SMTP_USERNAME", None)
    smtp_password = getattr(settings, "SMTP_PASSWORD", None)
    smtp_use_tls = getattr(settings, "SMTP_USE_TLS", True)
    
    if smtp_host and smtp_port and smtp_username and smtp_password:
        return SMTPEmailProvider(
            host=smtp_host,
            port=smtp_port,
            username=smtp_username,
            password=smtp_password,
            use_tls=smtp_use_tls,
        )
    
    # Fallback to development provider
    return DevelopmentEmailProvider()