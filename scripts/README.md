# Scripts

Build, development, and utility scripts for Universal-Chess.

## Quick Reference

| Task | Command |
|------|---------|
| **Create a release** | `./release.sh` |
| **Build .deb package** | `./build.sh` |
| **Bump version** | `./bump-version.sh patch` |
| **Check for updates** | `./check-updates.sh` |
| **Run the app** | `./run.sh` |

## Release & Versioning

| Script | Purpose |
|--------|---------|
| `release.sh` | Interactive release workflow (see [docs/releasing.md](../docs/releasing.md)) |
| `bump-version.sh` | Bump version in DEBIAN/control |
| `check-updates.sh` | Check GitHub for new releases |

**Creating a release:**
```bash
./release.sh           # Interactive mode
./release.sh patch     # Quick patch release (2.0.0 -> 2.0.1)
./release.sh minor     # Quick minor release (2.0.0 -> 2.1.0)
./release.sh 2.1.0     # Explicit version
```

See **[docs/releasing.md](../docs/releasing.md)** for complete documentation.

## Build Scripts

| Script | Purpose |
|--------|---------|
| `build.sh` | Build the .deb package |
| `rebuild.sh` | Full rebuild cycle: purge, build, install, restart |
| `setup.sh` | Initial device setup (configs, resources) |
| `reset.sh` | Reset device to clean state |

## Running

| Script | Purpose |
|--------|---------|
| `run.sh` | Run the main application |
| `run-web.sh` | Run the web UI |
| `test-web.sh` | Quick web UI smoke test |

## How to use build.sh

- Interactive build: `./build.sh`
- Headless build: `./build.sh full`
- Clean only: `./build.sh clean`

Resulting `.deb` files are in `scripts/releases/`.

## Reset the Pi before building/installing

Run the reset script on the target Pi to purge any previous installation and revert system changes. Requires root.

```bash
# Interactive (prompts before removing /opt if non-project files exist)
sudo bash scripts/reset.sh

# Non-interactive (auto-approve)
sudo bash scripts/reset.sh --yes

# Dry-run (print actions without executing)
sudo bash scripts/reset.sh --dry-run
```

## Web smoke test

Quick check that the web UI is up and serving expected endpoints.

```bash
scripts/test-web.sh
scripts/test-web.sh http://host[:port]
BASE_URL=http://host[:port] scripts/test-web.sh
```

## Rebuild on Pi (one command)

Non-interactive end-to-end rebuild and redeploy on the device:

```bash
cd ~/Universal-Chess/scripts
chmod +x rebuild.sh  # first time only
./rebuild.sh               # builds from UniversalChess branch
./rebuild.sh my-feature    # builds from branch/tag my-feature
```

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `engines/` | Engine build scripts (build-maia.sh, etc.) |
| `vm-setup/` | VM development environment setup |
| `config/` | Build configuration |
| `releases/` | Built .deb artifacts (gitignored) |

## Debugging & Development

| Script | Purpose |
|--------|---------|
| `probe.sh` | Probe board hardware |
| `board_probe.sh` | Low-level board diagnostics |
| `proxy.sh` | Serial proxy for debugging |
| `monitor_centaur_serial.py` | Monitor serial communication |

## Documentation

| Document | Description |
|----------|-------------|
| [docs/releasing.md](../docs/releasing.md) | Complete release process guide |
| [docs/architecture.md](../docs/architecture.md) | System architecture overview |
| [vm-setup/README.md](vm-setup/README.md) | VM development setup |
| [build-info.md](build-info.md) | Build system details |

## CI/CD

CI/CD is handled by GitHub Actions. See `.github/workflows/`:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `test.yml` | Push, PR | Run tests (Python 3.9, 3.11, 3.13) |
| `release.yml` | Tag `v*` | Build package, create GitHub release |
| `nightly.yml` | Daily, push to main | Nightly pre-release builds |
| `build.yml` | Manual | Build package without release |
