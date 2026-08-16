from app.db.session import SessionLocal
from app.models import Ticket, Profile
from app.services.notification_service import NotificationService

db = SessionLocal()
try:
    ticket = db.query(Ticket).order_by(Ticket.created_at.desc()).first()
    print(f"Latest ticket: {ticket.ticket_number} - {ticket.title} (created_by: {ticket.created_by})")
    
    creator = db.query(Profile).filter(Profile.id == ticket.created_by).first() if ticket else None
    print(f"Creator: {creator.full_name if creator else 'None'} - {creator.email if creator else 'None'}")

    # Now let's test notify_on_new_ticket
    res = NotificationService.notify_on_new_ticket(db, str(ticket.id))
    print(f"notify_on_new_ticket result: {res}")
finally:
    db.close()
