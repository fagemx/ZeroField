# Updraft: the ZeroField showcase production

`updraft/production.json` is the single source of the showcase: the director brief, the episode look, twelve assets (two characters, four locations, four props and two prop states) with their locked descriptions, voice and acting profiles, location maps, light logic and shape locks, and a ten-shot, about forty-second slate. The launcher (`run_studio.py`) and the `zerofield_studio` project template both read it, and `docs/examples/UPDRAFT_BIBLE.md` is a readable copy.

Updraft is original: a trainee pilot's burner dies over a red canyon at sunrise and her instructor will not take the controls. No third-party footage, likenesses, characters or text are used.

## Media

Pictures and clips are generated with open-weights models only (FLUX 3 Klein for assets and first frames, LTX-2.5 for video and sound, run through ComfyUI) and are added under `updraft/` together with `updraft/manifest.json`:

```json
{"items": [{"tab": "soul-cast", "code": "CAST-01", "column": "Reference Image", "panel": "face",
            "file": "noa_face.png", "card": "flux-soul-cast", "seed": 21001, "prompt": "..."}]}
```

`tab` is `soul-cast` or `cinema-studio`, `code` the row (`CAST-01`, `S01`), `column` the sheet header, `panel` the asset panel (`face`, `front`, `plate`, ...) or `null`, `file` a file in `updraft/`, and `card`, `seed` and `prompt` the generation record. Without a manifest the seed writes the content and the asset records only. With one, it fills only empty cells, once, and never overwrites a take, prompt or edit a person made.

## Other files here

`cast_kael.png`, `set_observatory.png` and `shot_s01.mp4` are small procedural placeholders left over from the earlier fixtures. The backend upload tests and the motion-lab scripts under `research/motion_lab/` still read them; they are not model renders and are not part of Updraft.

## License

The Updraft content, and the media generated for it, are dedicated to the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Code elsewhere in the repository follows the repository license.
