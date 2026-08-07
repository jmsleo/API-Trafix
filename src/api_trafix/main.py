from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api_trafix import models
from api_trafix.config.database import init_db
from api_trafix.config.redis import close_redis
from api_trafix.config.settings import get_settings
from api_trafix.core.middleware import RequestBodyLimitMiddleware, SecurityHeadersMiddleware
from api_trafix.routes.auth import router as auth_router
from api_trafix.routes.users import router as users_router
from api_trafix.routes import member, vehicle_type, shift


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_redis()


app = FastAPI(
    title=get_settings().app_name,
    version=get_settings().app_version,
    description="Fix Trafing System API - Admin, Teknisi, Operator",
    lifespan=lifespan,
    docs_url="/docs" if get_settings().debug else None,
    redoc_url="/redoc" if get_settings().debug else None,
)

app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "Request validation failed", "errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    settings = get_settings()
    if settings.debug:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error", "error": str(exc)},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(vehicle_type.router)
app.include_router(shift.router)
app.include_router(member.router)

@app.get("/")
async def root():
    return {
        "app": get_settings().app_name,
        "version": get_settings().app_version,
        "status": "running",
        "docs": "/docs" if get_settings().debug else None,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/healt", include_in_schema=False)
async def health_check_legacy():
    return {"status": "healthy"}
