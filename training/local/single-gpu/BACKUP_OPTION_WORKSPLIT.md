## Backup Option Worksplit

### Goal

Pick the leanest reliable way to get training state off a disposable Vast.ai GPU node.

### Shared Requirements

- Backup target is the homeserver.
- Public SSH exposure is not allowed.
- Training state must survive loss of the GPU node.
- We only need to preserve:
  - `checkpoints/`
  - `outputs/`
  - `logs/`
  - the exact config files used for the run
- We want the setup to stay simple enough to bootstrap on fresh rented machines.

### Track A: Nextcloud WebDAV

Investigate using Nextcloud over HTTPS, most likely via `rclone`.

Questions to answer:

1. What is the minimal client setup on the Vast.ai node?
2. How do we authenticate safely?
3. How do we push a run directory periodically?
4. How do we avoid relying on partially uploaded checkpoints?
5. How awkward is restore onto a fresh node?
6. Are there obvious performance or consistency concerns for large checkpoint directories?

Deliverable:

- A minimal bootstrap procedure.
- Example sync command(s).
- Example restore command(s).
- Clear caveats.
- A judgment: viable or not viable.

#### Track A Findings

Status: viable

Test result: validated end-to-end against the user's real Nextcloud instance

What was tested:

- WebDAV endpoint reachability
- authentication with a Nextcloud app password
- remote directory listing
- upload of a local test file
- restore of that file back to local disk
- byte-for-byte comparison of original and restored file

Tested endpoint shape:

- `https://<host>/remote.php/dav/files/<username>/`

Observed behavior:

- `rclone` worked correctly with `vendor = nextcloud`
- the tested backup path did not require SSH, VPN, or shell access to the homeserver
- the route is operationally simple enough to use on a disposable GPU node

Why it is viable:

- Uses HTTPS to the existing Nextcloud endpoint.
- Does not require shell access to the homeserver.
- `rclone` has first-class WebDAV support and a dedicated `nextcloud` vendor mode.
- Nextcloud supports modified times and hashes through this integration.

Why it is not perfect:

- It is a worse fit than `rsync` for a directory tree with lots of changing files.
- Uploading lots of small files can be slow.
- We should treat the most recently synced checkpoint as potentially incomplete after interruption.

#### Track A Minimal Bootstrap On Vast.ai

Dependencies needed for Track A only:

1. `rclone`
2. a Nextcloud account
3. a Nextcloud app password
4. outbound internet access from the GPU node

Bootstrap steps:

1. Install `rclone` on the node.
2. Create a Nextcloud app password instead of using the main account password.
3. Configure an `rclone` WebDAV remote with:
   - `type = webdav`
   - `vendor = nextcloud`
   - URL in the form `https://<host>/remote.php/dav/files/<username>/`
4. Create one remote directory per training run.
5. Periodically sync the local run directory to that remote directory.

#### Track A Suggested Layout

Local run directory on Vast.ai:

- `runs/<run-name>/train.toml`
- `runs/<run-name>/orch.toml`
- `runs/<run-name>/infer.toml`
- `runs/<run-name>/checkpoints/`
- `runs/<run-name>/outputs/`
- `runs/<run-name>/logs/`

Remote directory in Nextcloud:

- `prime-runs/<run-name>/...`

#### Track A Example Setup

Interactive setup:

```bash
rclone config
```

Key values:

- storage type: `webdav`
- vendor: `nextcloud`
- URL: `https://<host>/remote.php/dav/files/<username>/`
- username: `<username>`
- password: Nextcloud app password

Sanity check:

```bash
rclone lsd nextcloud:
```

#### Track A Example Sync

One-shot sync of a run directory:

```bash
rclone sync runs/<run-name> nextcloud:prime-runs/<run-name>
```

Safer periodic copy, which avoids deleting remote files during active work:

```bash
rclone copy runs/<run-name> nextcloud:prime-runs/<run-name>
```

Likely useful flags:

```bash
rclone copy runs/<run-name> nextcloud:prime-runs/<run-name> \
  --transfers 2 \
  --checkers 4 \
  --webdav-nextcloud-chunk-size 64M
```

For first implementation, `copy` is safer than `sync`.

#### Track A Example Restore

Restore a previous run onto a fresh node:

```bash
rclone copy nextcloud:prime-runs/<run-name> runs/<run-name>
```

Then resume training from the last known good checkpoint step.

#### Track A Operational Advice

- Use a Nextcloud app password, not the main password.
- Sync every few minutes, not every few seconds.
- Keep checkpoint intervals coarse enough that each checkpoint is meaningful.
- Assume the newest remote checkpoint may be incomplete if the node died mid-upload.
- Resume from the latest checkpoint that looks complete.

#### Track A Caveats

- Slower than `rsync` for lots of small files.
- Less natural than SSH tooling for incremental filesystem backup.
- Needs a little care around partially uploaded checkpoint directories.
- Large checkpoint uploads may benefit from tuning Nextcloud chunk size on both client and server.
- During testing, cleanup of the remote test directory failed on the first attempt because the temporary `rclone` config was deleted too early. This was a local test harness mistake, not a Nextcloud or `rclone` failure.

#### Track A Judgment

This is a realistic option if the priority is minimizing trust and access on the homeserver side.

It is probably the leaner security model.

It is probably not the technically strongest file-sync model.

### Track B: WireGuard + rsync

Investigate joining the Vast.ai node to the existing WireGuard VPN and syncing to the homeserver with `rsync` over SSH.

Questions to answer:

1. What is the minimal client setup on the Vast.ai node?
2. What credentials need to be placed on the node?
3. Can access be narrowed to backup-only behavior?
4. What does the sync command look like?
5. What does restore onto a fresh node look like?
6. What is the real setup burden compared with WebDAV?

Deliverable:

- A minimal bootstrap procedure.
- Example sync command(s).
- Example restore command(s).
- Clear caveats.
- A judgment: viable or not viable.

#### Track B Findings

Status: viable

Test result: validated for general file transfer through the Hetzner proxy to the homeserver

What was tested:

- SSH reachability from Hetzner to the homeserver over `wg0`
- `rsync` push from an ephemeral container on Hetzner to the homeserver
- `rsync` restore from the homeserver back into that container
- byte-for-byte comparison of original and restored test files

Observed behavior:

- The transfer path `container -> Hetzner -> homeserver` worked correctly.
- The homeserver SSH port was reachable from Hetzner on `10.0.0.2:22`.
- `rsync` performed a successful round trip for a fake run directory with config, checkpoint, output, and log files.

Why it is viable:

- `rsync` over SSH is a strong fit for checkpoint trees and repeated incremental syncs.
- The homeserver stays off the public internet.
- The Hetzner box already has the necessary VPN path to the homeserver.
- Access can be narrowed to a dedicated backup user with forced-command `rrsync`.

Why it is not perfect:

- Bootstrap is heavier than WebDAV because the client needs VPN plus SSH material.
- A true Vast-like client test was not completed in this pass. The validated path used an ephemeral container on Hetzner rather than a separate `wg1` client.
- The backup-only SSH restriction is straightforward in principle, but the exact user setup still needs one clean production pass.

#### Track B Minimal Bootstrap On Vast.ai

1. Install `wireguard-tools`, `openssh-client`, and `rsync` on the node.
2. Place a generated `wg1` client config on the node.
3. Bring up the VPN and confirm the homeserver is reachable at `10.0.0.2:22`.
4. Place a dedicated SSH key for the backup-only user on the node.
5. Periodically `rsync` the run directory to the homeserver.

#### Track B Suggested Layout

Local run directory on Vast.ai:

- `runs/<run-name>/train.toml`
- `runs/<run-name>/orch.toml`
- `runs/<run-name>/infer.toml`
- `runs/<run-name>/checkpoints/`
- `runs/<run-name>/outputs/`
- `runs/<run-name>/logs/`

Remote directory on the homeserver:

- `/srv/backups/prime-runs/<run-name>/...`

#### Track B Example Sync

One-shot sync of a run directory:

```bash
rsync -az runs/<run-name>/ backup@10.0.0.2:/srv/backups/prime-runs/<run-name>/
```

Safer periodic sync during active training:

```bash
rsync -az --partial --inplace runs/<run-name>/ backup@10.0.0.2:/srv/backups/prime-runs/<run-name>/
```

#### Track B Example Restore

Restore a previous run onto a fresh node:

```bash
rsync -az backup@10.0.0.2:/srv/backups/prime-runs/<run-name>/ runs/<run-name>/
```

#### Track B Caveats

- More moving parts than Nextcloud WebDAV.
- Requires distributing both VPN and SSH credentials to the rented node.
- A dedicated backup-only SSH user should be enforced before production use.
- If `--inplace` is used, the newest remote checkpoint should still be treated carefully after interruption.

#### Track B Judgment

This is a realistic option and the transfer model is technically stronger than WebDAV.

It is probably the stronger backup path if we are comfortable with the extra bootstrap work.

It is not the lighter operational path.

### Evaluation Criteria

Judge both tracks on:

1. Setup complexity on a fresh Vast.ai machine.
2. Security exposure.
3. Reliability for periodic checkpoint backup.
4. Ease of restore after node loss.
5. Likely performance with large files.
6. Ongoing operational annoyance.

### Decision Rule

Pick the option that is simplest while still being trustworthy for checkpoint persistence.

### Current Bias

- WebDAV feels operationally lighter.
- `rsync` feels technically stronger.
- We need to validate whether WebDAV is good enough before optimizing for elegance.
