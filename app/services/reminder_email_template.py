"""HTML email templates for PredictiX notifications."""
from __future__ import annotations

from datetime import date
from typing import Optional


def service_reminder_html(
    *,
    user_name: str,
    asset_name: str,
    asset_code: str,
    asset_type: str,
    next_service_date: date,
    days_remaining: int,
    warehouse_name: Optional[str] = None,
    dashboard_url: Optional[str] = None,
<<<<<<< HEAD
) -> tuple[str, str]:
    """Render (html, plain_text) for a service reminder email."""
=======
    admin_note: Optional[str] = None,
) -> tuple[str, str]:
    """Render HTML and plain-text versions of a service reminder email."""
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b
    date_str = next_service_date.strftime("%B %d, %Y")

    if days_remaining <= 0:
        urgency_label = "Service is due today"
        urgency_color = "#ef4444"
        urgency_text_color = "#ffffff"
    elif days_remaining == 1:
        urgency_label = "Service is due tomorrow"
        urgency_color = "#ef4444"
        urgency_text_color = "#ffffff"
    elif days_remaining <= 3:
<<<<<<< HEAD
        urgency_label = f"Service due in {days_remaining} days"
        urgency_color = "#f59e0b"
        urgency_text_color = "#0f1419"
    else:
        urgency_label = f"Service due in {days_remaining} days"
=======
        urgency_label = "Service due in " + str(days_remaining) + " days"
        urgency_color = "#f59e0b"
        urgency_text_color = "#0f1419"
    else:
        urgency_label = "Service due in " + str(days_remaining) + " days"
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b
        urgency_color = "#14b8a6"
        urgency_text_color = "#0f1419"

    warehouse_row = ""
    if warehouse_name:
        warehouse_row = (
<<<<<<< HEAD
            f'<tr><td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;">Warehouse</td>'
            f'<td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#f1f5f9;font-weight:500;font-size:14px;text-align:right;">{warehouse_name}</td></tr>'
        )

    cta_block = ""
    if dashboard_url:
        cta_block = (
            f'<a href="{dashboard_url}" '
            f'style="display:inline-block;background:#14b8a6;color:#0f1419;padding:12px 24px;border-radius:8px;'
            f'text-decoration:none;font-weight:600;margin-top:20px;">View in PredictiX</a>'
        )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Service Reminder</title></head>
<body style="margin:0;padding:24px;background:#0f1419;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#e5e7eb;">
  <div style="max-width:560px;margin:0 auto;background:#1a1f2e;border-radius:12px;padding:32px;border:1px solid #2a3142;">
    <h1 style="color:#14b8a6;margin:0 0 8px;font-size:22px;font-weight:600;">Service Reminder</h1>
    <p style="color:#cbd5e1;font-size:15px;margin:16px 0;">Hi {user_name},</p>
    <p style="color:#cbd5e1;font-size:15px;margin:0 0 20px;">
      This is a reminder that an asset assigned to you is due for service.
    </p>

    <div style="display:inline-block;background:{urgency_color};color:{urgency_text_color};font-weight:600;padding:6px 14px;border-radius:999px;font-size:13px;margin-bottom:8px;">
      {urgency_label}
    </div>

    <table style="width:100%;border-collapse:collapse;margin:20px 0;">
      <tr>
        <td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;">Asset</td>
        <td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#f1f5f9;font-weight:500;font-size:14px;text-align:right;">{asset_name}</td>
      </tr>
      <tr>
        <td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;">Asset Code</td>
        <td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#f1f5f9;font-weight:500;font-size:14px;text-align:right;">{asset_code}</td>
      </tr>
      <tr>
        <td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;">Type</td>
        <td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#f1f5f9;font-weight:500;font-size:14px;text-align:right;">{asset_type}</td>
      </tr>
      <tr>
        <td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;">Next Service Date</td>
        <td style="padding:10px 0;border-bottom:1px solid #2a3142;color:#14b8a6;font-weight:600;font-size:14px;text-align:right;">{date_str}</td>
      </tr>
      {warehouse_row}
    </table>

    <p style="color:#cbd5e1;font-size:14px;margin:0 0 8px;">
      Please coordinate with your maintenance team or warehouse admin to schedule the service.
    </p>

    {cta_block}

    <div style="color:#64748b;font-size:12px;margin-top:28px;text-align:center;border-top:1px solid #2a3142;padding-top:16px;">
      Sent by PredictiX &middot; LankaLogix Warehouse &amp; Fleet Management<br>
      You received this because this asset is assigned to you.
    </div>
  </div>
</body>
</html>"""

    warehouse_plain = f"\nWarehouse: {warehouse_name}" if warehouse_name else ""
    plain = f"""Service Reminder

Hi {user_name},

An asset assigned to you is due for service: {urgency_label.lower()}.

Asset:               {asset_name}
Asset Code:          {asset_code}
Type:                {asset_type}
Next Service Date:   {date_str}{warehouse_plain}

Please coordinate with your maintenance team or warehouse admin to schedule the service.

PredictiX (LankaLogix)
"""
=======
            "<tr>"
            "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;'>Warehouse</td>"
            "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#f1f5f9;font-weight:500;font-size:14px;text-align:right;'>"
            + str(warehouse_name) +
            "</td></tr>"
        )

    note_block = ""
    note_plain = ""
    if admin_note and admin_note.strip():
        safe_note = (
            admin_note.strip()
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        note_block = (
            "<div style='margin:20px 0;padding:14px 16px;border-left:3px solid #14b8a6;"
            "background:#0d3a36;color:#e6fff9;border-radius:6px;font-size:14px;line-height:1.5;'>"
            "<div style='font-weight:600;color:#5eead4;font-size:12px;text-transform:uppercase;"
            "letter-spacing:0.5px;margin-bottom:6px;'>Note from your admin</div>"
            + safe_note +
            "</div>"
        )
        note_plain = "\n\nNote from your admin:\n" + admin_note.strip() + "\n"

    cta_block = ""
    if dashboard_url:
        cta_block = (
            "<a href='" + str(dashboard_url) + "' "
            "style='display:inline-block;background:#14b8a6;color:#0f1419;padding:12px 24px;"
            "border-radius:8px;text-decoration:none;font-weight:600;margin-top:20px;'>"
            "View in PredictiX</a>"
        )

    rows = (
        "<tr>"
        "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;'>Asset</td>"
        "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#f1f5f9;font-weight:500;font-size:14px;text-align:right;'>"
        + str(asset_name) + "</td></tr>"
        "<tr>"
        "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;'>Asset Code</td>"
        "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#f1f5f9;font-weight:500;font-size:14px;text-align:right;'>"
        + str(asset_code) + "</td></tr>"
        "<tr>"
        "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;'>Type</td>"
        "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#f1f5f9;font-weight:500;font-size:14px;text-align:right;'>"
        + str(asset_type) + "</td></tr>"
        "<tr>"
        "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#94a3b8;font-size:14px;'>Next Service Date</td>"
        "<td style='padding:10px 0;border-bottom:1px solid #2a3142;color:#14b8a6;font-weight:600;font-size:14px;text-align:right;'>"
        + str(date_str) + "</td></tr>"
        + warehouse_row
    )

    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Service Reminder</title></head>"
        "<body style='margin:0;padding:24px;background:#0f1419;font-family:Arial,sans-serif;color:#e5e7eb;'>"
        "<div style='max-width:560px;margin:0 auto;background:#1a1f2e;border-radius:12px;padding:32px;border:1px solid #2a3142;'>"
        "<h1 style='color:#14b8a6;margin:0 0 8px;font-size:22px;font-weight:600;'>Service Reminder</h1>"
        "<p style='color:#cbd5e1;font-size:15px;margin:16px 0;'>Hi " + str(user_name) + ",</p>"
        "<p style='color:#cbd5e1;font-size:15px;margin:0 0 20px;'>This is a reminder that an asset assigned to you is due for service.</p>"
        "<div style='display:inline-block;background:" + urgency_color + ";color:" + urgency_text_color + ";font-weight:600;"
        "padding:6px 14px;border-radius:999px;font-size:13px;margin-bottom:8px;'>"
        + urgency_label + "</div>"
        "<table style='width:100%;border-collapse:collapse;margin:20px 0;'>"
        + rows +
        "</table>"
        "<p style='color:#cbd5e1;font-size:14px;margin:0 0 8px;'>Please coordinate with your maintenance team or warehouse admin to schedule the service.</p>"
        + note_block
        + cta_block +
        "<div style='color:#64748b;font-size:12px;margin-top:28px;text-align:center;"
        "border-top:1px solid #2a3142;padding-top:16px;'>"
        "Sent by PredictiX &middot; LankaLogix Warehouse &amp; Fleet Management<br>"
        "You received this because this asset is assigned to you.</div>"
        "</div></body></html>"
    )

    warehouse_plain = ""
    if warehouse_name:
        warehouse_plain = "\nWarehouse: " + str(warehouse_name)

    plain = (
        "Service Reminder\n\nHi " + str(user_name) + ",\n\n"
        "An asset assigned to you is due for service: " + urgency_label.lower() + ".\n\n"
        "Asset: " + str(asset_name) + "\n"
        "Asset Code: " + str(asset_code) + "\n"
        "Type: " + str(asset_type) + "\n"
        "Next Service Date: " + str(date_str) + warehouse_plain + "\n\n"
        "Please coordinate with your maintenance team or warehouse admin to schedule the service."
        + note_plain + "\n\nPredictiX (LankaLogix)\n"
    )
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b
    return html, plain