# Automated deployment

CarnoKit has two intentionally separate update paths:

- **Project code:** a successful `Validate` run for a push to `main` starts
  `Deploy tooling to VPS`. It deploys that exact commit and restarts only
  `asa-bot` and `asa-watchdog`.
- **ARK server builds:** the bot's update checker warns players, saves every
  reachable world, and restarts the four game containers. GitHub Actions never
  performs this operation.

## GitHub setup

Create a `production` environment and add these environment secrets:

| Secret | Value |
| --- | --- |
| `VPS_HOST` | VPS hostname or IP address |
| `VPS_USER` | Restricted deployment SSH user (currently `root`) |
| `VPS_SSH_PRIVATE_KEY` | Private half of a dedicated deployment key |
| `VPS_SSH_HOST_KEY` | Exact `known_hosts` line for the VPS |

Generate a dedicated key rather than storing an account password in GitHub.
Add its public half to the deployment user's `~/.ssh/authorized_keys`. Obtain
and verify the server's host-key fingerprint through an independent trusted
channel before saving the full host-key line as `VPS_SSH_HOST_KEY`.

The `production` environment may optionally require reviewer approval. The
workflow has read-only repository permissions and serializes deployments so
two pushes cannot deploy concurrently.

## Safety behavior

`deploy/deploy-commit.sh`:

1. takes a host-level `flock` deployment lock;
2. refuses tracked local changes;
3. requires the exact current commit at `origin/main`;
4. updates dependencies only when `requirements.txt` changes;
5. compiles Python before restarting services;
6. updates the three tooling systemd units;
7. disables the superseded five-minute pull timer;
8. verifies the bot and watchdog are active; and
9. rolls back code and units if deployment or health checks fail.

It never runs `git clean`, never touches ignored runtime data or secrets, and
never invokes Docker Compose or the ARK shutdown/restart scripts.

Use the workflow's manual dispatch to retry the current `main` commit. An
optional SHA must be a full 40-character SHA and must still equal current
`origin/main`; arbitrary or stale commits are rejected.
