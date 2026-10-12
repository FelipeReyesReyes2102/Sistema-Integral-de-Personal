from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://vacaciones:vacaciones@localhost:5432/vacaciones"
    secret_key: str = "cambia-esta-clave-en-produccion"
    # Orígenes permitidos por CORS (separados por coma). Acepta FRONTEND_ORIGINS o el antiguo CORS_ORIGINS.
    frontend_origins: str = Field("http://localhost:5173", validation_alias=AliasChoices("FRONTEND_ORIGINS", "CORS_ORIGINS"))

    # ---- Sesión (cookie HttpOnly gestionada por el backend) ----
    session_cookie_name: str = "sip_session"
    csrf_cookie_name: str = "sip_csrf"
    session_cookie_secure: bool = False      # true en producción (HTTPS)
    session_cookie_samesite: str = "lax"
    session_hours: int = 10

    # ---- Usuario y contraseña ----
    # El personal de planta normalmente no tiene cuenta Microsoft; por eso se conserva este acceso.
    password_login_enabled: bool = True
    # Roles que pueden entrar con contraseña (vacío = todos). Ej. en producción: "planta"
    password_login_roles: str = ""

    # ---- Microsoft Entra ID ----
    microsoft_auth_enabled: bool = False
    microsoft_tenant_id: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_redirect_uri: str = "http://localhost:5173/api/auth/microsoft/callback"
    microsoft_post_logout_redirect_uri: str = "http://localhost:5173/login"
    # URL pública del frontend; si se define, el cierre de sesión de Microsoft regresa a <url>/login
    microsoft_frontend_url: str = ""
    microsoft_scopes: str = "openid profile email User.Read"
    # Consulta de empleados en Microsoft Graph (permiso de aplicación User.Read.All)
    microsoft_graph_enabled: bool = False
    microsoft_authority_host: str = "https://login.microsoftonline.com"
    microsoft_graph_url: str = "https://graph.microsoft.com/v1.0"

    # True  -> los días se otorgan al cumplir cada año de servicio (criterio LFT).
    # False -> los días del año N se otorgan desde el inicio de ese año de servicio.
    vacaciones_al_cumplir_anio: bool = True
    # Meses (contados desde que se otorga el periodo) para disfrutar sus días.
    # Pasado ese plazo los días no usados se pierden. 18 = el año del periodo + 6 meses.
    meses_vigencia_periodo: int = 18

    # Textos de la pantalla de inicio
    app_nombre: str = "SIP-O"
    app_descripcion: str = "Sistema Integral de Personal O-Tek"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def microsoft_configurado(self) -> bool:
        return bool(self.microsoft_auth_enabled and self.microsoft_tenant_id and self.microsoft_client_id
                    and self.microsoft_client_secret)

    @property
    def graph_configurado(self) -> bool:
        return bool(self.microsoft_graph_enabled and self.microsoft_tenant_id and self.microsoft_client_id
                    and self.microsoft_client_secret)

    @property
    def roles_con_password(self) -> set[str]:
        return {r.strip() for r in self.password_login_roles.split(",") if r.strip()}


settings = Settings()
