# Local Ryot update pipeline

Build and test Linux amd64 images on an Apple Silicon Mac using an isolated Docker builder. Transfer only validated artifacts to an existing SSH server. No new GitHub Actions builds or tests are required.

`automation/local-update.py --build --deploy --ssh-host YOUR_SSH_ALIAS` prepares the private media patch from `codex/kvh-39` against upstream `main`, runs clippy, GraphQL generation, all workspace type checks, frontend/docs builds, release compilation and the complete media test suite. Merge conflicts stop before compilation.

The build container receives public source and test-only configuration. It has a separate Docker-in-Docker daemon and cannot access the host Docker socket, SSH keys, home directory or production secrets. Persistent build caches are scoped to this pipeline.

The resulting versioned image, checksum manifest and source bundle are transferred over SSH. The server validates provenance and architecture, tests migrations and note isolation on a private database copy, creates and restores a fresh backup, installs the image, and checks health, owner access and catalog search. A failed installation restores the previous database and image. Failed recovery stops the application and preserves the backup.

Server scripts expect the existing installation at `/srv/homelab/ryot`. Owner authentication and provider credentials remain local. Notifications use the server's existing alert bot. Private deployment journals and snapshots stay on the server.

A daily Mac LaunchAgent should invoke the local runner while Docker Desktop is available. Enable scheduling only after the first full local build, tests and deployment pass. Local state is ignored by Git; recent candidates and the last validated and deployed artifacts are retained.
