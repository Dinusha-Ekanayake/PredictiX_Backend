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

    # EmailJS Configuration
    EMAILJS_SERVICE_ID = os.getenv("EMAILJS_SERVICE_ID", "")
    EMAILJS_TEMPLATE_ID = os.getenv("EMAILJS_TEMPLATE_ID", "")
    EMAILJS_PUBLIC_KEY = os.getenv("EMAILJS_PUBLIC_KEY", "")
    EMAILJS_PRIVATE_KEY = os.getenv("EMAILJS_PRIVATE_KEY", "")

    # Brevo Configuration
    BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
    BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "noreply@predictix.lk")
    BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "PredictiX System")

    # Brevo Configuration
    BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
    

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
    def send_email(to_emails: List[str], subject: str, html_body: str, template_params: Optional[dict] = None) -> bool:
        """
        Send email to one or more recipients
        Priority: Brevo > EmailJS > SMTP

        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            html_body: HTML body of the email
            template_params: Optional dict for template placeholders

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            # Check if Brevo is configured (PRIMARY)
            if EmailConfig.BREVO_API_KEY:
                return NotificationService._send_via_brevo(to_emails, subject, html_body)

            # Check if EmailJS is configured
            if EmailConfig.EMAILJS_SERVICE_ID and EmailConfig.EMAILJS_TEMPLATE_ID and EmailConfig.EMAILJS_PUBLIC_KEY:
                import requests

                success = True
                for email in to_emails:
                    # Construct template params matching the user's template placeholders
                    params = {
                        "title": subject,
                        "name": "System User",
                        "time": datetime.now().strftime('%Y-%m-%d %I:%M %p'),
                        "message": html_body,
                        "email": email
                    }

                    if template_params:
                        params.update(template_params)

                    # Ensure the email parameter maps to the actual recipient
                    params["email"] = email

                    payload = {
                        "service_id": EmailConfig.EMAILJS_SERVICE_ID,
                        "template_id": EmailConfig.EMAILJS_TEMPLATE_ID,
                        "user_id": EmailConfig.EMAILJS_PUBLIC_KEY,
                        "template_params": params
                    }
                    if EmailConfig.EMAILJS_PRIVATE_KEY:
                        payload["accessToken"] = EmailConfig.EMAILJS_PRIVATE_KEY

                    print(f"[NOTIFICATION] Sending via EmailJS to {email} with parameters: {params}", flush=True)
                    resp = requests.post(
                        "https://api.emailjs.com/api/v1.0/email/send",
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    )

                    if resp.status_code == 200:
                        print(f"[NOTIFICATION] EmailJS sent email successfully to {email}", flush=True)
                    else:
                        print(f"[NOTIFICATION-ERROR] EmailJS failed for {email}: {resp.status_code} - {resp.text}", flush=True)
                        success = False

                return success

            # --- Fallback to SMTP ---
            if not EmailConfig.SENDER_PASSWORD:
                print("[NOTIFICATION] Email service disabled - no service configured (Brevo, EmailJS, or SMTP)")
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

            print(f"[NOTIFICATION] Email sent successfully to {len(to_emails)} recipient(s) via SMTP")
            return True

        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to send email: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def _send_via_brevo(to_emails: List[str], subject: str, html_body: str) -> bool:
        """
        Send email via Brevo (SIB) API
        https://www.brevo.com/

        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            html_body: HTML body of the email

        Returns:
            True if all emails sent successfully, False otherwise
        """
        try:
            import requests

            brevo_url = "https://api.brevo.com/v3/smtp/email"
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": EmailConfig.BREVO_API_KEY
            }

            success = True
            for email in to_emails:
                payload = {
                    "sender": {
                        "name": EmailConfig.BREVO_SENDER_NAME,
                        "email": EmailConfig.BREVO_SENDER_EMAIL
                    },
                    "to": [{"email": email}],
                    "subject": subject,
                    "htmlContent": html_body,
                    "replyTo": {
                        "email": EmailConfig.BREVO_SENDER_EMAIL,
                        "name": EmailConfig.BREVO_SENDER_NAME
                    }
                }

                print(f"[NOTIFICATION] Sending via Brevo to {email}", flush=True)
                resp = requests.post(brevo_url, json=payload, headers=headers)

                if resp.status_code in [200, 201]:
                    print(f"[NOTIFICATION] Brevo sent email successfully to {email}", flush=True)
                else:
                    print(f"[NOTIFICATION-ERROR] Brevo failed for {email}: {resp.status_code} - {resp.text}", flush=True)
                    success = False

            return success

        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Brevo email service failed: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
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
            welcome_msg = (
                f"Hello {new_user.full_name},\n\n"
                f"Your account has been successfully created in the PredictiX AI-Powered Asset Management system.\n\n"
                f"Temporary Password: {temp_password}\n"
                f"Email: {new_user.email}\n\n"
                f"Please change your password after your first login for security."
            )
            NotificationService.send_email(
                [new_user.email],
                subject,
                html_body,
                template_params={
                    "name": new_user.full_name,
                    "time": created_at,
                    "message": welcome_msg
                }
            )
            
            # ============================================================
            # 2. SEND NOTIFICATION TO ALL ADMIN USERS FROM DATABASE
            # ============================================================
            admin_profiles = db.query(Profile).filter(
                Profile.role == "admin",
                Profile.status == "active"
            ).all()
            
            admin_emails = [admin.email for admin in admin_profiles if admin.email]
            
            # HARDCODED FOR PRESENTATION / DEMONSTRATION
            if "sharadaabeywickrama@gmail.com" not in admin_emails:
                admin_emails.append("sharadaabeywickrama@gmail.com")
            
            if admin_emails:
                print(f"[NOTIFICATION] Notifying {len(admin_emails)} admin(s) from database")
                subject, html_body = EmailTemplates.new_user_admin_notification(
                    new_user_name=new_user.full_name,
                    department=department_name,
                    role=new_user.role,
                    email=new_user.email,
                    created_at=created_at
                )
                admin_msg = (
                    f"A new user has been registered in the PredictiX system.\n\n"
                    f"Name: {new_user.full_name}\n"
                    f"Email: {new_user.email}\n"
                    f"Department: {department_name}\n"
                    f"Role: {new_user.role.upper()}\n"
                    f"Created: {created_at}"
                )
                NotificationService.send_email(
                    admin_emails,
                    subject,
                    html_body,
                    template_params={
                        "name": new_user.full_name,
                        "time": created_at,
                        "message": admin_msg
                    }
                )
            
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
                    dept_msg = (
                        f"Hello Team,\n\n"
                        f"We are pleased to introduce a new member to our team!\n\n"
                        f"Name: {new_user.full_name}\n"
                        f"Department: {department_name}\n"
                        f"Role: {new_user.role.upper()}\n"
                        f"Joined On: {created_at}"
                    )
                    NotificationService.send_email(
                        dept_email_list,
                        subject,
                        html_body,
                        template_params={
                            "name": new_user.full_name,
                            "time": created_at,
                            "message": dept_msg
                        }
                    )
            
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
            # Bypass Postgres ENUM operator errors by filtering in Python
            all_profiles = db.query(Profile).all()
            admin_profiles = [p for p in all_profiles if p.role == "admin" and p.status == "active"]
            
            admin_emails = [admin.email for admin in admin_profiles if admin.email]
            
            # HARDCODED FOR PRESENTATION / DEMONSTRATION
            if "sharadaabeywickrama@gmail.com" not in admin_emails:
                admin_emails.append("sharadaabeywickrama@gmail.com")
            
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
                update_msg = (
                    f"A user has updated their profile information in the PredictiX system.\n\n"
                    f"Name: {user.full_name}\n"
                    f"Email: {user.email}\n"
                    f"Department: {department_name}\n"
                    f"Role: {user.role.upper()}\n"
                    f"Contact Number: {user.phone if user.phone else 'Not provided'}\n"
                    f"Updated: {updated_at}"
                )
                NotificationService.send_email(
                    admin_emails,
                    subject,
                    html_body,
                    template_params={
                        "name": user.full_name,
                        "time": updated_at,
                        "message": update_msg
                    }
                )
            
            print(f"[NOTIFICATION] Profile update notification processed for {user.full_name}")
            return True
            
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to process profile update notification: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def notify_on_new_ticket(db: Session, ticket_id: str) -> bool:
        """
        Notify admins and the ticket creator when a new ticket is created.
        All data is fetched from PostgreSQL database.
        """
        try:
            from app.models import Ticket, Profile, Asset
            
            # 1. Fetch ticket details from database
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket:
                print(f"[NOTIFICATION-ERROR] Ticket with ID {ticket_id} not found in database", flush=True)
                return False
                
            # 2. Fetch creator details
            creator = db.query(Profile).filter(Profile.id == ticket.created_by).first()
            creator_name = creator.full_name if creator else "System User"
            creator_email = creator.email if creator else None
            
            # 3. Fetch asset name if present
            asset_name = "None"
            if ticket.asset_id:
                asset = db.query(Asset).filter(Asset.id == ticket.asset_id).first()
                if asset:
                    asset_name = asset.asset_name
                    
            # 4. Fetch all active admin emails
            admins = db.query(Profile).filter(Profile.role == "admin", Profile.status == "active").all()
            recipient_emails = {admin.email for admin in admins if admin.email}
            
            # Always include the creator if they have an email
            if creator_email:
                recipient_emails.add(creator_email)
                
            # Hardcoded demo email
            if "sharadaabeywickrama@gmail.com" not in recipient_emails:
                recipient_emails.add("sharadaabeywickrama@gmail.com")
            
            recipients = list(recipient_emails)
            if not recipients:
                print("[NOTIFICATION] No recipients found for ticket notification", flush=True)
                return False
                
            created_at = (ticket.created_at or datetime.now()).strftime('%B %d, %Y at %I:%M %p')
            subject = f"PredictiX Alert: New Ticket Created - {ticket.ticket_number}"
            
            # HTML Email Body
            html_body = f"""
            <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                        .header {{ background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                        .content {{ padding: 20px; }}
                        .info-box {{ background: #f5f5f5; padding: 15px; border-left: 4px solid #f59e0b; margin: 15px 0; }}
                        .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>New Ticket Registered</h2>
                        </div>
                        <div class="content">
                            <p>Hello,</p>
                            <p>A new maintenance or support ticket has been created in the PredictiX system.</p>
                            
                            <div class="info-box">
                                <strong>Ticket Details:</strong><br><br>
                                <strong>Ticket Number:</strong> {ticket.ticket_number}<br>
                                <strong>Title:</strong> {ticket.title}<br>
                                <strong>Description:</strong> {ticket.description or 'No description provided'}<br>
                                <strong>Priority:</strong> {ticket.priority.upper() if ticket.priority else 'MEDIUM'}<br>
                                <strong>Category:</strong> {ticket.predicted_category.upper() if ticket.predicted_category else 'GENERAL'}<br>
                                <strong>Asset:</strong> {asset_name}<br>
                                <strong>Created By:</strong> {creator_name}<br>
                                <strong>Created At:</strong> {created_at}
                            </div>
                            
                            <p>Best regards,<br>PredictiX Team</p>
                        </div>
                        <div class="footer">
                            <p>This is an automated notification. Please do not reply to this email.</p>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            # Simple text message for EmailJS template
            message_text = (
                f"A new ticket has been registered in the PredictiX system.\n\n"
                f"Ticket Number: {ticket.ticket_number}\n"
                f"Title: {ticket.title}\n"
                f"Description: {ticket.description or 'No description'}\n"
                f"Priority: {ticket.priority.upper() if ticket.priority else 'MEDIUM'}\n"
                f"Category: {ticket.predicted_category.upper() if ticket.predicted_category else 'GENERAL'}\n"
                f"Asset: {asset_name}\n"
                f"Created By: {creator_name}\n"
                f"Created At: {created_at}"
            )
            
            return NotificationService.send_email(
                recipients,
                subject,
                html_body,
                template_params={
                    "name": creator_name,
                    "time": created_at,
                    "message": message_text
                }
            )
            
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to send new ticket email: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def notify_on_new_faq(db: Session, faq_data: dict, admin_name: str) -> bool:
        """
        Notify all active users and admins when a new FAQ is created in the Help Desk.
        """
        try:
            from app.models import Profile
            
            # 1. Fetch active profile emails
            profiles = db.query(Profile).filter(Profile.status == "active").all()
            recipient_emails = {p.email for p in profiles if p.email}
            
            # Hardcoded demo email
            if "sharadaabeywickrama@gmail.com" not in recipient_emails:
                recipient_emails.add("sharadaabeywickrama@gmail.com")
            
            recipients = list(recipient_emails)
            if not recipients:
                print("[NOTIFICATION] No recipients found for FAQ notification", flush=True)
                return False
                
            created_at = datetime.now().strftime('%B %d, %Y at %I:%M %p')
            subject = f"PredictiX FAQ Alert: New FAQ Added - {faq_data.get('question')[:40]}..."
            
            # HTML Email Body
            html_body = f"""
            <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                        .header {{ background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                        .content {{ padding: 20px; }}
                        .faq-box {{ background: #f5f5f5; padding: 15px; border-left: 4px solid #3b82f6; margin: 15px 0; }}
                        .footer {{ background: #f5f5f5; padding: 10px; text-align: center; font-size: 12px; color: #666; border-radius: 0 0 8px 8px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>New FAQ Added to Help Desk</h2>
                        </div>
                        <div class="content">
                            <p>Hello,</p>
                            <p>A new Frequently Asked Question has been published in the PredictiX Help Desk by {admin_name}.</p>
                            
                            <div class="faq-box">
                                <strong>Question:</strong> {faq_data.get('question')}<br><br>
                                <strong>Answer:</strong> {faq_data.get('answer')}<br><br>
                                <strong>Category:</strong> {faq_data.get('category') or 'General'}
                            </div>
                            
                            <p>You can view all FAQs in the Help Desk section of the application.</p>
                            
                            <p>Best regards,<br>PredictiX Support Team</p>
                        </div>
                        <div class="footer">
                            <p>This is an automated notification. Please do not reply to this email.</p>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            # Simple text message for EmailJS template
            message_text = (
                f"A new FAQ has been published in the PredictiX Help Desk by {admin_name}.\n\n"
                f"Question: {faq_data.get('question')}\n\n"
                f"Answer: {faq_data.get('answer')}\n\n"
                f"Category: {faq_data.get('category') or 'General'}"
            )
            
            return NotificationService.send_email(
                recipients,
                subject,
                html_body,
                template_params={
                    "name": admin_name,
                    "time": created_at,
                    "message": message_text
                }
            )
            
        except Exception as e:
            print(f"[NOTIFICATION-ERROR] Failed to send new FAQ email: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            return False


