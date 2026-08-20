# Modal Wan worker

This is the Kaggle Wan worker moved into Modal's GPU runtime.

1. Install Modal:
   `pip install -U modal`
2. Authenticate:
   `modal setup`
3. From this directory:
   `modal deploy modal_app.py`

The app creates two Modal Volumes:
- `ai-video-models` for Wan model weights
- `ai-video-jobs` for generated videos/job state

It uses a T4 GPU and a PyTorch CUDA image. The first generation may take longer
because ComfyUI and model files are restored into persistent storage.

After deploy, Modal prints the Web Function URLs. Set Render `MODAL_URL` to the
base URL of the `generate` endpoint (without `/generate`).

Current validation generation is intentionally short (33 frames at 16 fps).
Once it works, increase frames and add multi-scene stitching.
