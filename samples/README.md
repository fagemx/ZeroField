# The Last Signal — playback fixtures

All PNG/MP4 files in this directory are original procedural illustrations and 3-second animations made by `generate.py`. They are **test fixtures, not FLUX or LTX model renders**, not filmed human performances, and not evidence of model quality or motion/object transfer. The remastered example applies a deterministic color grade; the split clip demonstrates synchronized playback. `first_frame_vfx01.png` is extracted from frame 0 of the encoded source, `motion_structure_vfx01.mp4` contains a continuous edge guide with the source frame rate/audio, and `anchor_keyframe_vfx01.png` is an illustrative original drawing rather than a model-generated character swap.

Kael is a fictional, faceless courier; the observatory and recorder are original geometric drawings. No third-party footage, likenesses, copyrighted characters or external audio are used. MP4s are H.264/AAC, 24 fps, with a quiet synthesized tone and faststart indexing.

The fixture images, animation media and generator in this directory are dedicated to the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Code elsewhere in the repository retains its MIT license.

To reproduce with Pillow and FFmpeg installed:

```powershell
python samples/generate.py
```

Replace these fixtures with reviewed model renders or your own footage during a production. The launcher fills only empty demo media cells once and preserves existing takes, prompts and edits.
