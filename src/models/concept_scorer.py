import os
import yaml
import polars as pl
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
import pickle

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
with open(CONFIG_PATH, "r") as f:
    CONFIG = yaml.safe_load(f)

class ConceptScorer:
    def __init__(self):
        self.model = None
        self.genre_encoder = LabelEncoder()
        self.model_path = os.path.join(CONFIG['storage']['gold_path'], "concept_model.pkl")
        
    def train(self):
        """Trains the XGBoost model on Gold data."""
        gold_dir = CONFIG['storage']['gold_path']
        try:
            df = pl.read_parquet(os.path.join(gold_dir, "gold_metrics_*.parquet"))
        except:
            print("No training data found.")
            return
            
        print(f"Training on {len(df)} records...")
        
        if len(df) < 10:
            print("Not enough data to train XGBoost. Using mock logic.")
            self.model = "MOCK"
            return

        # Prepare Features
        # X: Genre (Encoded), Author (Encoded - maybe too high card), Title Length
        # y: log(views)
        
        pdf = df.to_pandas()
        
        # Encode Genre
        pdf['genre_encoded'] = self.genre_encoder.fit_transform(pdf['genre'].fillna("Unknown"))
        
        X = pdf[['genre_encoded']]
        y = np.log1p(pdf['views'])
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        self.model = xgb.XGBRegressor(objective='reg:squarederror', n_estimators=100)
        self.model.fit(X_train, y_train)
        
        score = self.model.score(X_test, y_test)
        print(f"Model R2 Score: {score:.4f}")
        
        # Save
        with open(self.model_path, "wb") as f:
            pickle.dump({"model": self.model, "encoder": self.genre_encoder}, f)
            
    def predict(self, genre: str, title: str) -> dict:
        """Predicts success score for a new concept."""
        if self.model == "MOCK":
            # Simple heuristic for demo
            score = 50
            if "Romance" in genre: score += 20
            if "Fantasy" in genre: score += 15
            if len(title) > 10: score += 5
            return {"predicted_score": score, "tier": "B"}
            
        # Real Inference
        try:
            genre_code = self.genre_encoder.transform([genre])[0]
        except:
            genre_code = 0 # Fallback
            
        pred_log = self.model.predict([[genre_code]])[0]
        pred_views = np.expm1(pred_log)
        
        return {
            "predicted_views_30d": int(pred_views), 
            "tier": "S" if pred_views > 1000000 else "A" if pred_views > 100000 else "B"
        }

if __name__ == "__main__":
    scorer = ConceptScorer()
    scorer.train()
    
    # Test Prediction
    print("\nTest Prediction:")
    print(scorer.predict("Romance", "The Duke's Secret"))
