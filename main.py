from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine
from config import settings
import db_models
from routers import auth as auth_router
from routers import candidates, votes, tenants, packages, payments
from routers.tickets import router_tickets          # ← import aquí arriba ✅

app = FastAPI(                                      # ← app se define PRIMERO ✅
    title=f"Podium App — API",
    version="2.0.0",
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url=None,
)

# ... middleware, startup event, sin cambios ...

# Routers existentes
app.include_router(auth_router.router)
app.include_router(candidates.router)
app.include_router(votes.router)

# Routers Día 7
app.include_router(tenants.router)
app.include_router(packages.router_packages)
app.include_router(payments.router_payments)

# Router boletos — TICK-1                          # ← include aquí abajo ✅
app.include_router(router_tickets)

@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.APP_ENV}