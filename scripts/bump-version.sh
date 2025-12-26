#!/usr/bin/env bash
# This file is part of the Universal-Chess project
# https://github.com/adrian-dybwad/Universal-Chess
#
# Bump the version number in DEBIAN/control and optionally create a git tag.
#
# Usage:
#   ./bump-version.sh patch    # 1.3.3 -> 1.3.4
#   ./bump-version.sh minor    # 1.3.3 -> 1.4.0
#   ./bump-version.sh major    # 1.3.3 -> 2.0.0
#   ./bump-version.sh 1.4.0    # Set explicit version
#   ./bump-version.sh --tag    # Also create and push git tag

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONTROL_FILE="${REPO_ROOT}/packaging/deb-root/DEBIAN/control"

# Parse current version
get_current_version() {
    grep -m1 '^Version:' "${CONTROL_FILE}" | cut -d' ' -f2
}

# Increment version based on type
bump_version() {
    local current="$1"
    local type="$2"
    
    IFS='.' read -r major minor patch <<< "${current}"
    
    case "${type}" in
        major)
            echo "$((major + 1)).0.0"
            ;;
        minor)
            echo "${major}.$((minor + 1)).0"
            ;;
        patch)
            echo "${major}.${minor}.$((patch + 1))"
            ;;
        *)
            # Assume explicit version
            echo "${type}"
            ;;
    esac
}

# Update version in control file
set_version() {
    local new_version="$1"
    
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s/^Version: .*/Version: ${new_version}/" "${CONTROL_FILE}"
    else
        sed -i "s/^Version: .*/Version: ${new_version}/" "${CONTROL_FILE}"
    fi
}

# Create git tag
create_tag() {
    local version="$1"
    local tag="v${version}"
    
    echo "Creating git tag: ${tag}"
    git add "${CONTROL_FILE}"
    git commit -m "Bump version to ${version}"
    git tag -a "${tag}" -m "Release ${version}"
    
    echo ""
    echo "Tag created. To push:"
    echo "  git push && git push --tags"
}

# Main
main() {
    local create_tag_flag=false
    local bump_type=""
    
    # Parse arguments
    for arg in "$@"; do
        case "${arg}" in
            --tag|-t)
                create_tag_flag=true
                ;;
            *)
                bump_type="${arg}"
                ;;
        esac
    done
    
    if [[ -z "${bump_type}" ]]; then
        echo "Usage: $0 [patch|minor|major|X.Y.Z] [--tag]"
        echo ""
        echo "Current version: $(get_current_version)"
        exit 1
    fi
    
    local current_version
    current_version="$(get_current_version)"
    
    local new_version
    new_version="$(bump_version "${current_version}" "${bump_type}")"
    
    echo "Bumping version: ${current_version} -> ${new_version}"
    set_version "${new_version}"
    echo "Updated ${CONTROL_FILE}"
    
    if [[ "${create_tag_flag}" == true ]]; then
        create_tag "${new_version}"
    else
        echo ""
        echo "To also create a git tag, run:"
        echo "  $0 ${bump_type} --tag"
        echo ""
        echo "Or manually:"
        echo "  git add ${CONTROL_FILE}"
        echo "  git commit -m 'Bump version to ${new_version}'"
        echo "  git tag -a v${new_version} -m 'Release ${new_version}'"
        echo "  git push && git push --tags"
    fi
}

main "$@"

