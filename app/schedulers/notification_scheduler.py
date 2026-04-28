import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.db import SessionLocal
from app.services.notification_service import check_and_send_maintenance_notifications

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

def run_maintenance_notification_job():
    """
    Job function to run the maintenance notification check.
    It creates a new database session and closes it after the task.
    """
    db = SessionLocal()
    try:
        logger.info("Starting scheduled maintenance notification check...")
        result = check_and_send_maintenance_notifications(db)
        logger.info(f"Maintenance notification check completed: {result}")
    except Exception as e:
        logger.error(f"Error during maintenance notification job: {e}")
    finally:
        db.close()

def setup_scheduler():
    """
    Configures and starts the scheduler.
    """
    # Run daily at 8:00 AM
    scheduler.add_job(
        run_maintenance_notification_job, 
        'cron', 
        hour=8, 
        minute=0, 
        id="maintenance_notifications",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Notification scheduler started.")

def shutdown_scheduler():
    """
    Shuts down the scheduler.
    """
    scheduler.shutdown()
    logger.info("Notification scheduler stopped.")
