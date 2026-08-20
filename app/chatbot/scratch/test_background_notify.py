from app.db.session import SessionLocal
from app.models import Ticket
from app.services.notification_service import NotificationService

db = SessionLocal()
ticket = db.query(Ticket).order_by(Ticket.created_at.desc()).first()
ticket_id = str(ticket.id)
db.close()  # Close the request session!

print("Testing notify_on_new_ticket with closed/None db...")
# Pass None to simulate FastAPI BackgroundTasks where the request session has closed
res = NotificationService.notify_on_new_ticket(None, ticket_id)
print(f"Result with None session: {res}")
