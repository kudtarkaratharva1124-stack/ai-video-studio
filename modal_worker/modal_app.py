import os, json, uuid, subprocess, time, shutil, random
from pathlib import Path
import modal

app=modal.App("ai-video-studio")
MODEL_VOL=modal.Volume.from_name("ai-video-models", create_if_missing=True)
JOB_VOL=modal.Volume.from_name("ai-video-jobs", create_if_missing=True)

# PyTorch CUDA runtime; ComfyUI and ffmpeg are added at image build time.
IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "ffmpeg",
        "git",
        "build-essential",
    )
    .pip_install(
        "fastapi[standard]",
        "requests",
        "edge-tts",
        "huggingface_hub",
        "torch",
    )
)


BASE=Path("/workspace")
COMFY=BASE/"ComfyUI"
MODELS=Path("/models")
JOBS=Path("/jobs")

WAN_FILES=[
    ("split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors",
     MODELS/"diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors",2.0),
    ("split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
     MODELS/"text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",5.0),
    ("split_files/vae/wan_2.1_vae.safetensors",
     MODELS/"vae/wan_2.1_vae.safetensors",0.1),
]

def ensure_models():
    from huggingface_hub import hf_hub_download
    for remote,target,min_gb in WAN_FILES:
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.stat().st_size >= min_gb*1024**3:
            print("[PASS] existing model",target)
            continue
        print("[RUN] downloading",remote)
        hf_hub_download(
            repo_id="Comfy-Org/Wan_2.1_ComfyUI_repackaged",
            filename=remote,
            local_dir=str(MODELS),
            local_dir_use_symlinks=False,
        )
        # HF preserves nested path under local_dir.
        nested=MODELS/remote
        if nested.exists() and nested.resolve()!=target.resolve():
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(str(nested),str(target))
        if not target.exists():
            raise RuntimeError("Model missing after download: "+str(target))

def ensure_comfy():
    if not (COMFY/"main.py").exists():
        subprocess.run(["git","clone","--depth","1","https://github.com/Comfy-Org/ComfyUI.git",str(COMFY)],check=True)
        subprocess.run(["python","-m","pip","install","-q","-r",str(COMFY/"requirements.txt")],check=True)
    # Use the persistent model volume as ComfyUI's model directory.
    cm=COMFY/"models"
    if cm.exists() and not cm.is_symlink():
        shutil.rmtree(cm)
    if not cm.exists():
        cm.symlink_to(MODELS)

def api_get(path):
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:8188"+path,timeout=30) as r:
        return json.loads(r.read())

def api_post(path,obj):
    import urllib.request
    data=json.dumps(obj).encode()
    req=urllib.request.Request("http://127.0.0.1:8188"+path,data=data,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read())

def start_comfy():
    try:
        return api_get("/system_stats")
    except Exception:
        pass
    log=(JOBS/"comfyui.log").open("a")
    p=subprocess.Popen(["python",str(COMFY/"main.py"),"--listen","127.0.0.1","--port","8188"],stdout=log,stderr=subprocess.STDOUT)
    for _ in range(90):
        if p.poll() is not None:
            raise RuntimeError((JOBS/"comfyui.log").read_text()[-10000:])
        try: return api_get("/system_stats")
        except Exception: time.sleep(2)
    raise TimeoutError("ComfyUI startup timeout")

def workflow(prompt,seed):
    return {
      "37":{"class_type":"UNETLoader","inputs":{"unet_name":"wan2.1_t2v_1.3B_fp16.safetensors","weight_dtype":"default"}},
      "38":{"class_type":"CLIPLoader","inputs":{"clip_name":"umt5_xxl_fp8_e4m3fn_scaled.safetensors","type":"wan","device":"default"}},
      "39":{"class_type":"VAELoader","inputs":{"vae_name":"wan_2.1_vae.safetensors"}},
      "40":{"class_type":"EmptyHunyuanLatentVideo","inputs":{"width":832,"height":480,"length":33,"batch_size":1}},
      "48":{"class_type":"ModelSamplingSD3","inputs":{"model":["37",0],"shift":8}},
      "6":{"class_type":"CLIPTextEncode","inputs":{"clip":["38",0],"text":prompt}},
      "7":{"class_type":"CLIPTextEncode","inputs":{"clip":["38",0],"text":"blurry, low quality, distorted, static, watermark, subtitles, text, logo, deformed"}},
      "3":{"class_type":"KSampler","inputs":{"model":["48",0],"positive":["6",0],"negative":["7",0],"latent_image":["40",0],"seed":seed,"steps":30,"cfg":6,"sampler_name":"uni_pc","scheduler":"simple","denoise":1}},
      "8":{"class_type":"VAEDecode","inputs":{"samples":["3",0],"vae":["39",0]}},
      "47":{"class_type":"SaveWEBM","inputs":{"images":["8",0],"filename_prefix":"wan_clip","codec":"vp9","fps":16,"crf":28}}
    }

def newest_video(after):
    out=COMFY/"output"
    files=[p for p in out.rglob("*") if p.is_file() and p.suffix.lower() in {".webm",".mp4",".mkv"} and p.stat().st_mtime>=after]
    if not files: raise RuntimeError("Wan completed but no video output found")
    return max(files,key=lambda p:p.stat().st_mtime)

def run_job(job_id,mode,topic):
    JOBS.mkdir(parents=True, exist_ok=True)
    job=JOBS/f"{job_id}.json"
    def state(s,**kw):
        d={"id":job_id,"status":s,**kw}; job.write_text(json.dumps(d,indent=2)); return d
    try:
        state("starting",message="Starting Modal GPU.")
        import torch
        if not torch.cuda.is_available(): raise RuntimeError("CUDA unavailable")
        state("restoring",message="Checking ComfyUI and Wan models.")
        ensure_comfy(); ensure_models(); start_comfy()
        prompt=(topic if mode=="creative" else
                f"Create a cinematic promotional short for this business/product: {topic}")
        state("generating",message="Wan 2.1 is generating the video.")
        started=time.time()
        r=api_post("/prompt",{"prompt":workflow(prompt,random.randint(1,2**31-1)),"client_id":job_id})
        pid=r["prompt_id"]
        deadline=time.time()+1800
        while time.time()<deadline:
            h=api_get("/history/"+pid)
            if pid in h:
                if h[pid].get("status",{}).get("status_str")=="error":
                    raise RuntimeError(json.dumps(h[pid],indent=2))
                break
            time.sleep(5)
        else: raise TimeoutError("Wan generation timeout")
        src=newest_video(started)
        state("rendering",message="Adding narration and rendering final video.")
        voice=JOBS/f"{job_id}.mp3"
        narration=("They said this place had been abandoned for decades. "
                   "But every night, the lights came back on.")
        subprocess.run(["edge-tts","--voice","en-US-AriaNeural","--text",narration,"--write-media",str(voice)],check=True)
        probe=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(src)],capture_output=True,text=True,check=True)
        dur=float(probe.stdout.strip())
        final=JOBS/f"{job_id}.mp4"
        vf="scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
        ffmpeg_result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", str(src),
                "-i", str(voice),
                "-vf", vf,
                "-r", "30",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(final),
            ],
            capture_output=True,
            text=True,
        )

        if ffmpeg_result.returncode != 0:
            raise RuntimeError(
                "FFmpeg failed.\n\n"
                "STDOUT:\n"
                + ffmpeg_result.stdout[-4000:]
                + "\n\nSTDERR:\n"
                + ffmpeg_result.stderr[-8000:]
            )
        state("completed",message="Video ready.",video_url=f"/video/{job_id}")
    except Exception as e:
        state("failed",message=str(e))

@app.function(
    image=IMAGE,
    gpu="T4",
    timeout=1800,
    volumes={"/models":MODEL_VOL,"/jobs":JOB_VOL},
)
def generate_job(job_id,mode,topic):
    run_job(job_id,mode,topic)
    JOB_VOL.commit()

@app.function(
    image=IMAGE,
    volumes={"/jobs":JOB_VOL},
)
@modal.fastapi_endpoint(method="POST",docs=True)
def generate(payload:dict):
    job_id=payload.get("job_id") or str(uuid.uuid4())
    generate_job.spawn(job_id,payload.get("mode","creative"),payload.get("topic",""))
    return {"id":job_id,"status":"queued","message":"GPU job queued."}

@app.function(
    image=IMAGE,
    volumes={"/jobs":JOB_VOL},
)
@modal.fastapi_endpoint(method="GET")
def jobs(job_id:str):
    p=JOBS/f"{job_id}.json"
    if not p.exists(): return {"id":job_id,"status":"queued","message":"Waiting for worker."}
    d=json.loads(p.read_text())
    if d.get("video_url"): d["video_url"]=jobs.get_web_url().rsplit("/jobs",1)[0]+"/video/"+job_id
    return d

@app.function(
    image=IMAGE,
    volumes={"/jobs":JOB_VOL},
)
@modal.fastapi_endpoint(method="GET")
def video(job_id:str):
    from fastapi.responses import FileResponse, JSONResponse
    p=JOBS/f"{job_id}.mp4"
    if not p.exists(): return JSONResponse({"status":"not_ready"},status_code=404)
    return FileResponse(str(p),media_type="video/mp4",filename="final_video.mp4")
