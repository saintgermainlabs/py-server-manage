# Agent Implementation Plan: Hetzner Coolify Backup System

## 1. Mission

Build a reliable, host-level backup and disaster-recovery system for the Hetzner server running Coolify.

The system must:

- Back up Coolify configuration and recovery-critical secrets.
- Back up application files and persistent Docker data.
- Create database-consistent dumps.
- Store encrypted backups in a Hetzner Storage Box.
- Run automatically through `systemd`.
- Detect failures and send alerts.
- Support documented, tested restores.
- Be maintainable through the existing `py-server-manage` repository.

The backup system must run directly on the Ubuntu host, not as a Coolify application or ordinary Docker container. This prevents the backup system from depending on Coolify or Docker during an outage.

Use:

- BorgBackup
- borgmatic
- systemd services and timers
- database-native dump tools
- a dedicated Hetzner Storage Box sub-account
- independent health monitoring

---

## 2. Project location

Add the backup implementation to the existing project:

```text
py-server-manage/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── mise.toml
├── .gitignore
├── .env.example
├── src/
│   └── serverops/
│       ├── __init__.py
│       ├── cli.py
│       ├── backup/
│       │   ├── __init__.py
│       │   ├── cli.py
│       │   ├── config.py
│       │   ├── discovery.py
│       │   ├── inventory.py
│       │   ├── preflight.py
│       │   ├── databases.py
│       │   ├── volumes.py
│       │   ├── borg.py
│       │   ├── restore.py
│       │   └── models.py
│       ├── inventory/
│       │   ├── coolify.py
│       │   ├── docker.py
│       │   └── system.py
│       └── utils/
│           ├── command.py
│           ├── filesystem.py
│           ├── logging.py
│           └── secrets.py
├── config/
│   ├── serverops.example.yaml
│   ├── backup.example.yaml
│   └── borgmatic.example.yaml
├── deploy/
│   ├── systemd/
│   │   ├── server-backup.service
│   │   ├── server-backup.timer
│   │   ├── server-backup-check.service
│   │   ├── server-backup-check.timer
│   │   ├── server-backup-restore-test.service
│   │   └── server-backup-restore-test.timer
│   └── scripts/
│       ├── install-backup-system.sh
│       └── uninstall-backup-system.sh
├── docs/
│   ├── backup-plan.md
│   ├── backup-installation.md
│   ├── backup-operations.md
│   ├── backup-restore-runbook.md
│   └── backup-security.md
├── tests/
│   ├── unit/
│   └── integration/
└── data/
    ├── inventory/
    ├── reports/
    └── restore-tests/
```

The Python package must provide discovery, configuration generation, validation, reporting, and restore assistance.

BorgBackup and borgmatic remain responsible for performing the actual archive operations.

---

## 3. Mandatory backup sources

The following paths are mandatory:

```text
/data/coolify/
/srv/projects/
/opt/
/home/dom/projects/
/etc/
/usr/local/bin/
/usr/local/sbin/
/root/.ssh/
```

The implementation must explicitly protect these Coolify recovery items:

```text
/data/coolify/source/.env
/data/coolify/ssh/keys/
/data/coolify/source/docker-compose.custom.yml
```

The original Coolify `APP_KEY` is critical because encrypted values in the restored Coolify database may otherwise become unusable.

The Coolify SSH keys are also critical because Coolify needs them to reconnect to managed servers.

Do not assume that Git repositories are sufficient backups for `/srv/projects`, `/opt`, or `/home/dom/projects`. These paths may contain uncommitted work, deployment files, environment files, uploaded media, service configuration, local scripts, and generated but non-reproducible data.

---

## 4. Explicit exclusions

Do not back up runtime or reproducible system data unless specifically approved.

Default exclusions must include:

```text
/proc
/sys
/dev
/run
/tmp
/var/tmp
/var/cache
/var/lib/docker/overlay2
/var/lib/docker/image
```

Also exclude, after confirming they are reproducible:

- Docker build caches
- unused Docker images
- package caches
- dependency directories
- generated thumbnails
- temporary files
- excessive application logs
- the Borg local cache
- backup staging data after successful archival

Do not blindly archive all of `/var/lib/docker`.

Do not copy live database data directories as the primary database backup method.

---

## 5. Safety requirements

### 5.1 No destructive actions by default

Discovery and dry-run commands must be read-only.

The agent must not:

- delete Docker volumes
- stop the whole Docker service
- prune Docker resources
- delete Borg archives
- overwrite an existing Borg repository
- modify production database contents
- replace live files during restore testing
- restart production applications without an explicit need

### 5.2 Dry-run support

Every command that can alter state must support a dry-run or preview mode where practical.

```bash
serverops backup install --dry-run
serverops backup run --dry-run
serverops backup prune --dry-run
serverops backup restore --dry-run
```

### 5.3 Secrets

Never commit:

- Borg passphrases
- Storage Box private keys
- database passwords
- Coolify `APP_KEY`
- application environment files
- monitoring tokens

Recommended secret locations:

```text
/etc/server-backup/credentials.env
/root/.ssh/server-backup-storagebox
/etc/borgmatic/config.yaml
```

Required permissions:

```text
root:root
0600
```

The systemd service must use:

```ini
UMask=0077
```

### 5.4 Preserve metadata

Backups and restores must preserve ownership, groups, permissions, symbolic links, ACLs, extended attributes, and timestamps where supported.

### 5.5 Idempotency

Installation and configuration commands must be safe to run repeatedly.

An existing valid configuration must not be silently overwritten. Use a generated `.new` file, an interactive diff, an explicit `--force`, or a backup of the previous file.

---

## 6. Required CLI

Implement a unified CLI:

```bash
uv run serverops backup discover
uv run serverops backup inventory
uv run serverops backup validate-config
uv run serverops backup generate-config
uv run serverops backup install
uv run serverops backup preflight
uv run serverops backup run
uv run serverops backup check
uv run serverops backup list
uv run serverops backup restore
uv run serverops backup restore-test
uv run serverops backup status
uv run serverops backup report
```

### `backup discover`

Discover Coolify resources, containers, Compose projects, bind mounts, named volumes, databases, project directories, disk usage, mount boundaries, filesystems, existing backup tools, and existing Borg configuration.

Output both YAML and Markdown:

```text
data/inventory/backup-inventory.yaml
data/reports/backup-inventory.md
```

### `backup inventory`

Generate a machine-readable inventory containing:

- Coolify resource name and UUID
- project UUID
- container name
- Docker Compose project
- image and service type
- database engine and database names
- bind mounts and named volumes
- secrets locations
- proposed backup method
- proposed restore order
- acceptable downtime
- notes requiring manual review

### `backup validate-config`

Validate source paths, exclusions, Borg repository URL, Storage Box hostname, SSH key, credentials, staging path, retention, expected databases, monitoring, and systemd settings.

### `backup generate-config`

Generate configuration files into a staging directory first:

```text
borgmatic.yaml
credentials.env.example
server-backup.service
server-backup.timer
server-backup-check.service
server-backup-check.timer
```

### `backup preflight`

Check DNS resolution, SSH on port 23, Borg access, Docker responsiveness, database clients, free disk space, staging permissions, source paths, repository locks, previous status, and monitoring settings.

### `backup run`

Run the approved workflow:

1. Obtain a lock.
2. Run preflight checks.
3. Create a protected staging directory.
4. Generate database dumps.
5. Validate all expected dumps.
6. Generate inventory and system-state reports.
7. Run borgmatic.
8. Apply retention.
9. Run the configured lightweight check.
10. Emit a structured run report.
11. Notify success or failure.
12. Remove staging data only after success.

### `backup restore`

Support selective extraction into a temporary directory. Do not automatically overwrite production paths.

```bash
serverops backup restore \
  --archive ARCHIVE_NAME \
  --path /srv/projects/example \
  --destination /var/lib/server-backup/restore/example
```

### `backup restore-test`

Restore representative files, Coolify configuration, databases, and volumes into isolated temporary locations and produce a validation report.

### `backup status`

Show the last attempted and successful runs, archive details, timer status, repository checks, restore tests, Storage Box usage, staging free space, and systemd state.

---

## 7. Configuration model

Create a strongly validated YAML configuration, preferably using Pydantic.

```yaml
version: 1

server:
  name: hetzner-primary
  staging_directory: /var/lib/server-backup/staging
  restore_directory: /var/lib/server-backup/restore
  lock_file: /run/lock/server-backup.lock

repository:
  url: ssh://STORAGE_USER@STORAGE_HOST:23/./borg/server-primary
  ssh_key: /root/.ssh/server-backup-storagebox
  passphrase_environment_variable: BORG_PASSPHRASE

sources:
  mandatory:
    - /data/coolify
    - /srv/projects
    - /opt
    - /home/dom/projects
  host_configuration:
    - /etc
    - /usr/local/bin
    - /usr/local/sbin
    - /root/.ssh
  additional: []

exclusions:
  - /proc
  - /sys
  - /dev
  - /run
  - /tmp
  - /var/tmp
  - /var/cache
  - /var/lib/docker/overlay2
  - /var/lib/docker/image

databases: []

retention:
  keep_within: 48H
  keep_daily: 14
  keep_weekly: 8
  keep_monthly: 12
  keep_yearly: 3

checks:
  lightweight_every_run: true
  full_check_weekly: true

monitoring:
  enabled: false
  start_url_env: BACKUP_START_URL
  success_url_env: BACKUP_SUCCESS_URL
  failure_url_env: BACKUP_FAILURE_URL

scheduling:
  nightly_calendar: "*-*-* 03:00:00"
  randomized_delay_seconds: 1800
  persistent: true
```

Unknown or invalid keys should cause clear validation errors.

---

## 8. Database discovery and backup

Support initially:

- PostgreSQL
- MySQL
- MariaDB
- MongoDB
- Redis where Redis contains durable state

Use native tools:

```bash
pg_dump --format=custom
pg_dumpall --globals-only
mysqldump
mariadb-dump
mongodump --archive --gzip
```

Classify Redis as disposable cache or durable state. Do not back up disposable caches.

Every expected database dump must exist, be non-empty, have a successful exit code, and be recorded in the run manifest. A missing required dump must fail the full backup.

---

## 9. Docker volume classification

Classify every named volume:

### Database volume

Use a native database backup. Exclude live database data directories from ordinary backup unless explicitly justified.

### Static application data

Capture uploads, media, documents, and user files using a read-only mount or safe host-path backup.

### Actively written application data

Use an application quiesce hook, filesystem snapshot, brief pause of the affected container, or application-native export.

Do not stop the entire Docker engine.

---

## 10. System inventory report

Generate a system-state report on every full backup.

Include:

- hostname
- OS and kernel
- installed packages
- enabled services and timers
- Docker and Compose versions
- Coolify version where discoverable
- containers, networks, volumes, and bind mounts
- disks, filesystems, and free space
- firewall rules
- listening ports
- Tailscale status
- relevant DNS and routing information

Do not include secret values. Environment-variable names may be recorded, but values must be redacted.

---

## 11. Borg and borgmatic design

Use an encrypted Borg repository on a dedicated Hetzner Storage Box sub-account.

Expected repository form:

```text
ssh://uXXXXX-sub1@uXXXXX-sub1.your-storagebox.de:23/./borg/server-primary
```

Use SSH key authentication, the Storage Box hostname, port 23, encryption, compression, deduplication, pruning, and repository checks.

Recommended retention:

```yaml
keep_within: 48H
keep_daily: 14
keep_weekly: 8
keep_monthly: 12
keep_yearly: 3
```

Archive naming examples:

```text
hetzner-primary-full-2026-07-28T030000
hetzner-primary-databases-2026-07-28T060000
```

---

## 12. systemd design

Create:

```text
server-backup.service
server-backup.timer
server-backup-check.service
server-backup-check.timer
server-backup-restore-test.service
server-backup-restore-test.timer
```

The main service must run as root, use `UMask=0077`, load credentials from `/etc/server-backup/credentials.env`, prevent concurrent execution, log to journald, use controlled CPU and I/O priority, and fail when required database dumps fail.

The timer must use:

```ini
Persistent=true
RandomizedDelaySec=
```

Schedule:

- critical databases every six hours
- full backup nightly
- repository check weekly
- restore test monthly

---

## 13. Monitoring

Support a dead-man-switch endpoint such as Healthchecks.io.

Send:

- start when backup begins
- success only after archive creation, pruning, and checks succeed
- failure on fatal error

Record start time, finish time, duration, archive name, dump counts and sizes, Borg size statistics, prune results, checks, and errors.

Monitoring must not depend entirely on Coolify.

---

## 14. Structured run manifest

Every run must produce a machine-readable manifest:

```yaml
run_id: 20260728T030000Z
server: hetzner-primary
backup_type: full
started_at: 2026-07-28T03:00:00Z
finished_at: 2026-07-28T03:17:42Z
status: success

archive:
  name: hetzner-primary-full-2026-07-28T030000
  repository: storagebox

databases:
  expected: 4
  completed: 4
  failed: 0
  dumps: []

sources:
  included: []
  missing: []

checks:
  preflight: success
  borg_create: success
  prune: success
  repository_check: success

warnings: []
errors: []
```

Include manifests in the Borg archive.

---

## 15. Restore runbook

Full-server recovery order:

1. Provision a clean compatible Ubuntu server.
2. Patch and secure it.
3. Install Borg, borgmatic, Docker, and database clients.
4. Retrieve recovery credentials and the runbook from independent storage.
5. Connect to the Storage Box and list archives.
6. Verify the repository.
7. Restore selected host configuration.
8. Install a compatible Coolify version.
9. Restore the Coolify database, original `APP_KEY`, and SSH keys.
10. Restore `/srv/projects`, `/opt`, and `/home/dom/projects`.
11. Restore approved bind mounts and named volumes.
12. Recreate and import databases.
13. Start services in dependency order.
14. Validate permissions and application behaviour.
15. Update DNS, Cloudflare, Tailscale, or routing.
16. Keep the failed server isolated until recovery is verified.

Service order:

```text
database
→ queue/cache
→ backend
→ workers
→ frontend
→ reverse proxy
```

Always restore databases and files into temporary locations first.

---

## 16. Implementation phases

### Phase 1: Repository preparation

Create the package structure, dependencies, logging, typed configuration models, CLI groups, tests, and `.gitignore` rules.

**Acceptance:** `uv sync`, CLI loading, and tests succeed.

### Phase 2: Read-only discovery

Inspect Coolify, Docker, volumes, databases, mandatory paths, filesystems, and disk usage. Generate YAML and Markdown inventories.

**Acceptance:** Every persistent service has an identifier, storage location, backup method, restore method, and review status.

### Phase 3: Storage Box configuration

Create the dedicated sub-account and SSH key, validate port 23, initialise Borg, and test archive creation and extraction.

**Acceptance:** Encrypted non-interactive backup and restore works, and the sub-account is restricted.

### Phase 4: Database pipeline

Implement and validate native database dumps and isolated restore tests.

**Acceptance:** Every required database restores successfully and passes integrity checks.

### Phase 5: Files and Docker volumes

Add mandatory paths, approved mounts, safe volume capture, exclusions, and metadata-preserving restores.

**Acceptance:** Restore representative data from each mandatory source and one application volume.

### Phase 6: borgmatic integration

Generate borgmatic configuration, source and exclusion lists, retention, checks, naming, logs, and manifests.

**Acceptance:** A manual full backup succeeds and includes all required data.

### Phase 7: systemd automation

Create services, timers, locking, scheduling, credentials loading, resource limits, and failure handling.

**Acceptance:** An unattended run succeeds, missed runs survive reboot, and overlap is prevented.

### Phase 8: Monitoring

Add start, success, failure, capacity, and last-success monitoring.

**Acceptance:** Successful and simulated failed runs produce correct alerts.

### Phase 9: Restore testing

Implement file, database, Coolify, and volume restore tests.

**Acceptance:** Monthly isolated validation produces a report and cleans up safely.

### Phase 10: Disaster-recovery rehearsal

Restore Coolify and at least one complete application onto an isolated clean machine.

**Acceptance:** Recovery succeeds without relying on the failed server.

### Phase 11: Independent third copy

Replicate encrypted backup data to another provider or offline target.

**Acceptance:** Critical data can be restored without the original server or Storage Box.

---

## 17. Testing requirements

Add unit tests for:

- configuration validation
- command construction
- exclusions
- database and volume classification
- manifests
- secret redaction
- archive naming
- retention
- preflight handling

Add integration tests using temporary directories and disposable containers.

```bash
uv run pytest
uv run pytest -m integration
uv run ruff check .
uv run mypy src
```

---

## 18. Documentation requirements

Create:

```text
docs/backup-installation.md
docs/backup-operations.md
docs/backup-restore-runbook.md
docs/backup-security.md
```

Document installation, operation, restore procedures, security, credentials, monitoring, and disaster recovery.

---

## 19. Coding standards

Use Python 3.12+, `uv`, `pathlib`, type hints, Pydantic, structured logging, subprocess argument lists, explicit timeouts, custom exceptions, and small testable functions.

Avoid `shell=True`, hidden global state, secret logging, hard-coded container names, and hard-coded credentials.

All external command execution must capture output, exit code, and timeout while redacting secrets.

---

## 20. Agent workflow

For each phase:

1. Inspect the existing repository.
2. Reuse existing helpers.
3. State assumptions.
4. Make the smallest coherent change.
5. Add or update tests.
6. Run formatting, linting, typing, and tests.
7. Update documentation.
8. Summarise changed files.
9. Record validation commands.
10. Stop before production credentials or irreversible changes are required.

Never guess Storage Box details, credentials, database names, container names, monitoring endpoints, or acceptable downtime.

---

## 21. Definition of done

The project is complete only when:

- all persistent Coolify resources are inventoried
- mandatory paths are included
- database-native dumps work
- every required database passes a restore test
- encrypted Borg storage works
- the Storage Box sub-account is restricted
- systemd automation works
- retention and checks work
- alerts work
- file, database, volume, and Coolify restores work
- the runbook exists outside the server
- a clean-machine recovery rehearsal succeeds
- actual RPO and RTO are documented
- secrets are absent from Git
- all tests pass

---

## 22. First task for the agent

Begin with Phase 1 and Phase 2 only.

Do not install Borg, modify production systemd units, initialise the Storage Box repository, stop containers, or change live services yet.

The first implementation must:

1. inspect the existing `py-server-manage` repository;
2. create the backup package skeleton;
3. implement read-only discovery;
4. inventory Docker containers, mounts, volumes, and probable databases;
5. inspect `/data/coolify`, `/srv/projects`, `/opt`, and `/home/dom/projects`;
6. generate YAML and Markdown reports;
7. redact secrets;
8. add tests;
9. update the README;
10. report unresolved decisions before moving forward.

Expected command:

```bash
uv run serverops backup discover
```

Expected outputs:

```text
data/inventory/backup-inventory.yaml
data/reports/backup-inventory.md
data/inventory/system-state.yaml
data/reports/system-state.md
```
