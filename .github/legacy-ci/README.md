# Legacy CI System (Deprecated)

**This Docker-based CI system is deprecated.**

The project now uses GitHub Actions for CI/CD. See `.github/workflows/` for:

- `test.yml` - Run tests on push/PR
- `build.yml` - Build .deb package
- `release.yml` - Create GitHub releases
- `nightly.yml` - Automated nightly builds

## Migration Notes

The old system used a Docker container running cron to poll for version changes.
The new system uses GitHub Actions which:

- Triggers automatically on push/tag
- Runs tests across multiple Python versions
- Builds packages in clean environments
- Creates releases with checksums
- Provides nightly builds for testing

## Files in this directory

These files are preserved for reference only:

- `Dockerfile` - Old Docker image definition
- `release-dgtcm.sh` - Old release script
- `cronjob/` - Cron configuration
- `templates/` - Release note templates

The templates may be useful for customizing GitHub release notes in the future.
