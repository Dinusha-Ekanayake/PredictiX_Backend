import os
from dotenv import load_dotenv
load_dotenv()

from app.services.notification_service import NotificationService

to_email = "aroshnimantha386@gmail.com"
subject = "PredictiX Alert: New Maintenance Ticket Created - T-0936"
html_body = """
<html>
<body style="font-family: Arial, sans-serif; color: #333;">
<div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px;">
    <div style="background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0;">
        <h2>New Ticket: T-0936</h2>
    </div>
    <div style="padding: 20px;">
        <p>Hello Aroshan,</p>
        <p>A new maintenance ticket has been filed in the PredictiX system.</p>
        <div style="background: #eff6ff; padding: 15px; border-left: 4px solid #2563eb; margin: 15px 0; border-radius: 4px;">
            <strong>Ticket:</strong> T-0936<br>
            <strong>Title:</strong> Brake failure on Forklift FL-04<br>
            <strong>Created By:</strong> Aroshan Nimantha<br>
            <strong>Assignee:</strong> Maintenance Team<br>
            <strong>Priority:</strong> <span style="background-color: #ef4444; color: white; padding: 2px 8px; border-radius: 10px; font-weight: bold;">HIGH</span><br><br>
            <strong>Description:</strong><br>
            Brake failure observed during regular warehouse transit operation.
        </div>
        <p>Please log in to the PredictiX dashboard to track status.</p>
    </div>
</div>
</body>
</html>
"""

print(f"Sending verified ticket alert to {to_email}...")
res = NotificationService.send_email([to_email], subject, html_body)
print(f"DELIVERY STATUS: {res}")
