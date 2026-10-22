"""Download small public checkpoints from their publishing organizations only.

Weights stay under this project and are loaded offline thereafter.
"""
from pathlib import Path
import sys
from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.doctor import safetensors_valid
MODELS = [
    ("IDEA-Research/grounding-dino-tiny", ROOT / "checkpoints" / "grounding-dino-tiny",
     ["config.json", "model.safetensors", "preprocessor_config.json", "tokenizer.json",
      "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "vocab.txt"]),
    ("facebook/sam-vit-base", ROOT / "checkpoints" / "sam-vit-base",
     ["config.json", "model.safetensors", "preprocessor_config.json"]),
]


def main():
    api = HfApi()
    for repo, target, patterns in MODELS:
        target.mkdir(parents=True, exist_ok=True)
        valid, reason = safetensors_valid(target / 'model.safetensors')
        if not valid and (target / 'model.safetensors').exists():
            print(f'Invalid local weight ({reason}), deleting truncated file for redownload.', flush=True)
            (target / 'model.safetensors').unlink()
        revision = api.model_info(repo).sha
        print(f"Downloading {repo}@{revision} to {target}", flush=True)
        snapshot_download(repo_id=repo, revision=revision, local_dir=str(target),
                          allow_patterns=patterns, max_workers=4)
        valid, reason = safetensors_valid(target / 'model.safetensors')
        if not valid: raise RuntimeError(f'Invalid/incomplete checkpoint {repo}: {reason}')
        print(f"Ready: {repo}", flush=True)


if __name__ == "__main__":
    main()
