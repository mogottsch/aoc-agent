## Local Single-GPU Training

This directory contains one self-contained workflow for running AoC RL training on a single rented GPU.

- `configs/` contains the `trainer`, `orchestrator`, and `inference` configs.
- `scripts/` contains bootstrap, launch, backup, and restore helpers.
- `SINGLE_GPU_TRAINING_NOTES.md` is the working note for this setup.
- `BACKUP_OPTION_WORKSPLIT.md` records the backup-path investigation.

The intended Vast template for this workflow is `NVIDIA CUDA`.

### Usage

1. Copy `scripts/local.env.example` to `scripts/local.env`.
2. Fill in secrets and machine-specific values in `scripts/local.env`.
3. Edit `configs/*.template.toml` if you want to change training hyperparameters.
4. Run `scripts/bootstrap_node.sh`.
5. Run `scripts/write_rclone_config.sh`.
6. Run `scripts/preflight.sh`.
7. Run `scripts/start_single_gpu_tmux.sh`.

The checked-in config files hold the training settings. The actual runnable configs in `generated/` only inject runtime values like the run output directory, inference port, and GPU memory utilization.
