# Build tool
This will build a deb package out of the cloned branch. It means that not all the time the tool will get you a working build of the software. This tool is meant to be used mainly by the developers. Usually, if try to build the `master` branch, you should get a working build though.

## How to use the tool?
- To start a new build process just run: `./build.sh`. This runs as interactive mode.
- To start a headless build process run: `./build.sh full`. This will perform all operations without interaction.
- Although performed at the start, cleaning can be done by `./build.sh clean`

Resulting build file will be in `build/releases/`.

## Reset the Pi before building/installing
Run the reset script on the target Pi to purge any previous DGTCentaurMods installation and revert its system changes. Requires root.

- Interactive (prompts before removing entire `/opt` if non-DGTCM files exist):
  - `sudo bash build/reset.sh`
- Non-interactive (auto-approve `/opt` removal if needed):
  - `sudo bash build/reset.sh --yes`
- Dry-run (print actions without executing):
  - `sudo bash build/reset.sh --dry-run`

## Web smoke test

- Quick check that the Centaur web UI is up and serving expected endpoints.
- Defaults to `http://127.0.0.1` and falls back to port `5000` if port `80` is unavailable.

Usage:

- `build/test-web.sh`
- `build/test-web.sh http://host[:port]`
- `BASE_URL=http://host[:port] build/test-web.sh`

The script performs:

- Preflight checks for required install paths, venv `python`, Flask import, systemd units, and nginx site config (best-effort).
- Endpoint checks for `/`, `/fen`, and `/engines` with retries.

## Rebuild on Centaur (one command)

- Non-interactive end-to-end rebuild and redeploy on the Centaur device. Purges existing package, updates the repo, builds the `.deb`, installs it, and restarts services.

Usage:

```bash
cd ~/DGTCentaurMods/build
chmod +x rebuild.sh  # first time only
./rebuild.sh               # builds from AsyncController
./rebuild.sh my-feature    # builds from branch/tag my-feature
```

Notes:

- Runs on the Centaur device (Debian/apt environment).
- Service restarts are case-insensitive; explicitly attempts `DGTCentaurMods` and `centaurmods-web`, then restarts all `dgt*` services if present.
- Leaves a copy of the built `.deb` in `/tmp/`.
