"""
Email and Notification Service
Handles sending emails to admins and relevant team members when users are created
All data is fetched from PostgreSQL database - no mock data used
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
import os
from datetime import datetime
from sqlalchemy.orm import Session
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass


class EmailConfig:
    """Email configuration - set these via environment variables"""
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SENDER_EMAIL = os.getenv("SENDER_EMAIL", "noreply@predictix.lk")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")
    USE_TLS = os.getenv("USE_TLS", "true").lower() == "true"
    

class EmailTemplates:
    """Email templates for different notifications"""
    
    @staticmethod
    def new_user_admin_notification(new_user_name: str, department: str, role: str, email: str, created_at: str) -> tuple:
        """Email template for admin notification when new user is created"""
        subject = f"New User Created: {new_user_name}"
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 20px; }}
                    .info-box {{ background: #f5f5f5; padding: 15px; border-left: 4px solid #667eea; margin: 15px 0; }}
                    .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>New User Created</h2>
                    </div>
                    <div class="content">
                        <p>Hello Admin,</p>
                        <p>A new user has been registered in the PredictiX system.</p>
                        
                        <div class="info-box">
                            <strong>User Details (from Database):</strong><br>
                            <strong>Name:</strong> {new_user_name}<br>
                            <strong>Email:</strong> {email}<br>
                            <strong>Department:</strong> {department}<br>
                            <strong>Role:</strong> {role.upper()}<br>
                            <strong>Created:</strong> {created_at}
                        </div>
                        
                        <p>Please review the user's profile and ensure all information is correct. The user will receive a separate welcome email with login credentials.</p>
                        
                        <p>Best regards,<br>PredictiX System</p>
                    </div>
                    <div class="footer">
                        <p>This is an automated notification. Please do not reply to this email.</p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return subject, html_body
    
    @staticmethod
    def new_user_department_notification(new_user_name: str, department: str, role: str, created_at: str) -> tuple:
        """Email template for department members when new user joins"""
        subject = f"Welcome to Your Team: {new_user_name} has joined {department}"
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 20px; }}
                    .info-box {{ background: #f5f5f5; padding: 15px; border-left: 4px solid #667eea; margin: 15px 0; }}
                    .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>New Team Member Welcome</h2>
                    </div>
                    <div class="content">
                        <p>Hello {department} Team,</p>
                        <p>We are pleased to introduce a new member to our team!</p>
                        
                        <div class="info-box">
                            <strong>New Team Member (from Database):</strong><br>
                            <strong>Name:</strong> {new_user_name}<br>
                            <strong>Department:</strong> {department}<br>
                            <strong>Role:</strong> {role.upper()}<br>
                            <strong>Joined On:</strong> {created_at}
                        </div>
                        
                        <p>Please feel free to reach out and help {new_user_name.split()[0] if new_user_name else 'them'} get up to speed. You can find their contact information in the Team Members section of the PredictiX application.</p>
                        
                        <p>Welcome aboard!</p>
                        
                        <p>Best regards,<br>PredictiX Team</p>
                    </div>
                    <div class="footer">
                        <p>This is an automated notification. Please do not reply to this email.</p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return subject, html_body
    
    @staticmethod
    def new_user_welcome_email(new_user_name: str, email: str, temp_password: str) -> tuple:
        """Email template for new user welcome - uses real database data"""
        subject = "Welcome to PredictiX - Your Account is Ready!"
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 20px; }}
                    .credentials-box {{ background: #fffacd; padding: 15px; border-left: 4px solid #ffa500; margin: 15px 0; border-radius: 4px; }}
                    .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 4px; margin: 15px 0; }}
                    .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>Welcome to PredictiX!</h2>
                    </div>
                    <div class="content">
                        <p>Hello {new_user_name},</p>
                        <p>Your account has been successfully created in the PredictiX AI-Powered Asset Management system.</p>
                        
                        <div class="credentials-box">
                            <strong>Login Credentials:</strong><br>
                            <strong>Email:</strong> {email}<br>
                            <strong>Temporary Password:</strong> {temp_password}<br><br>
                            <em>Please change your password after your first login for security.</em>
                        </div>
                        
                        <p>You can now access PredictiX at: <a href="http://localhost:3001" class="button">Access PredictiX</a></p>
                        
                        <p><strong>Quick Start Guide:</strong></p>
                        <ul>
                            <li>Log in with your email and temporary password</li>
                            <li>Visit your Profile page to view your team members</li>
                            <li>Check your assigned assets in the Assets section</li>
                            <li>Submit tickets for maintenance issues as needed</li>
                        </ul>
                        
                        <p>If you need any assistance, please use the Help Desk feature within the application or contact your administrator.</p>
                        
                        <p>Welcome aboard!<br>PredictiX Team</p>
                    </div>
                    <div class="footer">
                        <p>This is an automated notification. Please do not reply to this email.</p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return subject, html_body


class NotificationService:
    """Service to send email notifications using PostgreSQL database data"""
    
    @staticmethod
    def send_email(to_emails: List[str], subject: str, html_body: str) -> bool:
        """
        Send email to one or more recipients
        
        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            html_body: HTML body of the email
            
        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            if not EmailConfig.SENDER_PASSWORD:
                print("[NOTIFICATION] Email service disabled - SENDER_PASSWORD not configured")
                return False
            
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = EmailConfig.SENDER_EMAIL
            message["To"] = ", ".join(to_emails)
            
            # Attach HTML content
            message.attach(MIMEText(html_body, "html"))
            
            # Send email
            with smtplib.SMTP(EmailConfig.SMTP_SERVER, EmailConfig.SMTP_PORT) as server:
                if EmailConfig.USE_TLS:
                    server.starttls()
                
                server.login(EmailConfig.SENDER_EMAIL, EmailConfig.SENDER_PASSWORD)
                server.sendmail(EmailConfig.SENDER_EMAIL, to_emails, message.as_string())
            
            print(f"[NOTIFICATION] Email sent successfully to {len(to_emails)} recipient(s)")
            return True
            
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to send email: {str(e)}")
            return False
    
    @staticmethod
    def notify_on_new_user(db: Session, new_user_id: str) -> bool:
        """
        Main notification handler - sends all notifications for new user
        Queries all data directly from PostgreSQL database
        
        Args:
            db: SQLAlchemy database session
            new_user_id: UUID of the newly created user
            
        Returns:
            True if notifications sent successfully (or email disabled)
        """
        try:
            from app.models import Profile, Department
            
            # ============================================================
            # Query new user from database
            # ============================================================
            new_user = db.query(Profile).filter(Profile.id == new_user_id).first()
            
            if not new_user:
                print(f"[NOTIFICATION-ERROR] New user with ID {new_user_id} not found in database")
                return False
            
            print(f"[NOTIFICATION] Processing notifications for user: {new_user.full_name}")
            
            # Get department name from database
            department_name = "Not Assigned"
            if new_user.department_id:
                dept = db.query(Department).filter(Department.id == new_user.department_id).first()
                if dept:
                    department_name = dept.name
            
            # Format creation timestamp
            created_at = (new_user.created_at or datetime.now()).strftime('%B %d, %Y at %I:%M %p')
            
            # Generate temporary password
            import secrets
            temp_password = secrets.token_urlsafe(12)
            
            # ============================================================
            # 1. SEND WELCOME EMAIL TO NEW USER
            # ============================================================
            print(f"[NOTIFICATION] Sending welcome email to {new_user.email}")
            subject, html_body = EmailTemplates.new_user_welcome_email(
                new_user_name=new_user.full_name,
                email=new_user.email,
                temp_password=temp_password
            )
            NotificationService.send_email([new_user.email], subject, html_body)
            
            # ============================================================
            # 2. SEND NOTIFICATION TO ALL ADMIN USERS FROM DATABASE
            # ============================================================
            admin_profiles = db.query(Profile).filter(
                Profile.role == "admin",
                Profile.status == "active"
            ).all()
            
            admin_emails = [admin.email for admin in admin_profiles if admin.email]
            
            if admin_emails:
                print(f"[NOTIFICATION] Notifying {len(admin_emails)} admin(s) from database")
                subject, html_body = EmailTemplates.new_user_admin_notification(
                    new_user_name=new_user.full_name,
                    department=department_name,
                    role=new_user.role,
                    email=new_user.email,
                    created_at=created_at
                )
                NotificationService.send_email(admin_emails, subject, html_body)
            
            # ============================================================
            # 3. SEND NOTIFICATION TO DEPARTMENT MEMBERS FROM DATABASE
            # ============================================================
            if new_user.department_id:
                dept_members = db.query(Profile).filter(
                    Profile.department_id == new_user.department_id,
                    Profile.id != new_user.id,  # Exclude the new user
                    Profile.status == "active"
                ).all()
                
                dept_email_list = [member.email for member in dept_members if member.email]
                
                if dept_email_list:
                    print(f"[NOTIFICATION] Notifying {len(dept_email_list)} department member(s) in {department_name} from database")
                    subject, html_body = EmailTemplates.new_user_department_notification(
                        new_user_name=new_user.full_name,
                        department=department_name,
                        role=new_user.role,
                        created_at=created_at
                    )
                    NotificationService.send_email(dept_email_list, subject, html_body)
            
            print(f"[NOTIFICATION] All notifications processed for {new_user.full_name}")
            return True
            
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to process notifications: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    @staticmethod
    def notify_on_profile_update(db: Session, user_id: str) -> bool:
        """
        Send notification to admins when a user updates their profile
        All data fetched directly from PostgreSQL database
        
        Args:
            db: SQLAlchemy database session
            user_id: UUID of the user who updated their profile
            
        Returns:
            True if notifications sent successfully (or email disabled)
        """
        try:
            from app.models import Profile, Department
            
            # ============================================================
            # Query user who updated their profile
            # ============================================================
            user = db.query(Profile).filter(Profile.id == user_id).first()
            
            if not user:
                print(f"[NOTIFICATION-ERROR] User with ID {user_id} not found in database", flush=True)
                return False
            
            print(f"[NOTIFICATION] Processing profile update notification for: {user.full_name}", flush=True)
            
            # Get department name from database
            department_name = "Not Assigned"
            if user.department_id:
                dept = db.query(Department).filter(Department.id == user.department_id).first()
                if dept:
                    department_name = dept.name
            
            # Format timestamp
            updated_at = (datetime.now()).strftime('%B %d, %Y at %I:%M %p')
            
            # ============================================================
            # SEND NOTIFICATION TO ALL ADMIN USERS FROM DATABASE
            # ============================================================
            admin_profiles = db.query(Profile).filter(
                Profile.role == "admin",
                Profile.status == "active"
            ).all()
            
            admin_emails = [admin.email for admin in admin_profiles if admin.email]
            
            if admin_emails:
                print(f"[NOTIFICATION] Notifying {len(admin_emails)} admin(s) of profile update from database", flush=True)
                
                subject = f"Profile Updated: {user.full_name}"
                
                html_body = f"""
                <html>
                    <head>
                        <style>
                            body {{ font-family: Arial, sans-serif; color: #333; }}
                            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                            .content {{ padding: 20px; }}
                            .info-box {{ background: #f5f5f5; padding: 15px; border-left: 4px solid #667eea; margin: 15px 0; }}
                            .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="header">
                                <h2>Profile Update Notification</h2>
                            </div>
                            <div class="content">
                                <p>Hello Admin,</p>
                                <p>A user has updated their profile information in the PredictiX system.</p>
                                
                                <div class="info-box">
                                    <strong>User Details (from Database):</strong><br>
                                    <strong>Name:</strong> {user.full_name}<br>
                                    <strong>Email:</strong> {user.email}<br>
                                    <strong>Department:</strong> {department_name}<br>
                                    <strong>Role:</strong> {user.role.upper()}<br>
                                    <strong>Contact Number:</strong> {user.phone if user.phone else 'Not provided'}<br>
                                    <strong>Updated:</strong> {updated_at}
                                </div>
                                
                                <p>Please review their updated profile in the admin section if needed.</p>
                                
                                <p>Best regards,<br>PredictiX System</p>
                            </div>
                            <div class="footer">
                                <p>This is an automated notification. Please do not reply to this email.</p>
                            </div>
                        </div>
                    </body>
                </html>
                """
                
                NotificationService.send_email(admin_emails, subject, html_body)
            
            print(f"[NOTIFICATION] Profile update notification processed for {user.full_name}")
            return True
            
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to process profile update notification: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

