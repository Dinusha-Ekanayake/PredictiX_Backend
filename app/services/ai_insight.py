from typing import Dict, Any, List

class AIInsightService:
    def generate_insights(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mock AI insight generation. In a real system, this would call an LLM API
        (like OpenAI or Vertex AI) with the context to get these bullet points.
        """
        asset = context.get("asset", {})
        metrics = context.get("metrics", {})
        
        # Rule-based generation for demonstration
        maintenance_insights = []
        if asset.get("status") == "CRITICAL" or metrics.get("health_score", 100) < 70:
            maintenance_insights.append("Predicted maintenance earlier than scheduled (based on risk trend).")
        else:
            maintenance_insights.append("Asset health is stable; standard maintenance schedule applies.")
            
        confidence = asset.get("prediction_confidence", "0%")
        if int(confidence.replace("%", "")) > 80:
             maintenance_insights.append("Confidence reflects high available sensor/log coverage.")
        else:
             maintenance_insights.append("Confidence is moderate; consider increasing sensor data frequency.")
             
        variance = asset.get("cost_variance", "+0%")
        if variance.startswith("+") and int(variance.replace("+", "").replace("%", "")) > 10:
             maintenance_insights.append("Estimated cost variance indicates recent maintenance cost deviation.")
             
        if not maintenance_insights:
            maintenance_insights.append("No significant deviations detected in operational behavior.")
            
        return {
            "executive_summary": "The asset is currently operating within expected parameters, although some maintenance optimization is possible based on recent sensor data trends.",
            "maintenance_insights": maintenance_insights,
            "recommendations": {
                "critical": [],
                "high": ["Check hydraulic system pressure for minor fluctuations."],
                "medium": ["Schedule routine filter replacement in the next 30 days."]
            },
            "cost_analysis": {
                "maintenance_cost_mtd": metrics.get("total_cost", 0) * 0.1,
                "downtime_cost_mtd": metrics.get("total_downtime_hours", 0) * 5000,
                "predicted_repair_cost": metrics.get("estimated_cost", 0),
                "predicted_downtime_days": 2
            },
            "future_predictions": {
                "next_failure_probability": metrics.get("failure_probability", 0) / 100,
                "optimal_maintenance_date": metrics.get("predicted_maintenance_date", "—"),
                "suggested_maintenance_type": "Preventive",
                "predicted_maintenance_cost_next_6_months": metrics.get("estimated_cost", 0) * 2,
                "predicted_performance_in_6_months": "92%",
                "estimated_remaining_life": "4.5 years"
            },
            "operational_efficiency": {
                "optimisation_recommendations": ["Optimize route planning to reduce idle hours by 15%."]
            },
            "conclusion": "Continue regular monitoring. The predicted maintenance window is sufficient for current operational loads."
        }
