from fastapi import FastAPI
from app.readiness import router as readiness_router
from app.release_info import router as release_info_router

from app.routers import posts, users

app = FastAPI()

app.include_router(users.router)
app.include_router(posts.router)
app.include_router(readiness_router)
app.include_router(release_info_router)


@app.get("/")
def root():
    return {"status": "API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}
