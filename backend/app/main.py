from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

app = FastAPI(title="Routapse", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors, allow_methods=["*"], allow_headers=["*"])

if settings.role in ("all", "gateway"):
    from .api_gateway import api as gateway
    app.include_router(gateway)
if settings.role in ("all", "admin"):
    from .api_admin import api as admin
    app.include_router(admin)


@app.get("/healthz")
def healthz():
    return {"ok": True, "role": settings.role}
