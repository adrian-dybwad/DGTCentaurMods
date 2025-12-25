# Scripts

Build, development, and utility scripts for Universal-Chess.

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
| `vm-setup/` | VM setup for Mac development |
| `config/` | Build configuration |
| `releases/` | Built .deb artifacts (gitignored) |

## CI/CD

CI/CD is handled by GitHub Actions. See `.github/workflows/`:

- `test.yml` - Run tests on push/PR
- `build.yml` - Build .deb package
- `release.yml` - Create GitHub releases
- `nightly.yml` - Automated nightly builds
