from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()
Instrumentator().instrument(app).expose(app)  # GET /metrics


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
