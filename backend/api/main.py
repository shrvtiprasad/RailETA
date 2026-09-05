from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv
import os
from pathlib import Path

from backend.api.routes.trains import router as trains_router
from backend.api.routes.eta import router as eta_router
from backend.api.routes.features import router as features_router
from backend.api.routes.connections import router as connections_router
from backend.api.routes.api_keys import router as api_keys_router
from backend.api.routes.public import router as public_router
from backend.api.middleware import api_http_exception_handler, api_middleware, unhandled_exception_handler, validation_exception_handler


load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def _cors_origins() -> list[str]:
    configured = os.getenv("RAILETA_CORS_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
app = FastAPI(
    title="RailETA API",
    description="Dynamic Railway ETA Prediction API",
    version="1.0.0",
)

# Allow the React frontend to communicate with the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(api_middleware)
app.add_exception_handler(StarletteHTTPException, api_http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


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
    eta_router,
    prefix="/api/v1",
)

app.include_router(
    features_router,
    prefix="/api/v1",
)

app.include_router(
    connections_router,
    prefix="/api/v1",
)

app.include_router(
    public_router,
    prefix="/api/v1",
)

app.include_router(api_keys_router, prefix="/api/v1")
