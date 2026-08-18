"""
Email and Notification Service
Handles sending emails to admins and relevant team members when users are created
All data is fetched from PostgreSQL database - no mock data used
"""

from typing import List, Optional
import os
from datetime import datetime
from sqlalchemy.orm import Session
from pathlib import Path

from app.deps import ADMIN_ROLES

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass


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
        app_url = os.getenv("APP_URL", "https://predicti-x-frontend.vercel.app")

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
                        
                        <p>You can now access PredictiX at: <a href="{app_url}" class="button">Access PredictiX</a></p>
                        
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

    @staticmethod
    def new_faq_notification(question: str, answer: str, category: str, creator_name: str) -> tuple:
        """Email template for new FAQ publication"""
        subject = f"PredictiX Alert: New FAQ Published - {category}"
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                    .header {{ background: linear-gradient(135deg, #0d9488 0%, #0f766e 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 20px; }}
                    .faq-box {{ background: #f0fdfa; padding: 15px; border-left: 4px solid #0d9488; margin: 15px 0; border-radius: 4px; }}
                    .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>New FAQ Published</h2>
                    </div>
                    <div class="content">
                        <p>Hello Team,</p>
                        <p>A new FAQ has been successfully published to the PredictiX Help Desk by <strong>{creator_name}</strong>.</p>
                        
                        <div class="faq-box">
                            <strong>Category:</strong> {category}<br>
                            <strong>Question:</strong> {question}<br><br>
                            <strong>Answer:</strong><br>
                            {answer}
                        </div>
                        
                        <p>This FAQ is now visible to all users under the FAQ section of the Help Desk.</p>
                        
                        <p>Best regards,<br>PredictiX Support</p>
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
    def new_ticket_notification(ticket_number: str, title: str, description: str, priority: str, creator_name: str, assignee_name: str) -> tuple:
        """Email template for new maintenance ticket creation"""
        subject = f"PredictiX Alert: New Maintenance Ticket Created - {ticket_number}"
        
        priority_color = "#ef4444" if priority == "high" else "#eab308" if priority == "medium" else "#22c55e"
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                    .header {{ background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 20px; }}
                    .ticket-box {{ background: #eff6ff; padding: 15px; border-left: 4px solid #2563eb; margin: 15px 0; border-radius: 4px; }}
                    .badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; color: white; }}
                    .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>New Ticket: {ticket_number}</h2>
                    </div>
                    <div class="content">
                        <p>Hello,</p>
                        <p>A new maintenance ticket has been filed in the PredictiX system.</p>
                        
                        <div class="ticket-box">
                            <strong>Ticket:</strong> {ticket_number}<br>
                            <strong>Title:</strong> {title}<br>
                            <strong>Created By:</strong> {creator_name}<br>
                            <strong>Assignee:</strong> {assignee_name}<br>
                            <strong>Priority:</strong> <span class="badge" style="background-color: {priority_color};">{priority.upper()}</span><br><br>
                            <strong>Description:</strong><br>
                            {description}
                        </div>
                        
                        <p>Please log in to the PredictiX dashboard to view the ticket details and track progress.</p>
                        
                        <p>Best regards,<br>PredictiX Help Desk</p>
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
    def ticket_updated_notification(ticket_number: str, title: str, updater_name: str, changes_html: str) -> tuple:
        """Email template for ticket updates (status/priority/assignment changes)"""
        subject = f"PredictiX Alert: Ticket {ticket_number} Updated"
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                    .header {{ background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 20px; }}
                    .update-box {{ background: #fffbeb; padding: 15px; border-left: 4px solid #f59e0b; margin: 15px 0; border-radius: 4px; }}
                    .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>Ticket Updated: {ticket_number}</h2>
                    </div>
                    <div class="content">
                        <p>Hello,</p>
                        <p>Ticket <strong>{ticket_number} ({title})</strong> has been updated by <strong>{updater_name}</strong>.</p>
                        
                        <div class="update-box">
                            <strong>Recent Changes:</strong><br>
                            {changes_html}
                        </div>
                        
                        <p>Please log in to the PredictiX dashboard to view the full ticket status history and add comments.</p>
                        
                        <p>Best regards,<br>PredictiX Help Desk</p>
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
    def ticket_deleted_notification(ticket_number: str, title: str, deleter_name: str) -> tuple:
        """Email template for ticket deletion"""
        subject = f"PredictiX Alert: Ticket {ticket_number} Deleted"
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                    .header {{ background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 20px; }}
                    .delete-box {{ background: #fef2f2; padding: 15px; border-left: 4px solid #ef4444; margin: 15px 0; border-radius: 4px; }}
                    .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>Ticket Deleted: {ticket_number}</h2>
                    </div>
                    <div class="content">
                        <p>Hello,</p>
                        <p>Ticket <strong>{ticket_number} ({title})</strong> has been deleted from the PredictiX system by <strong>{deleter_name}</strong>.</p>
                        
                        <div class="delete-box">
                            <strong>Details of deleted ticket:</strong><br>
                            <strong>Ticket ID/Number:</strong> {ticket_number}<br>
                            <strong>Title:</strong> {title}
                        </div>
                        
                        <p>No further actions are required for this ticket.</p>
                        
                        <p>Best regards,<br>PredictiX Help Desk</p>
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
    def _resolve_session(db: Optional[Session]) -> tuple[Session, bool]:
        """Ensures an open, valid SQLAlchemy session.
        If `db` is None or closed (e.g. dispatched via FastAPI BackgroundTasks),
        opens a fresh SessionLocal() and returns (session, should_close=True)."""
        try:
            if db is not None and db.is_active:
                # Ping connection to ensure it's not closed
                db.connection()
                return db, False
        except Exception:
            pass
        from app.db.session import SessionLocal
        return SessionLocal(), True

    @staticmethod
    def _admin_emails_for_warehouse(db: Session, warehouse_id: Optional[str]) -> List[str]:
        """Active admin/super_admin emails, scoped to a warehouse.

        Falls back to every active admin fleet-wide when warehouse_id is
        unset (e.g. an orphaned ticket, or a user with no warehouse
        assigned yet) so notifications are never silently dropped.
        """
        from app.models import Profile

        q = db.query(Profile.email).filter(
            Profile.role.in_(ADMIN_ROLES),
            Profile.status == "active",
            Profile.email.isnot(None),
        )
        if warehouse_id:
            q = q.filter(
                (Profile.warehouse_id == warehouse_id) | (Profile.role == "super_admin")
            )
        return [email for (email,) in q.all()]

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
        import requests

        recipients = [e for e in to_emails if e]
        if not recipients:
            print("[NOTIFICATION] No valid recipients - skipping email")
            return False

        reply_to_email = "neuromindspredictix@gmail.com"

        # 1. Primary: Direct Google SMTP (guaranteed inbox delivery)
        try:
            from app.services.reminder_email_sender import send_email as send_smtp
            for recipient in recipients:
                send_smtp(
                    to_email=recipient,
                    subject=subject,
                    html_body=html_body,
                    reply_to=reply_to_email,
                )
            print(f"[NOTIFICATION] Email sent via SMTP to {len(recipients)} recipient(s)", flush=True)
            return True
        except Exception as smtp_err:
            print(f"[NOTIFICATION-WARNING] Direct SMTP failed: {smtp_err}, trying Brevo API...", flush=True)

        # 2. Secondary Fallback: Brevo API
        api_key = os.getenv("BREVO_API_KEY")
        sender_email = os.getenv("BREVO_SENDER_EMAIL", "neuromindspredictix@11453287.brevosend.com")
        sender_name = os.getenv("BREVO_SENDER_NAME", "PredictiX Admin")

        if api_key:
            try:
                resp = requests.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "api-key": api_key,
                        "Content-Type": "application/json",
                        "accept": "application/json",
                    },
                    json={
                        "sender": {"email": sender_email, "name": sender_name},
                        "to": [{"email": e} for e in recipients],
                        "replyTo": {"email": reply_to_email, "name": "PredictiX Support"},
                        "subject": subject,
                        "htmlContent": html_body,
                    },
                    timeout=15,
                )
                if resp.status_code in (200, 201, 202):
                    print(f"[NOTIFICATION] Email sent from {sender_email} via Brevo to {len(recipients)} recipient(s)", flush=True)
                    return True
                print(f"[NOTIFICATION-ERROR] Brevo API returned {resp.status_code}: {resp.text[:200]}", flush=True)
            except Exception as brevo_err:
                print(f"[NOTIFICATION-ERROR] Brevo sending failed: {brevo_err}", flush=True)

        return False
    
    @staticmethod
    def notify_on_new_user(db: Optional[Session], new_user_id: str) -> bool:
        """
        Main notification handler - sends all notifications for new user
        Queries all data directly from PostgreSQL database
        """
        session, should_close = NotificationService._resolve_session(db)
        try:
            from app.models import Profile, Department
            
            new_user = session.query(Profile).filter(Profile.id == new_user_id).first()
            if not new_user:
                print(f"[NOTIFICATION-ERROR] New user with ID {new_user_id} not found in database")
                return False
            
            print(f"[NOTIFICATION] Processing notifications for user: {new_user.full_name}")
            
            department_name = "Not Assigned"
            if new_user.department_id:
                dept = session.query(Department).filter(Department.id == new_user.department_id).first()
                if dept:
                    department_name = dept.name
            
            created_at = (new_user.created_at or datetime.now()).strftime('%B %d, %Y at %I:%M %p')
            
            import secrets
            temp_password = secrets.token_urlsafe(12)
            
            # 1. Welcome email to new user
            subject, html_body = EmailTemplates.new_user_welcome_email(
                new_user_name=new_user.full_name,
                email=new_user.email,
                temp_password=temp_password
            )
            NotificationService.send_email([new_user.email], subject, html_body)
            
            # 2. Notification to admins
            admin_emails = NotificationService._admin_emails_for_warehouse(session, new_user.warehouse_id)
            if admin_emails:
                subject, html_body = EmailTemplates.new_user_admin_notification(
                    new_user_name=new_user.full_name,
                    department=department_name,
                    role=new_user.role,
                    email=new_user.email,
                    created_at=created_at
                )
                NotificationService.send_email(admin_emails, subject, html_body)
            
            # 3. Notification to department members
            if new_user.department_id:
                dept_members = session.query(Profile).filter(
                    Profile.department_id == new_user.department_id,
                    Profile.id != new_user.id,
                    Profile.status == "active"
                ).all()
                dept_email_list = [member.email for member in dept_members if member.email]
                if dept_email_list:
                    subject, html_body = EmailTemplates.new_user_department_notification(
                        new_user_name=new_user.full_name,
                        department=department_name,
                        role=new_user.role,
                        created_at=created_at
                    )
                    NotificationService.send_email(dept_email_list, subject, html_body)
            
            return True
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to process notifications: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if should_close:
                session.close()
    
    @staticmethod
    def notify_on_profile_update(db: Optional[Session], user_id: str) -> bool:
        """Send notification to admins when a user updates their profile"""
        session, should_close = NotificationService._resolve_session(db)
        try:
            from app.models import Profile, Department
            
            user = session.query(Profile).filter(Profile.id == user_id).first()
            if not user:
                print(f"[NOTIFICATION-ERROR] User with ID {user_id} not found in database", flush=True)
                return False
            
            print(f"[NOTIFICATION] Processing profile update notification for: {user.full_name}", flush=True)
            
            department_name = "Not Assigned"
            if user.department_id:
                dept = session.query(Department).filter(Department.id == user.department_id).first()
                if dept:
                    department_name = dept.name
            
            updated_at = (datetime.now()).strftime('%B %d, %Y at %I:%M %p')
            
            admin_emails = NotificationService._admin_emails_for_warehouse(session, user.warehouse_id)
            if admin_emails:
                subject, html_body = EmailTemplates.new_user_admin_notification(
                    new_user_name=user.full_name,
                    department=department_name,
                    role=user.role,
                    email=user.email,
                    created_at=updated_at
                )
                NotificationService.send_email(admin_emails, subject, html_body)
            
            return True
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to process profile update notification: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if should_close:
                session.close()

    @staticmethod
    def notify_on_new_faq(db: Optional[Session], question: str, answer: str, category: Optional[str] = None, creator_name: str = "Administrator") -> bool:
        """Send notification to all users when a new FAQ is created"""
        session, should_close = NotificationService._resolve_session(db)
        try:
            from app.models import Profile
            user_emails = [
                email for (email,) in session.query(Profile.email)
                .filter(Profile.email.isnot(None))
                .all()
            ]
            if not user_emails:
                print("[NOTIFICATION] No users to notify for new FAQ - skipping email", flush=True)
                return False
                
            print(f"[NOTIFICATION] Notifying {len(user_emails)} user(s) of new FAQ", flush=True)
            subject, html_body = EmailTemplates.new_faq_notification(
                question=question,
                answer=answer,
                category=category or "General",
                creator_name=creator_name
            )
            return NotificationService.send_email(user_emails, subject, html_body)
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to notify on new FAQ: {str(e)}", flush=True)
            return False
        finally:
            if should_close:
                session.close()

    @staticmethod
    def notify_on_new_ticket(db: Optional[Session], ticket_id: str) -> bool:
        """Send notifications to admins, creator, and assignee when a ticket is created"""
        session, should_close = NotificationService._resolve_session(db)
        try:
            from app.models import Ticket, Profile
            
            ticket = session.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket:
                print(f"[NOTIFICATION-ERROR] Ticket with ID {ticket_id} not found", flush=True)
                return False
                
            creator = session.query(Profile).filter(Profile.id == ticket.created_by).first()
            creator_name = creator.full_name if creator else "System/Unknown"
            creator_email = creator.email if creator else None
            
            assignee_name = "Unassigned"
            assignee_email = None
            if ticket.assigned_to:
                assignee = session.query(Profile).filter(Profile.id == ticket.assigned_to).first()
                if assignee:
                    assignee_name = assignee.full_name
                    assignee_email = assignee.email
                    
            admin_emails = NotificationService._admin_emails_for_warehouse(session, ticket.warehouse_id)
            recipients = set(admin_emails)
            if creator_email:
                recipients.add(creator_email)
            if assignee_email:
                recipients.add(assignee_email)
                
            email_list = list(recipients)
            if not email_list:
                print("[NOTIFICATION] No recipients to notify for new ticket - skipping email", flush=True)
                return False
                
            print(f"[NOTIFICATION] Notifying on new ticket {ticket.ticket_number} to {len(email_list)} recipients", flush=True)
            subject, html_body = EmailTemplates.new_ticket_notification(
                ticket_number=ticket.ticket_number,
                title=ticket.title,
                description=ticket.description or "",
                priority=ticket.priority or "medium",
                creator_name=creator_name,
                assignee_name=assignee_name
            )
            return NotificationService.send_email(email_list, subject, html_body)
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to notify on new ticket: {str(e)}", flush=True)
            return False
        finally:
            if should_close:
                session.close()

    @staticmethod
    def notify_on_ticket_update(db: Optional[Session], ticket_id: str, updater_id: str, old_status: str, old_priority: str, old_assigned_to: Optional[str]) -> bool:
        """Send notifications when a ticket is updated"""
        session, should_close = NotificationService._resolve_session(db)
        try:
            from app.models import Ticket, Profile
            
            ticket = session.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket:
                print(f"[NOTIFICATION-ERROR] Ticket with ID {ticket_id} not found", flush=True)
                return False
                
            updater = session.query(Profile).filter(Profile.id == updater_id).first()
            updater_name = updater.full_name if updater else "System/User"
            
            changes = []
            if old_status != ticket.status:
                changes.append(f"<li><b>Status:</b> Changed from <span style='color: #ef4444;'>{old_status}</span> to <span style='color: #22c55e;'>{ticket.status}</span></li>")
            if old_priority != ticket.priority:
                changes.append(f"<li><b>Priority:</b> Changed from <b>{old_priority}</b> to <b>{ticket.priority}</b></li>")
            
            old_assignee_name = "Unassigned"
            old_assignee_email = None
            if old_assigned_to:
                old_assignee = session.query(Profile).filter(Profile.id == old_assigned_to).first()
                if old_assignee:
                    old_assignee_name = old_assignee.full_name
                    old_assignee_email = old_assignee.email
            new_assignee_name = "Unassigned"
            new_assignee_email = None
            if ticket.assigned_to:
                new_assignee = session.query(Profile).filter(Profile.id == ticket.assigned_to).first()
                if new_assignee:
                    new_assignee_name = new_assignee.full_name
                    new_assignee_email = new_assignee.email
            
            if str(old_assigned_to or "") != str(ticket.assigned_to or ""):
                changes.append(f"<li><b>Assignee:</b> Changed from <b>{old_assignee_name}</b> to <b>{new_assignee_name}</b></li>")
                
            if not changes:
                print(f"[NOTIFICATION] No status, priority, or assignee change on ticket {ticket.ticket_number} - skipping email", flush=True)
                return False
                
            changes_html = "<ul>" + "".join(changes) + "</ul>"
            
            creator = session.query(Profile).filter(Profile.id == ticket.created_by).first()
            creator_email = creator.email if creator else None
            updater_email = updater.email if updater else None
            
            admin_emails = NotificationService._admin_emails_for_warehouse(session, ticket.warehouse_id)
            recipients = set(admin_emails)
            if creator_email:
                recipients.add(creator_email)
            if updater_email:
                recipients.add(updater_email)
            if new_assignee_email:
                recipients.add(new_assignee_email)
            if old_assignee_email:
                recipients.add(old_assignee_email)
            email_list = list(recipients)
            if not email_list:
                return False
                
            print(f"[NOTIFICATION] Notifying on update of ticket {ticket.ticket_number} to {len(email_list)} recipients", flush=True)
            subject, html_body = EmailTemplates.ticket_updated_notification(
                ticket_number=ticket.ticket_number,
                title=ticket.title,
                updater_name=updater_name,
                changes_html=changes_html
            )
            return NotificationService.send_email(email_list, subject, html_body)
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to notify on ticket update: {str(e)}", flush=True)
            return False
        finally:
            if should_close:
                session.close()

    @staticmethod
    def notify_on_ticket_delete(
        ticket_number: str,
        title: str,
        creator_email: Optional[str],
        assignee_email: Optional[str],
        deleter_name: str,
        admin_emails: List[str]
    ) -> bool:
        """Send notifications to creator, assignee, and admins when a ticket is deleted"""
        try:
            recipients = set(admin_emails)
            if creator_email:
                recipients.add(creator_email)
            if assignee_email:
                recipients.add(assignee_email)
                
            email_list = list(recipients)
            if not email_list:
                print("[NOTIFICATION] No recipients to notify for deleted ticket - skipping email", flush=True)
                return False
                
            print(f"[NOTIFICATION] Notifying on deleted ticket {ticket_number} to {len(email_list)} recipients", flush=True)
            subject, html_body = EmailTemplates.ticket_deleted_notification(
                ticket_number=ticket_number,
                title=title,
                deleter_name=deleter_name
            )
            return NotificationService.send_email(email_list, subject, html_body)
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to notify on ticket delete: {str(e)}", flush=True)
            return False

