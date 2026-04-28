from sqlalchemy.orm import Session
from app.models import Asset, Ticket, MaintenanceEvent 
from datetime import datetime


def build_asset_context(db: Session, asset_id: int):

    asset = db.query(Asset).filter(Asset.id == asset_id).first()

    tickets = db.query(Ticket).filter(Ticket.asset_id == asset_id).all()
    maintenance = db.query(MaintenanceEvent).filter(MaintenanceEvent.asset_id == asset_id).all()

    # --- Metrics ---
    total_cost = sum([m.cost for m in maintenance if m.cost])
    total_events = len(maintenance)

    preventive = len([m for m in maintenance if m.type == "preventive"])
    corrective = len([m for m in maintenance if m.type == "corrective"])

    preventive_ratio = (preventive / total_events * 100) if total_events else 0

    open_tickets = len([t for t in tickets if t.status == "open"])

    avg_failure_prob = (
        sum(p.failure_probability for p in predictions) / len(predictions)
        if predictions else 0
    )

    ctx = {
        "generated_date": datetime.now().strftime("%B %d, %Y"),

        "asset_info": {
            "id": asset.id,
            "name": asset.name,
            "type": asset.type,
            "status": asset.status,
            "purchase_date": str(asset.purchase_date),
        },

        "health_metrics": {
            "failure_probability": round(avg_failure_prob * 100, 2),
        },

        "maintenance_metrics": {
            "total_events": total_events,
            "preventive_ratio": round(preventive_ratio, 1),
            "corrective_ratio": round(100 - preventive_ratio, 1),
            "total_cost": total_cost,
        },

        "ticket_metrics": {
            "open_tickets": open_tickets,
        }
    }

    return ctx

#ADD LLM

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
import json

SYSTEM_PROMPT = """
You are a senior asset reliability engineer.

Generate an executive-level asset report based ONLY on given structured data.

Return valid JSON:

{
"executive_summary": "...",
"risk_analysis": "...",
"maintenance_analysis": "...",
"recommendations": {
"critical": [],
"high": [],
"medium": []
},
"conclusion": "..."
}
"""
#run_asset_agent()

def run_asset_agent(db: Session, asset_id: int):

    ctx = build_asset_context(db, asset_id)

    llm = ChatGroq(
        model="llama3-70b-8192",
        temperature=0.2
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Generate report using this data:\n{json.dumps(ctx, indent=2)}")
    ]

    response = llm.invoke(messages)

    ai_output = json.loads(response.content)

    return {
        "context": ctx,
        "ai": ai_output
    }
    
    