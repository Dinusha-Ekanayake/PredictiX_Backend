from typing import Dict, Any, List

class AIInsightService:
    def generate_insights(self, context: Dict[str, Any]) -> List[str]:
        """
        Mock AI insight generation. In a real system, this would call an LLM API
        (like OpenAI or Vertex AI) with the context to get these bullet points.
        """
        insights = []
        asset = context.get("asset", {})
        
        # Rule-based generation for demonstration
        if asset.get("status") == "CRITICAL" or int(asset.get("health_score", "0").replace("%", "")) < 70:
            insights.append("Predicted maintenance earlier than scheduled (based on risk trend).")
        else:
            insights.append("Asset health is stable; standard maintenance schedule applies.")
            
        confidence = asset.get("prediction_confidence", "0")
        if int(confidence.replace("%", "")) > 80:
             insights.append("Confidence reflects high available sensor/log coverage.")
        else:
             insights.append("Confidence is moderate; consider increasing sensor data frequency.")
             
        variance = asset.get("cost_variance", "+0%")
        if variance.startswith("+") and int(variance.replace("+", "").replace("%", "")) > 10:
             insights.append("Estimated cost variance indicates recent maintenance cost deviation.")
             
        if not insights:
            insights.append("No significant deviations detected in operational behavior.")
            
        return insights
