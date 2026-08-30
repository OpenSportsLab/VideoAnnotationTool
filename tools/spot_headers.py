#!/usr/bin/env python
"""Spot headers from H5 skeletal tracking.

    python spot_headers.py /data/FIFA_data
    python spot_headers.py /data/FIFA_data/128083
    python spot_headers.py /data/FIFA_data --config OpenSportsLab/skeleton-header-max-recall

The path is either a game directory holding live_joints.h5 and live_ball.h5,
or a directory of such game directories. --config takes a local config or a
HuggingFace repo id holding a config.yaml.
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if (REPO_ROOT / "opensportslib" / "__init__.py").exists():
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CONFIG = "opensportslib/configs/localization/h5_header_skeleton.yaml"
from opensportslib.apis import LocalizationModel

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help="A game directory, or a directory of game directories.")
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help="Config path or HuggingFace repo id.")
    parser.add_argument("--output", default="headers.json")
    args = parser.parse_args()

    os.environ.setdefault("RUN_ID", "headers")
    

    # if args.path is a directory, find all h5 games within it and create the maniufest. Otherwise, assume it's a manifest file.
    if os.path.isdir(args.path):
        from opensportslib.datasets.utils.h5_tracking import find_h5_games, write_h5_manifest
        games = find_h5_games(args.path)
        if not games:
            sys.exit(f"No tracking files found in or under {args.path}")

        manifest = write_h5_manifest(output.parent / ".header_work" / "manifest.json", games)
    else:
        manifest = Path(args.path).resolve()
        if not manifest.exists():
            sys.exit(f"Manifest file {manifest} does not exist")

    output = Path(args.output).resolve()

    api = LocalizationModel(config=args.config)
    # print(f"[spot] {len(games)} game(s), {api.config.MODEL.components.rule.source.name}", flush=True)

    predictions = api.infer(test_set=str(manifest), use_wandb=False)
    api.save_predictions(str(output), predictions)

    for game in predictions["data"]:
        print(f"  {game['id']}: {len(game['events'])} headers")
    total = sum(len(game["events"]) for game in predictions["data"])
    print(f"[spot] {total} headers -> {output}", flush=True)


if __name__ == "__main__":
    main()
