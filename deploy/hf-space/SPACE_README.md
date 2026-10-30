---
title: ZeroField Studio (read-only demo)
emoji: 🎈
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Read-only tour of an open-weights AI film studio
---

# ZeroField Studio — read-only demo

This Space runs the real ZeroField studio with its sample production, **Updraft**: the Cast & sets wall (each character's face, front, back and sheet; the props and their states), the ten shots with their first frames and takes, the compiled prompt of every shot (**See the full prompt** in a shot's composer), and the film window. All media are FLUX 3 Klein and LTX-2.5 renders made through the studio on one RTX 4090.

The 88-second Updraft one-take is not a shot in this production: it was made from one Blender previs with nine chained Layout Render slices, a composited push-through and an ACE-Step score, using the scripts in `tools/oner/`. Watch it in the repository: [`samples/updraft/updraft_oner.mp4`](https://github.com/fagemx/ZeroField/blob/main/samples/updraft/updraft_oner.mp4).

Nothing can be changed or generated here: every visitor is the same demo guest, and the front proxy passes only reads and previews. The Space reseeds from scratch whenever it restarts. To make films, run ZeroField on your own GPU: <https://github.com/fagemx/ZeroField>.

How this Space is built: `deploy/hf-space/` in the repository (Dockerfile, seed, nginx boundary).
