#!/usr/bin/env python3
"""
bfmd_to_osl_v2.py

Convert BFMD to OSL-JSON with integrated video handling:
1. Direct yt-dlp download of full-match videos (no external script)
2. Extract 16-frame clips for each of 11,301 shots
3. Organize output:
   - bfmd_fullmatch_osl.json (references full_match/*.mp4)
   - bfmd_clips_osl.json (references trimmed_clips/*.mp4)
   - full_match/ folder with full-match videos (~500 MB each)
   - trimmed_clips/ folder with 16-frame shot clips (~10-50 MB total)

LICENSE / SCOPE
---------------
- BFMD: non-commercial academic use only, NO redistribution.
- Videos belong to BWF TV (not included in HF uploads; only JSONs + clips).
- This script handles everything locally; always use --private on HF.

REQUIREMENTS
  pip install yt-dlp opencv-python  (ffmpeg on PATH for video trimming)

USAGE
  python bfmd_to_osl_v2.py --data-root BFMD_data --out-dir bfmd_osl \\
    --download-videos --trim-clips
  # Downloads full matches, extracts 11,301 16-frame clips, writes JSONs
  # Then upload (annotations + videos only, never redistributed):
  export HF_TOKEN=...
  python bfmd_to_osl_v2.py --data-root BFMD_data --out-dir bfmd_osl \\
    --repo-id your-org/bfmd-osl --private
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import date
from glob import glob
from pathlib import Path

FPS = 30.0
VIDEO_W, VIDEO_H = 1280, 720

SHOT_TYPES = [
    "serve", "flick_serve", "clear", "drop", "smash", "drive",
    "net_shot", "net_kill", "lift", "push", "press", "block",
]
DOUBLES_HIT_LABELS = ["hit", "bounce", "net_hit"]

# ============================================================================
# VIDEO DOWNLOAD (direct yt-dlp)
# ============================================================================
def download_full_match_video(url: str, out_path: Path, match_name: str):
    """Download a single YouTube video via yt-dlp to out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        print(f"  [skip] {out_path.name} already exists")
        return
    
    fmt = "bv*[height<=720]+ba/b[height<=720]"  # ≤720p merged
    cmd = [
        "yt-dlp",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", str(out_path),
        url,
    ]
    print(f"  [dl] {match_name}...")
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"    ERROR: {e.stderr.decode('utf-8', errors='replace')}")
        raise


def download_videos(data_root: Path, out_dir: Path, match_filter: str = None):
    """Download all BFMD full-match videos from YouTube to videos/ or videos_doubles/."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        sys.exit("Please `pip install yt-dlp` (and have ffmpeg on PATH) to download videos.")
    
    # Load video list with type info
    csv_path = data_root / "Badminton_video_list.csv"
    if not csv_path.is_file():
        sys.exit(f"No Badminton_video_list.csv in {data_root}")
    
    matches = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            matches.append(row)
    
    if match_filter:
        matches = [r for r in matches if match_filter.lower() in r.get("match_name", "").lower()]
        print(f"[dl] filtered to {len(matches)} matches")
    
    print(f"[dl] downloading {len(matches)} videos...")
    for row in matches:
        name = row.get("match_name", "").strip()
        url = row.get("youtube_url", "").strip()
        match_type = row.get("type", "").strip().lower()
        
        if not name or not url:
            continue
        
        # Save singles to videos/, doubles to videos_doubles/
        if match_type == "doubles":
            out_path = out_dir / "videos_doubles" / f"{name}.mp4"
        else:
            out_path = out_dir / "videos" / f"{name}.mp4"
        
        download_full_match_video(url, out_path, name)
    print(f"[dl] done")


# ============================================================================
# VIDEO TRIMMING (16-frame clips via ffmpeg)
# ============================================================================
def trim_clip(video_path: Path, start_frame: int, num_frames: int, out_path: Path, fps: float):
    """Trim a clip from start_frame for num_frames, save to out_path via ffmpeg."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start_sec = start_frame / fps
    duration_sec = num_frames / fps
    
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start_sec:.3f}",
        "-i", str(video_path),
        "-t", f"{duration_sec:.3f}",
        "-c", "copy",  # stream copy (fast, no re-encode)
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def trim_clips_for_matches(data_root: Path, out_dir: Path, matches: list):
    """Extract 16-frame clips for all 11,301 singles shots to trimmed_videos/."""
    full_match_singles_dir = out_dir / "videos"
    full_match_doubles_dir = out_dir / "videos_doubles"
    clips_dir = out_dir / "trimmed_videos"
    
    print(f"[trim] extracting clips to {clips_dir}...")
    total_clips = sum(len(m["hits"]) for m in matches if not m["doubles"])
    done = 0
    
    for m in matches:
        if m["doubles"]:
            continue
        name = m["name"]
        video_path = full_match_singles_dir / f"{name}.mp4"
        if not video_path.exists():
            print(f"  SKIP {name}: video not found at {video_path}")
            continue
        
        for i, h in enumerate(m["hits"]):
            fr = h["frame"]
            clip_id = f"{name}_shot_{i:04d}"
            out_path = clips_dir / f"{clip_id}.mp4"
            
            try:
                trim_clip(video_path, fr - 3, 16, out_path, FPS)
                done += 1
                if done % 500 == 0:
                    print(f"  [{done}/{total_clips}] {clip_id}")
            except Exception as e:
                print(f"    ERROR trimming {clip_id}: {e}")
                raise
    
    print(f"[trim] done ({done} clips)")


# ============================================================================
# LOADERS (reuse from v1)
# ============================================================================
def match_names(data_root: Path, subdir: str, suffix: str = ".json"):
    out = {}
    for p in sorted((data_root / "annotations" / subdir).glob(f"*{suffix}")):
        if p.name.endswith(".bak"):
            continue
        stem = p.name[: -len(suffix)] if suffix and p.name.endswith(suffix) else p.stem
        out[stem] = p
    return out


def load_metadata(path: Path) -> dict:
    obj = json.load(open(path))
    return obj[0] if isinstance(obj, list) else obj


def load_hits_singles(path: Path):
    return json.load(open(path)).get("hits", [])


def load_segments_from_timeline(path: Path):
    obj = json.load(open(path))
    anns = obj.get("annotations", [])
    results = anns[0].get("result", []) if anns else []
    segments, points = [], []
    for r in results:
        v = r.get("value", {})
        labels = v.get("timelinelabels", [])
        label = labels[0] if labels else None
        if label is None:
            continue
        for rg in v.get("ranges", []):
            start, end = int(rg["start"]), int(rg.get("end", rg["start"]))
            if end > start:
                segments.append({"label": label, "start_frame": start, "end_frame": end})
            else:
                points.append({"label": label, "frame": start})
    return segments, points


def load_doubles_hits(path: Path):
    _, points = load_segments_from_timeline(path)
    return [p for p in points if p["label"] in DOUBLES_HIT_LABELS]


def load_captions(data_root: Path):
    return {}


# ============================================================================
# OSL BUILDERS (updated paths)
# ============================================================================
def frame_to_ms(frame: int, fps: float = FPS) -> int:
    return int(round(frame / fps * 1000.0))


def build_fullmatch_localization(matches: list, captions: dict, split: str) -> dict:
    """One OSL sample per match; hits as localization events. Videos in videos/ or videos_doubles/."""
    data = []
    for m in matches:
        name, doubles = m["name"], m["doubles"]
        events = []
        for h in m["hits"]:
            fr = h["frame"]
            ev = {
                "head": "shot_type",
                "label": h.get("shot_type", "hit"),
                "frame": fr,
                "position_ms": frame_to_ms(fr),
            }
            for k in ("side", "player", "game", "rally"):
                if k in h:
                    ev[k] = h[k]
            events.append(ev)

        dense = []
        for fr, text in captions.get(name, {}).items():
            dense.append({"position_ms": frame_to_ms(int(fr)), "lang": "en", "text": text})

        # Use videos_doubles/ for doubles, videos/ for singles
        video_folder = "videos_doubles" if doubles else "videos"
        sample = {
            "id": name,
            "inputs": [{
                "type": "video",
                "path": f"{video_folder}/{name}.mp4",
                "fps": FPS,
            }],
            "metadata": {
                "match_name": name,
                "match_type": "doubles" if doubles else "singles",
                "resolution": {"width": VIDEO_W, "height": VIDEO_H},
                "segments": m["segments"],
                "match_meta": m.get("meta", {}),
            },
            "events": events,
        }
        if dense:
            sample["dense_captions"] = dense
        data.append(sample)

    return {
        "version": "2.0",
        "date": str(date.today()),
        "task": "action_spotting",
        "dataset_name": f"bfmd-fullmatch-{split}",
        "description": "BFMD full-match badminton hit events (shot-type localization). "
                       "Videos in videos/ (singles) and videos_doubles/ (doubles) folders.",
        "modalities": ["video"],
        "metadata": {"sport": "badminton", "split": split, "source": "BFMD",
                     "fps": FPS, "license": "non-commercial, no redistribution"},
        "labels": {
            "shot_type": {"type": "single_label", "labels": SHOT_TYPES + DOUBLES_HIT_LABELS},
        },
        "data": data,
    }


def build_clip_classification(matches: list, captions: dict, split: str) -> dict:
    """One OSL sample per shot (singles only); 16-frame clips in trimmed_videos/."""
    PRE, POST = 3, 12
    data = []
    for m in matches:
        if m["doubles"]:
            continue
        name = m["name"]
        cap_map = captions.get(name, {})
        for i, h in enumerate(m["hits"]):
            fr = h["frame"]
            clip_id = f"{name}_shot_{i:04d}"
            sample = {
                "id": clip_id,
                "inputs": [{
                    "type": "video",
                    "path": f"trimmed_videos/{clip_id}.mp4",
                    "fps": FPS,
                }],
                "labels": {"action": {"label": h["shot_type"]}},
                "metadata": {
                    "match_name": name,
                    "hit_frame": fr,
                    "window_start_frame": fr - PRE,
                    "window_end_frame": fr + POST,
                    "position_ms": frame_to_ms(fr),
                    "side": h.get("side"),
                    "player": h.get("player"),
                    "game": h.get("game"),
                    "rally": h.get("rally"),
                },
            }
            if str(fr) in cap_map:
                sample["captions"] = [{"lang": "en", "text": cap_map[str(fr)]}]
            data.append(sample)

    return {
        "version": "2.0",
        "date": str(date.today()),
        "task": "action_classification",
        "dataset_name": f"bfmd-clips-{split}",
        "description": "BFMD per-shot 16-frame clips (3 pre / 12 post hit frame) with shot type. "
                       "Videos in trimmed_videos/ folder.",
        "modalities": ["video"],
        "metadata": {"sport": "badminton", "split": split, "source": "BFMD",
                     "fps": FPS, "license": "non-commercial, no redistribution"},
        "labels": {"action": {"type": "single_label", "labels": SHOT_TYPES}},
        "data": data,
    }


# ============================================================================
# COLLECT MATCHES
# ============================================================================
_TOURNAMENT_BY_MATCH = {}


def _load_tournament_map(data_root: Path):
    idx = data_root / "match_index.csv"
    if not idx.is_file():
        return
    with open(idx, newline="") as f:
        for row in csv.DictReader(f):
            name = row.get("match_name")
            tour = (row.get("tournament") or "").strip()
            if name and tour:
                _TOURNAMENT_BY_MATCH[name] = tour


def _slim_meta(meta: dict) -> dict:
    if not meta:
        return {}
    keep = {}
    for k in ("player1_name", "player2_name", "game1_top_player",
              "match_score", "match_winner"):
        if k in meta:
            keep[k] = meta[k]
    games = meta.get("games", {})
    if isinstance(games, dict):
        keep["games"] = {}
        for gk, gv in games.items():
            if isinstance(gv, dict):
                keep["games"][gk] = {
                    "start_label": gv.get("start_label"),
                    "end_label": gv.get("end_label"),
                    "rallies": gv.get("rallies", []),
                    "game_winner": gv.get("game_winner"),
                    "final_score": gv.get("final_score"),
                }
    return keep


def collect_matches(data_root: Path):
    _load_tournament_map(data_root)
    meta_files = match_names(data_root, "metadata")
    hit_files = match_names(data_root, "hit_inferred")
    seg_files = match_names(data_root, "shot_type")
    dbl_files = match_names(data_root, "hits_doubles")

    matches = []

    # --- singles ---
    for name, hpath in hit_files.items():
        hits = load_hits_singles(hpath)
        segments = []
        if name in seg_files:
            segments, _ = load_segments_from_timeline(seg_files[name])
        meta = load_metadata(meta_files[name]) if name in meta_files else {}
        matches.append({
            "name": name, "doubles": False,
            "hits": hits, "segments": segments,
            "meta": _slim_meta(meta),
        })

    # --- doubles ---
    for name, dpath in dbl_files.items():
        segments, _ = load_segments_from_timeline(dpath)
        hits = load_doubles_hits(dpath)
        hits = [{"frame": h["frame"], "shot_type": h["label"]} for h in hits]
        meta = load_metadata(meta_files[name]) if name in meta_files else {}
        matches.append({
            "name": name, "doubles": True,
            "hits": hits, "segments": segments,
            "meta": _slim_meta(meta),
        })

    return matches


# ============================================================================
# HUGGING FACE UPLOAD
# ============================================================================
def upload_to_hf(local_dir: Path, repo_id: str, private: bool = True):
    from huggingface_hub import HfApi, create_repo
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("Set HF_TOKEN in your environment (a write token).")
    create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True, token=token)
    HfApi().upload_folder(
        folder_path=str(local_dir),
        repo_id=repo_id,
        repo_type="dataset",
        token=token,
        ignore_patterns=[],  # upload everything: JSONs + clips (no full matches)
        commit_message="Add BFMD OSL-JSON + 16-frame trimmed clips",
    )
    print(f"[hf] uploaded to https://huggingface.co/datasets/{repo_id} (private={private})")


# ============================================================================
# MAIN
# ============================================================================
def main():
    ap = argparse.ArgumentParser(
        description="Convert BFMD to OSL-JSON with integrated video download and trimming.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--data-root", type=Path, required=True,
                    help="Path to BFMD_data/ directory.")
    ap.add_argument("--out-dir", type=Path, default=Path("bfmd_osl"),
                    help="Output directory for JSONs and video folders.")
    ap.add_argument("--download-videos", action="store_true",
                    help="Download full-match videos from YouTube.")
    ap.add_argument("--video-match", default=None,
                    help="Only download matches whose name contains this substring.")
    ap.add_argument("--trim-clips", action="store_true",
                    help="Extract 16-frame clips for all 11,301 shots.")
    ap.add_argument("--view", choices=["localization", "clips", "both"], default="both",
                    help="Which OSL JSON to generate.")
    ap.add_argument("--repo-id", default=None,
                    help="HuggingFace repo ID to upload to (e.g., your-org/bfmd-osl).")
    ap.add_argument("--private", action="store_true",
                    help="Upload as private (recommended for BFMD; default unless --public).")
    ap.add_argument("--public", action="store_true",
                    help="Upload as public (NOT recommended; violates BFMD redistribution terms).")
    args = ap.parse_args()

    if not (args.data_root / "annotations").is_dir():
        sys.exit(f"{args.data_root}/annotations not found.")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # --- Download ---
    if args.download_videos:
        download_videos(args.data_root, args.out_dir, match_filter=args.video_match)

    # --- Convert ---
    matches = collect_matches(args.data_root)
    captions = load_captions(args.data_root)
    n_singles = sum(1 for m in matches if not m["doubles"])
    n_doubles = sum(1 for m in matches if m["doubles"])
    n_hits = sum(len(m["hits"]) for m in matches)
    print(f"[collect] {len(matches)} matches ({n_singles} singles, {n_doubles} doubles), "
          f"{n_hits} hits, captions for {len(captions)} matches")

    # --- Trim clips ---
    if args.trim_clips:
        trim_clips_for_matches(args.data_root, args.out_dir, matches)

    # --- Write JSONs ---
    written = []
    if args.view in ("localization", "both"):
        p = args.out_dir / "bfmd_fullmatch_osl.json"
        p.write_text(json.dumps(build_fullmatch_localization(matches, captions, "all"), indent=2))
        written.append(p)
    if args.view in ("clips", "both"):
        p = args.out_dir / "bfmd_clips_osl.json"
        p.write_text(json.dumps(build_clip_classification(matches, captions, "all"), indent=2))
        written.append(p)

    (args.out_dir / "NOTICE.txt").write_text(
        "BFMD OSL-JSON conversion.\n"
        "Non-commercial academic use only. No redistribution.\n"
        "Full-match videos belong to BWF TV and are stored locally only.\n"
        "Trimmed clips (~16-frame shots) are OSL-JSON training data.\n"
        "Original dataset: https://ning-d.github.io/BFMD-Dataset/\n"
    )
    print(f"[convert] wrote {len(written)} JSON files to {args.out_dir}")

    # --- Upload ---
    if args.repo_id:
        if args.public and not args.private:
            print("[hf] WARNING: uploading as public. BFMD terms require non-commercial use.")
        private = not args.public if args.public or not args.private else args.private
        upload_to_hf(args.out_dir, args.repo_id, private=private)
    else:
        print("[hf] no --repo-id given; skipping upload.")


if __name__ == "__main__":
    main()