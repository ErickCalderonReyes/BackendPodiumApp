from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Base de datos y servicios
    DATABASE_URL: str
    REDIS_URL: str

    # Pasarela de pagos y Frontend (Día 7)
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET:str
    FRONTEND_URL: str = "http://localhost:4200"

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

    # RESEND
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "Mister International México <onboarding@resend.dev>"

    # ════════════════════════════════════════════════════════
    # CONFIGURACIÓN CORRECTA PARA PYDANTIC V2
    # ════════════════════════════════════════════════════════
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Evita que truene si hay variables de más en tu .env que no usas aquí
    )
settings = Settings()
