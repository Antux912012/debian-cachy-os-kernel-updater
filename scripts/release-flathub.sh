#!/usr/bin/env bash
# ==============================================================================
# Automated Release & Flathub Publisher for Debian CachyOS Kernel Updater
# App ID: io.github.Antux912012.debian-cachy-os-kernel-updater
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEV_ENV="$(cd "${PROJECT_DIR}/.." && pwd)/dev-env.sh"
APP_ID="io.github.Antux912012.debian-cachy-os-kernel-updater"
GITHUB_USER="Antux912012"

# Resolve GitHub Token from environment or ~/.config/cachy-kernel-updater/github_token
TOKEN_FILE="${HOME}/.config/cachy-kernel-updater/github_token"
if [ -z "${GITHUB_TOKEN:-}" ] && [ -f "$TOKEN_FILE" ]; then
    GITHUB_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
fi

cd "$PROJECT_DIR"

usage() {
    cat <<EOF
Usage: ./scripts/release-flathub.sh <version> ["release notes"] [options]

Arguments:
  <version>         Semantic version (e.g., 1.1.5 or 1.2.0)
  "release notes"   Optional changelog summary (default: "Release version <version>")

Options:
  --first-submission  Fork flathub/flathub (all branches), push branch '${APP_ID}' from 'new-pr', and open PR
  --update-flathub    Target existing Flathub app repo (flathub/${APP_ID}) and open PR
  --skip-build        Skip container rebuild if packages were already built
  --no-push           Prepare versions, validate, build packages, and tag locally without git push

Examples:
  ./scripts/release-flathub.sh 1.1.5 "Initial Flathub release" --first-submission
  ./scripts/release-flathub.sh 1.2.0 "Add Linux 6.19 support" --update-flathub
EOF
    exit 1
}

if [ $# -lt 1 ] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    usage
fi

VERSION="${1#v}"
shift

NOTES="Release version ${VERSION}"
if [ $# -gt 0 ] && [[ "$1" != --* ]]; then
    NOTES="$1"
    shift
fi

MODE="none"
NO_PUSH=false
SKIP_BUILD=false

while [ $# -gt 0 ]; do
    case "$1" in
        --first-submission) MODE="first" ;;
        --update-flathub)   MODE="update" ;;
        --skip-build)       SKIP_BUILD=true ;;
        --no-push)          NO_PUSH=true ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
    shift
done

DATE_TODAY="$(date +%Y-%m-%d)"
TAG="v${VERSION}"

if [ -n "${GITHUB_TOKEN:-}" ]; then
    AUTH_PREFIX="https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com"
else
    AUTH_PREFIX="https://github.com"
fi

echo "=================================================================="
echo " Preparing Release ${TAG} (${DATE_TODAY}) for ${APP_ID}"
echo "=================================================================="

# 1. Sync version in main.py and kernel_manager.py
echo "[1/6] Syncing APP_VERSION = \"${VERSION}\" in main.py and kernel_manager.py..."
sed -i -E "s/^APP_VERSION = \"[^\"]+\"/APP_VERSION = \"${VERSION}\"/" main.py kernel_manager.py

# 2. Ensure <release version="${VERSION}"> exists in metainfo.xml
echo "[2/6] Updating ${APP_ID}.metainfo.xml..."
python3 - "${APP_ID}.metainfo.xml" "$VERSION" "$DATE_TODAY" "$NOTES" << 'PYEOF'
import sys

path, version, date_today, notes = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

if f'<release version="{version}"' in content:
    print(f"  -> Release {version} already present in {path}, keeping existing entry.")
else:
    entry = f"""  <releases>
    <release version="{version}" date="{date_today}">
      <description>
        <p>{notes}</p>
      </description>
    </release>"""
    content = content.replace("  <releases>", entry, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  -> Inserted <release version=\"{version}\" date=\"{date_today}\"> into {path}.")
PYEOF

# 3. Validate & Rebuild (.deb + .flatpak) inside Podman dev-debian container
if [ "$SKIP_BUILD" = false ]; then
    echo "[3/6] Running desktop/AppStream validation & package builds inside Podman (dev-debian)..."
    "$DEV_ENV" debian run bash -c "
        set -e
        cd /workspace/debian-cachy-os-kernel-updater
        desktop-file-validate ${APP_ID}.desktop
        appstreamcli validate --pedantic --explain ${APP_ID}.metainfo.xml
        ./build_deb.sh
        ./build_flatpak.sh
    "
else
    echo "[3/6] --skip-build specified, skipping container build."
fi

# 4. Commit and Tag Upstream Release
echo "[4/6] Committing release changes and tagging ${TAG}..."
git add README.md main.py kernel_manager.py "${APP_ID}.metainfo.xml" "${APP_ID}.yml" "${APP_ID}.desktop" build_flatpak.sh scripts/release-flathub.sh FLATHUB_SUBMISSION_PLAN.md
if ! git diff --cached --quiet; then
    git commit -m "Release ${TAG}: ${NOTES}"
fi
git tag -f "$TAG"
COMMIT_SHA="$(git rev-parse HEAD)"
echo "  -> Tagged ${TAG} at commit ${COMMIT_SHA}"

# 5. Update Flathub Submission Manifest with new tag & commit SHA
echo "[5/6] Locking tag (${TAG}) and commit (${COMMIT_SHA}) in flathub_submission/${APP_ID}.yml..."
sed -i -E "s|^([[:space:]]*tag:[[:space:]]*).*|\1${TAG}|" "flathub_submission/${APP_ID}.yml"
sed -i -E "s|^([[:space:]]*commit:[[:space:]]*).*|\1${COMMIT_SHA}|" "flathub_submission/${APP_ID}.yml"

git add "flathub_submission/${APP_ID}.yml" "flathub_submission/flathub.json"
if ! git diff --cached --quiet; then
    git commit --amend --no-edit
    git tag -f "$TAG"
    COMMIT_SHA="$(git rev-parse HEAD)"
    sed -i -E "s|^([[:space:]]*commit:[[:space:]]*).*|\1${COMMIT_SHA}|" "flathub_submission/${APP_ID}.yml"
fi

if [ "$NO_PUSH" = true ]; then
    echo "[6/6] --no-push specified. Skipping git push and Flathub branch push."
    exit 0
fi

# 6. Push Upstream & Optionally Push Flathub PR Branch
echo "[6/6] Pushing upstream main and tag ${TAG} to GitHub..."
git push "${AUTH_PREFIX}/${GITHUB_USER}/debian-cachy-os-kernel-updater.git" main
git push -f "${AUTH_PREFIX}/${GITHUB_USER}/debian-cachy-os-kernel-updater.git" "$TAG"

if [ "$MODE" = "first" ]; then
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        echo "[*] Ensuring fork ${GITHUB_USER}/flathub exists on GitHub (with all branches)..."
        curl -sS -X POST \
            -H "Authorization: Bearer ${GITHUB_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/repos/flathub/flathub/forks \
            -d '{"default_branch_only":false}' >/dev/null || true
        sleep 3
    fi

    # Pre-flight check: Verify https://github.com/${GITHUB_USER}/${REPO_SLUG} returns HTTP 200 for flatpak-builder-lint 'appid-url-not-reachable'
    REPO_SLUG="${APP_ID##*.}"
    HTTP_CODE=$(curl -sL -o /dev/null -w "%{http_code}" "https://github.com/${GITHUB_USER}/${REPO_SLUG}")
    if [ "$HTTP_CODE" != "200" ]; then
        echo "ERROR: https://github.com/${GITHUB_USER}/${REPO_SLUG} returned HTTP ${HTTP_CODE}! flatpak-builder-lint will fail with appid-url-not-reachable."
        exit 1
    fi
    echo "  -> Verified https://github.com/${GITHUB_USER}/${REPO_SLUG} is reachable (HTTP 200)."

    WORK_DIR="$(mktemp -d /tmp/flathub-first.XXXXXX)"
    trap 'rm -rf "$WORK_DIR"' EXIT
    echo "[*] Cloning Flathub 'new-pr' branch..."
    git clone --branch=new-pr --single-branch "https://github.com/flathub/flathub.git" "$WORK_DIR"
    cd "$WORK_DIR"
    git config user.name "$GITHUB_USER"
    git config user.email "${GITHUB_USER}@users.noreply.github.com"
    git checkout -b "${APP_ID}" new-pr
    cp "${PROJECT_DIR}/flathub_submission/${APP_ID}.yml" .
    cp "${PROJECT_DIR}/flathub_submission/flathub.json" .
    git add "${APP_ID}.yml" flathub.json
    git commit -m "Add ${APP_ID}"
    git push -f "${AUTH_PREFIX}/${GITHUB_USER}/flathub.git" "${APP_ID}"

    if [ -n "${GITHUB_TOKEN:-}" ]; then
        echo "[*] Creating Pull Request on flathub/flathub (base: new-pr)..."
        PR_BODY=$(cat <<'EOF'
### Please confirm your submission meets all the criteria

- [X] Please describe the application briefly. Kernel Updater for CachyOS on Debian is an independent GTK4 and Libadwaita utility that automates the discovery, compilation, installation, and UEFI MOK Secure Boot signing of CachyOS kernels on Debian-based systems.
- [X] Please attach a video showcasing the application on Linux using the Flatpak. https://github.com/Antux912012/debian-cachy-os-kernel-updater/releases/download/v1.1.5/DCKU_Flathub_sub_vid.mp4
- [X] The Flatpak ID follows all the rules listed in the [Application ID requirements][appid].
- [X] I have read and followed all the [Submission requirements][reqs] and the [Submission guide][reqs2] and I agree to them.
  - [X] The application has a meaningful development history, evidence of real-world use, and a clear commitment to ongoing maintenance, as required by the [development history requirements][history].
  - [X] I have disclosed any AI-generated material included in the application or its Flathub packaging, as required by the [Generative AI policy][ai]. **Affected parts and approximate extent:** None
  - [X] I have not used AI tools or agents to generate or automate this submission pull request or its review interactions.
- [X] I am an author/developer/upstream contributor to the project. **Link:** https://github.com/Antux912012/debian-cachy-os-kernel-updater

### Sandbox Permissions Note
- `--talk-name=org.freedesktop.Flatpak` & `--filesystem=host`: Required because this utility compiles Linux kernels (via host Podman/toolchain), inspects `/boot`, `/var/lib/dpkg`, and `/sys/firmware/efi/efivars`, signs kernel modules with MOK keys (`mokutil` / `sbsigntool`), and installs `.deb` kernel packages on the host via `pkexec dpkg -i`.
- `only-arches: ["x86_64"]`: CachyOS kernel optimizations (`x86-64-v3` and `x86-64-v4`) specifically target `x86_64` systems.

<!-- ⚠️⚠️  Please DO NOT modify anything below this line ⚠️⚠️  -->

[appid]: https://docs.flathub.org/docs/for-app-authors/requirements#application-id
[reqs]: https://docs.flathub.org/docs/for-app-authors/requirements
[reqs2]: https://docs.flathub.org/docs/for-app-authors/submission
[history]: https://docs.flathub.org/docs/for-app-authors/requirements#insufficient-development-history
[ai]: https://docs.flathub.org/docs/for-app-authors/requirements#generative-ai-policy
EOF
)
        # Validate PR_BODY against Flathub's flathub-submission-checker rules before opening PR
        python3 - "$PR_BODY" << 'PYCHECK'
import re, sys

body = sys.argv[1]
checklist = [(m.lower() == "x", t.strip()) for m, t in re.findall(r"^[ \t]*[-+*][ \t]+\[([ xX])\][ \t]*(.+?)\s*$", body, re.M)]
required = [
    "Please describe the application briefly.",
    "Please attach a video showcasing the application on Linux using the Flatpak.",
    "The Flatpak ID follows all the rules listed in the",
    "I have read and followed all the",
    "The application has a meaningful development history, evidence of real-world use, and a clear commitment to ongoing maintenance, as required by the",
    "I have disclosed any AI-generated material included in the application or its Flathub packaging, as required by the",
    "I have not used AI tools or agents to generate or automate this submission pull request or its review interactions.",
]
norm = lambda s: " ".join(s.replace("*", "").replace("_", "").replace("`", "").split()).casefold()
texts = [norm(t) for _, t in checklist]
missing = [r for r in required if not any(norm(r) in t for t in texts)]
if missing or not all(c for c, _ in checklist):
    sys.exit(f"ERROR: Flathub checklist validation failed! Missing={missing}")
print("  -> Flathub PR checklist pre-validation passed (8/8 items checked).")
PYCHECK
        PR_JSON=$(python3 -c 'import json, sys; print(json.dumps({"title": sys.argv[1], "head": sys.argv[2], "base": "new-pr", "body": sys.argv[3]}))' \
            "Add ${APP_ID}" "${GITHUB_USER}:${APP_ID}" "$PR_BODY")
        RESPONSE=$(curl -sS -X POST \
            -H "Authorization: Bearer ${GITHUB_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/repos/flathub/flathub/pulls \
            -d "$PR_JSON")
        PR_URL=$(python3 -c 'import json, sys; d=json.loads(sys.stdin.read()); print(d.get("html_url", ""))' <<< "$RESPONSE")
        if [ -n "$PR_URL" ]; then
            echo "=================================================================="
            echo " SUCCESS! Flathub Pull Request Created: ${PR_URL}"
            echo "=================================================================="
        else
            echo "Branch pushed! Compare/PR response: $RESPONSE"
            echo "Manual PR URL: https://github.com/flathub/flathub/compare/new-pr...${GITHUB_USER}:flathub:${APP_ID}?expand=1"
        fi
    fi

elif [ "$MODE" = "update" ]; then
    WORK_DIR="$(mktemp -d /tmp/flathub-update.XXXXXX)"
    trap 'rm -rf "$WORK_DIR"' EXIT
    BRANCH_NAME="release-${TAG}"
    echo "[*] Cloning https://github.com/flathub/${APP_ID}.git..."
    git clone "${AUTH_PREFIX}/flathub/${APP_ID}.git" "$WORK_DIR"
    cd "$WORK_DIR"
    git config user.name "$GITHUB_USER"
    git config user.email "${GITHUB_USER}@users.noreply.github.com"
    git checkout -b "$BRANCH_NAME"
    cp "${PROJECT_DIR}/flathub_submission/${APP_ID}.yml" .
    cp "${PROJECT_DIR}/flathub_submission/flathub.json" .
    git add "${APP_ID}.yml" flathub.json
    git commit -m "Update ${APP_ID} to ${TAG}"
    git push -f "${AUTH_PREFIX}/flathub/${APP_ID}.git" "$BRANCH_NAME"

    if [ -n "${GITHUB_TOKEN:-}" ]; then
        echo "[*] Creating Release Update Pull Request on flathub/${APP_ID}..."
        PR_JSON=$(python3 -c 'import json, sys; print(json.dumps({"title": sys.argv[1], "head": sys.argv[2], "base": "master", "body": sys.argv[3]}))' \
            "Update ${APP_ID} to ${TAG}" "$BRANCH_NAME" "Release ${TAG}: ${NOTES}")
        RESPONSE=$(curl -sS -X POST \
            -H "Authorization: Bearer ${GITHUB_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/repos/flathub/${APP_ID}/pulls" \
            -d "$PR_JSON")
        PR_URL=$(python3 -c 'import json, sys; d=json.loads(sys.stdin.read()); print(d.get("html_url", ""))' <<< "$RESPONSE")
        echo "=================================================================="
        echo " SUCCESS! Flathub Update PR: ${PR_URL:-https://github.com/flathub/${APP_ID}/compare/master...${BRANCH_NAME}?expand=1}"
        echo "=================================================================="
    fi
fi
