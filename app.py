"""Inicia interface web com upload fragmentado sem HTTP 413."""
import os
import uvicorn
from webapp import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT","7860")), log_level="info")
