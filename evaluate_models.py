import pickle
import pandas as pd

COMPONENTS = ['brake', 'tire', 'battery', 'oil', 'hydraulic']
print('Model Evaluation Results:\\n')
for comp in COMPONENTS:
    try:
        model = pickle.load(open(f"app/ai/models/survival_analysis/{comp}_aft.pkl", "rb"))
        print(f"[{comp.upper()}] Concordance Index: {model.concordance_index_:.3f}")
        
        # Print top 3 most impactful features
        params = model.params_.loc['lambda_']
        # Absolute value of coefficient dictates impact on timescale
        top_features = params.abs().sort_values(ascending=False).head(3)
        print(f"Top drivers of component lifespan:")
        for feat, val in top_features.items():
            print(f"  - {feat} (Impact: {'Negative' if params[feat] < 0 else 'Positive'})")
        print()
    except Exception as e:
        print(f"Failed to load {comp}: {e}")
