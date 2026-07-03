from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from loguru import logger
import time

from app.config import settings
from app.routers import products, reviews, agent
from app.database import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AgentMart backend starting up...")
    # Create DB tables on startup (use Alembic migrations in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")
    yield
    logger.info("AgentMart backend shutting down...")


app = FastAPI(
    title="AgentMart API",
    description="AI-powered shopping guide: multi-platform product aggregation + video review analysis",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time * 1000, 2)) + "ms"
    return response


# Routers
app.include_router(products.router, prefix="/api/products", tags=["Products"])
app.include_router(reviews.router, prefix="/api/reviews", tags=["Reviews"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])


@app.get("/health", tags=["System"])
async def health_check():
    return JSONResponse({
        "status": "ok",
        "version": "1.0.0",
        "env": settings.APP_ENV,
    })


@app.get("/", tags=["System"])
async def root():
    return {"message": "Welcome to AgentMart API", "docs": "/docs"}
