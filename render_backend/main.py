import os
import uuid
import requests

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


app = FastAPI(title="AI Video Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# MODAL ENDPOINTS
# ---------------------------------------------------------

MODAL_GENERATE_URL = os.getenv("MODAL_GENERATE_URL", "").rstrip("/")
MODAL_JOBS_URL = os.getenv("MODAL_JOBS_URL", "").rstrip("/")
MODAL_VIDEO_URL = os.getenv("MODAL_VIDEO_URL", "").rstrip("/")


# Render's in-memory job cache.
# This is sufficient for the single-user presentation version.
JOBS = {}


class Req(BaseModel):
    mode: str = "creative"
    topic: str


# ---------------------------------------------------------
# BASIC ROUTES
# ---------------------------------------------------------

@app.get("/")
def root():
    return {
        "service": "AI Video Studio API",
        "status": "ok",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "modal_configured": all(
            [
                MODAL_GENERATE_URL,
                MODAL_JOBS_URL,
                MODAL_VIDEO_URL,
            ]
        ),
    }


# ---------------------------------------------------------
# START GENERATION
# ---------------------------------------------------------

@app.post("/generate")
def generate(req: Req):

    if not req.topic.strip():
        raise HTTPException(
            status_code=400,
            detail="Topic is required",
        )

    if not MODAL_GENERATE_URL:
        raise HTTPException(
            status_code=503,
            detail="MODAL_GENERATE_URL is not configured",
        )

    job_id = str(uuid.uuid4())

    try:
        response = requests.post(
            MODAL_GENERATE_URL,
            json={
                "job_id": job_id,
                "mode": req.mode,
                "topic": req.topic,
            },
            timeout=30,
        )

        response.raise_for_status()

        modal_data = response.json()

        JOBS[job_id] = {
            "id": job_id,
            "mode": req.mode,
            "topic": req.topic,
            "status": modal_data.get("status", "queued"),
            "message": modal_data.get(
                "message",
                "GPU job queued.",
            ),
        }

        return JOBS[job_id]

    except Exception as e:

        JOBS[job_id] = {
            "id": job_id,
            "mode": req.mode,
            "topic": req.topic,
            "status": "failed",
            "message": str(e),
        }

        raise HTTPException(
            status_code=502,
            detail=f"Modal request failed: {e}",
        )


# ---------------------------------------------------------
# CHECK JOB STATUS
# ---------------------------------------------------------

@app.get("/jobs/{job_id}")
def job(job_id: str):

    if job_id not in JOBS:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    if not MODAL_JOBS_URL:
        raise HTTPException(
            status_code=503,
            detail="MODAL_JOBS_URL is not configured",
        )

    try:

        response = requests.get(
            MODAL_JOBS_URL,
            params={
                "job_id": job_id,
            },
            timeout=20,
        )

        response.raise_for_status()

        modal_data = response.json()

        JOBS[job_id].update(
            {
                "status": modal_data.get(
                    "status",
                    JOBS[job_id].get("status"),
                ),
                "message": modal_data.get(
                    "message",
                    JOBS[job_id].get("message"),
                ),
            }
        )

        # When Modal finishes, expose the Render video URL.
        if modal_data.get("status") == "completed":
            JOBS[job_id]["video_url"] = f"/video/{job_id}"

        return JOBS[job_id]

    except Exception as e:

        JOBS[job_id]["message"] = (
            f"Status check failed: {e}"
        )

        return JOBS[job_id]


# ---------------------------------------------------------
# VIDEO PROXY
# ---------------------------------------------------------

@app.get("/video/{job_id}")
def video(job_id: str):

    if not MODAL_VIDEO_URL:
        raise HTTPException(
            status_code=503,
            detail="MODAL_VIDEO_URL is not configured",
        )

    try:

        response = requests.get(
            MODAL_VIDEO_URL,
            params={
                "job_id": job_id,
            },
            stream=True,
            timeout=60,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail="Video is not available yet.",
            )

        content_type = response.headers.get(
            "content-type",
            "video/mp4",
        )

        return StreamingResponse(
            response.iter_content(
                chunk_size=1024 * 1024
            ),
            media_type=content_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="ai-video-{job_id}.mp4"'
                )
            },
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=502,
            detail=f"Video retrieval failed: {e}",
        )