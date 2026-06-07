from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from config import settings

DATABASE_URL = settings.DATABASE_URL.replace("mssql+pyodbc", "mssql+aioodbc")

engine = create_async_engine(
    DATABASE_URL,
    echo=True,
    pool_pre_ping=True,       # ← detecta conexiones muertas antes de usarlas
    pool_recycle=1800,        # ← recicla conexiones cada 30 min (Azure SQL timeout ~28 min)
    pool_size=5,              # ← conexiones persistentes en el pool
    max_overflow=10,          # ← conexiones extra bajo carga alta
    pool_timeout=30,          # ← espera máx 30s por una conexión libre
)

AsyncSessionLocal = async_sessionmaker(      # ← usa async_sessionmaker (más moderno)
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session