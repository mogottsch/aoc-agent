## Local Single-GPU Training

This directory contains one self-contained workflow for running AoC RL training on a single rented GPU.

- `configs/` contains the `trainer`, `orchestrator`, and `inference` configs.
- `scripts/` contains ordered setup, launch, and recovery helpers.

The intended Vast template for this workflow is `NVIDIA CUDA`.

### Usage

1. Copy `scripts/local.env.example` to `scripts/local.env`.
2. Fill in secrets and machine-specific values in `scripts/local.env`.
3. Edit `configs/*.template.toml` if you want to change training hyperparameters.
4. Run `scripts/10_bootstrap_node.sh`.
5. Run `scripts/20_write_rclone_config.sh`.
6. Run `scripts/30_preflight.sh`.
7. Run `scripts/40_start_single_gpu_tmux.sh`.
8. Attach manually with `tmux attach-session -t aoc-single-gpu` when you want to watch it live.

### Script Groups

- Ordered setup and launch:
  - `scripts/10_bootstrap_node.sh`
  - `scripts/15_generate_runtime_configs.sh`
  - `scripts/20_write_rclone_config.sh`
  - `scripts/30_preflight.sh`
  - `scripts/40_start_single_gpu_tmux.sh`
- Recovery and persistence:
  - `scripts/50_backup_to_nextcloud.sh`
  - `scripts/60_restore_from_nextcloud.sh`
- Internal helper:
  - `scripts/_common.sh`

The checked-in config files hold the training settings. The actual runnable configs in `generated/` only inject runtime values like the run output directory, inference port, and GPU memory utilization.
