from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine
from config import settings
import db_models
from routers import auth as auth_router
from routers import candidates, votes

app = FastAPI(
    title=f"{settings.TENANT_NAME} — API",
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url=None,
)

_origins = [
    "http://localhost:4200",
    f"https://{settings.TENANT_DOMAIN}",
    f"https://www.{settings.TENANT_DOMAIN}",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(db_models.Base.metadata.create_all)
        print("🚀 Tablas verificadas — API arriba")
    except Exception as e:
        print(f"⚠️ DB no disponible al arrancar: {e} — continuando sin tablas")

app.include_router(auth_router.router)
app.include_router(candidates.router)
app.include_router(votes.router)

@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.APP_ENV}