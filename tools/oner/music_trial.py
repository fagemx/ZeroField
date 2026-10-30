"""ACE-Step 1.5 (turbo) text-to-music through ComfyUI's core nodes, with the official template's settings.

python -X utf8 music_trial.py <job.json> <out_dir>
job.json: {"jobs": [{"name", "tags", "lyrics", "seed", "seconds", "bpm", "keyscale", "timesignature"}]}
Each job saves <out_dir>/<name>.flac. Settings follow Comfy-Org's audio_ace_step_1_5_split template: euler / simple,
8 steps, cfg 1, AuraFlow shift 3, the 1.7B planner on (generate_audio_codes), cfg_scale 2, temperature 0.85, top_p 0.9.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import klein_trial as kt


def graph(job):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "acestep_v1.5_turbo.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "qwen_0.6b_ace15.safetensors", "clip_name2": "qwen_1.7b_ace15.safetensors",
                                                         "type": "ace", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ace_1.5_vae.safetensors"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "5": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["2", 0], "tags": job["tags"], "lyrics": job.get("lyrics", "[Instrumental]"), "seed": job["seed"],
            "bpm": job.get("bpm", 72), "duration": job["seconds"], "timesignature": str(job.get("timesignature", 4)), "language": "en",
            "keyscale": job.get("keyscale", "D major"), "generate_audio_codes": True, "cfg_scale": 2.0, "temperature": 0.85,
            "top_p": 0.9, "top_k": 0, "min_p": 0.0}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": job["seconds"], "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": job["seed"], "steps": 8, "cfg": 1.0, "sampler_name": "euler",
                                                   "scheduler": "simple", "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
                                                   "denoise": 1.0}},
        "9": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveAudio", "inputs": {"audio": ["9", 0], "filename_prefix": "zf_music_" + job["name"]}},
    }


def run(job, out_dir):
    pid = json.loads(kt.call("/prompt", json.dumps({"prompt": graph(job), "client_id": "zfmusic"}).encode(),
                             {"Content-Type": "application/json"}))["prompt_id"]
    start = time.time()
    while True:
        hist = json.loads(kt.call(f"/history/{pid}"))
        if pid in hist:
            entry = hist[pid]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(entry["status"])[:2000])
            files = [f for out in entry["outputs"].values() for f in out.get("audio", [])]
            if files:
                f = files[0]
                path = os.path.join(out_dir, job["name"] + os.path.splitext(f["filename"])[1])
                open(path, "wb").write(kt.call(f"/view?filename={f['filename']}&subfolder={f['subfolder']}&type={f['type']}"))
                return path, time.time() - start
        time.sleep(2)


if __name__ == "__main__":
    jobs, out_dir = json.load(open(sys.argv[1], encoding="utf-8"))["jobs"], sys.argv[2]
    for job in jobs:
        path, secs = run(job, out_dir)
        print(f"{job['name']}: {secs:.0f}s -> {path}")
