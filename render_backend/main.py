import os, uuid, requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app=FastAPI(title="AI Video Studio API")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

MODAL_URL=os.getenv("MODAL_URL","").rstrip("/")
JOBS={}

class Req(BaseModel):
    mode:str="creative"
    topic:str

@app.get("/")
def root(): return {"service":"AI Video Studio API","status":"ok"}

@app.get("/health")
def health(): return {"status":"ok","modal_configured":bool(MODAL_URL)}

@app.post("/generate")
def generate(req:Req):
    if not req.topic.strip(): raise HTTPException(400,"Topic is required")
    if not MODAL_URL: raise HTTPException(503,"MODAL_URL is not configured")
    job_id=str(uuid.uuid4())
    try:
        r=requests.post(MODAL_URL+"/generate",json={
            "job_id":job_id,"mode":req.mode,"topic":req.topic
        },timeout=20)
        r.raise_for_status()
        d=r.json()
        JOBS[job_id]={"id":job_id,"mode":req.mode,"topic":req.topic,**d}
        return JOBS[job_id]
    except Exception as e:
        JOBS[job_id]={"id":job_id,"mode":req.mode,"topic":req.topic,"status":"failed","message":str(e)}
        raise HTTPException(502,f"Modal request failed: {e}")

@app.get("/jobs/{job_id}")
def job(job_id:str):
    if job_id not in JOBS: raise HTTPException(404,"Job not found")
    try:
        r=requests.get(MODAL_URL+"/jobs/"+job_id,timeout=15)
        if r.ok:
            JOBS[job_id].update(r.json())
    except Exception as e:
        JOBS[job_id]["message"]=f"Status check: {e}"
    return JOBS[job_id]
