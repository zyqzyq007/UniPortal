from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

from app.routers import project, testcase

app = FastAPI(title="C Unit Test Generator", version="0.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(testcase.router)
app.include_router(project.router)

@app.get("/api/health")
async def health_check():
    return {"message": "C Unit Test Generator API is running"}

if os.path.isdir("Frontend/dist"):
    app.mount("/", StaticFiles(directory="Frontend/dist", html=True), name="static")
