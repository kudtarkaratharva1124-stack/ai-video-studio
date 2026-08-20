# AI Video Studio — Modal Wan backend

This version moves the tested Wan/ComfyUI worker concept from Kaggle into Modal.
Architecture:

Vercel -> Render -> Modal GPU -> final video -> Vercel

No Neon is required for the single-user presentation.

The Modal worker uses a T4, persistent Volumes for model/job files, and an
asynchronous GPU job so the frontend is not blocked by generation.

Deploy Modal first, then put the generated endpoint into Render's MODAL_URL.
