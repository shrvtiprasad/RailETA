from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes.trains import router as trains_router
from backend.api.routes.live import router as live_router
app = FastAPI(
    title="RailETA API",
    description="Dynamic Railway ETA Prediction API",
    version="1.0.0",
)

# Allow the React frontend to communicate with the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "service": "RailETA API",
        "version": "1.0.0",
    }


app.include_router(
    trains_router,
    prefix="/api/v1",
)
app.include_router(
    trains_router,
    prefix="/api/v1",
)

app.include_router(
    live_router,
    prefix="/api/v1",
)