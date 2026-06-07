from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Base de datos y servicios
    DATABASE_URL: str
    REDIS_URL: str

    # JWT
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # Entorno
    APP_ENV: str = "development"

    # Tenant — identidad del certamen que usa esta instancia
    TENANT_SLUG: str = "mimx"
    TENANT_NAME: str = "Mister International México"
    TENANT_DOMAIN: str = "misterinternational.mx"

    class Config:
        env_file = ".env"

settings = Settings()