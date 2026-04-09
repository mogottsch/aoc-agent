## Single-GPU Prime RL Notes

### Goal

Run AoC RL training on a single rented GPU instead of Prime hosted RL, because hosted RL is too expensive for iterative experimentation.

### Current Understanding

- We want to use open-source `prime-rl`, not hosted `prime rl` training.
- The local codebase has a unified `rl.toml` launcher path, but the documented single-GPU setup still uses separate `train.toml`, `orch.toml`, and `infer.toml` files with manual process startup.
- For now, we are following the documented manual single-GPU path because it explicitly supports trainer and inference sharing one physical GPU.
- The local config is still separate from the hosted configs in `configs/prime/*.toml`.
- It is not completely independent from this repo, because it still needs to point at the AoC environment and model we use.

### AoC Environment

- For local `prime-rl`, the easiest path is to use the local AoC environment package from this repo:
  - `environments/aoc_prime_env`
- That package is already installable as `aoc-prime-env`.
- The local environment exposes `load_environment(split, max_examples, max_turns, command_timeout_seconds, ...)`, which maps cleanly onto local `prime-rl` env args.
- Hosted training used the published hub environment like `mgottsch/aoc-prime-env@0.1.2`.
- For local training, we should prefer installing the local package directly unless we later decide to test installing the published hub version instead.

### Expected Vast.ai Node Setup

- Rent one GPU machine with the `NVIDIA CUDA` template and access it over SSH.
- Install basic tools:
  - `git`
  - `uv`
  - `tmux`
- Configure `rclone` for Nextcloud backup.
- Clone this repo.
- Install Python dependencies with the RL group.
- Install the local AoC environment package.
- Configure hosted Weights & Biases.
- Configure Hugging Face access for model downloads.
- Configure backup sync for checkpoints and outputs.

### Automation

- Reproducible node bootstrap now lives in `training/local/single-gpu/scripts/bootstrap_node.sh`.
- Nextcloud `rclone` config generation lives in `training/local/single-gpu/scripts/write_rclone_config.sh`.
- Config generation for runtime values lives in `training/local/single-gpu/scripts/generate_configs.sh`.
- Single-GPU tmux startup lives in `training/local/single-gpu/scripts/start_single_gpu_tmux.sh`.
- Backup and restore helpers live in:
  - `training/local/single-gpu/scripts/backup_to_nextcloud.sh`
  - `training/local/single-gpu/scripts/restore_from_nextcloud.sh`
- Required environment variables are templated in `training/local/single-gpu/scripts/local.env.example`.
- Training hyperparameters live in the checked-in config templates under `training/local/single-gpu/configs/`.

### Model Weights

- `prime-rl` should download model weights through Hugging Face tooling on first use.
- We do not plan to manually copy model weights onto the machine.
- We will likely want an HF token to avoid download friction and rate limits.
- The Hugging Face cache should live on disk with enough space.

### W&B

- We plan to use hosted Weights & Biases.
- Self-hosting W&B on the homeserver is not planned.

### Persistence

- Persistence is critical.
- Local `prime-rl` can checkpoint training state, but checkpointing must be enabled explicitly.
- We should assume the rented GPU machine is disposable.
- Training state must be copied off the machine regularly.
- The minimum state to preserve is:
  - `checkpoints/`
  - `outputs/`
  - `logs/`
  - the exact config files used for the run

### Chosen Backup Path

- We chose Nextcloud WebDAV over WireGuard + `rsync`.
- Reason: it is the leaner setup and does not require shell access to the homeserver.
- The tested client path is `rclone` with the `webdav` backend and `nextcloud` vendor mode.
- This was tested successfully end-to-end against the user's real Nextcloud instance.
- Minimal extra dependency on the GPU node for backup is just `rclone`.
- We should still assume the newest uploaded checkpoint may be incomplete if a node dies mid-upload.
- For active runs, prefer periodic `rclone copy` over `rclone sync`.

### Open Questions

- Is the local AoC environment definitely the best path, or is installing the published environment package leaner for local `prime-rl`?
- What GPU class on Vast.ai are we targeting?
- What checkpoint cadence should we use?
- What sync cadence should we use?

### Likely Next Steps

1. Copy `training/local/single-gpu/scripts/local.env.example` to `training/local/single-gpu/scripts/local.env` and fill in secrets.
2. Bring up a real single-GPU node and run `training/local/single-gpu/scripts/bootstrap_node.sh`.
3. Run `training/local/single-gpu/scripts/write_rclone_config.sh`.
4. Start the training stack with `training/local/single-gpu/scripts/start_single_gpu_tmux.sh`.
