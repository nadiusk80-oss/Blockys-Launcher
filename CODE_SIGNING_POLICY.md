# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io),
certificate by [SignPath Foundation](https://signpath.org).

This document describes how release binaries of Blockys are built, reviewed and
signed. It applies to every Windows executable published by this project.

## Team roles

| Role | Responsibilities | GitHub |
| --- | --- | --- |
| Committer / Author | Writes and commits code, submits and approves signing requests | `nadiusk80-oss` |
| Reviewer | Reviews pull requests and release changes | `nadiusk80-oss` |
| Approver | Manually approves each signing request in SignPath | `nadiusk80-oss` |

One person may hold several roles for a personal project, but every person
with commit, review or approval permissions must have multi-factor
authentication enabled on their GitHub account.

## What is signed

- `Blockys.exe` in the 64-bit build (`dist\Blockys`).
- `Blockys.exe` in the 32-bit build (`dist\Blockys32`).
- The combined installer `Blockys-Setup-<version>.exe`, which embeds the signed
  application builds.

The certificate is issued to SignPath Foundation, so Windows shows
**SignPath Foundation** as the publisher. The signing certificate is not
available to the maintainer and cannot be used outside the approved SignPath
policies.

## Build and signing requirements

- All signed binaries are built from the source code in this repository by the
  GitHub Actions workflow in `.github/workflows/build.yml`, on GitHub-hosted
  Windows runners. Locally built binaries are never signed.
- The x64 and x86 builds are produced by PyInstaller from `build.py` and
  `run.py`; the installer is produced by Inno Setup from
  `packaging/Blockys.iss`.
- The signing order guarantees full coverage: the application executables are
  signed first, the installer is then assembled from the signed builds and the
  installer is signed last.
- Each signing request is manually approved by an approver in SignPath before
  the certificate is applied. There is no automatic or bulk signing.
- No proprietary components, third-party binaries or prebuilt files are signed.
  The only external content inside the artifacts is Python itself and the
  Pillow dependency, installed from PyPI during the workflow.
- API tokens used by the workflow are stored as encrypted GitHub Actions
  secrets and are limited to the project's signing policy.

## Release process

1. Update `__version__` in `bloque/__init__.py`.
2. Push a tag `v<version>` (for example `v1.0.2`).
3. The workflow builds both architectures, signs them, assembles the combined
   installer from the signed builds, signs the installer, and attaches the
   result to the GitHub release.
4. An approver manually reviews the signing request in SignPath before signing
   completes.

## Verifying a release

On Windows, check the publisher of a downloaded file:

```powershell
Get-AuthenticodeSignature .\Blockys-Setup-1.0.2.exe | Format-List
```

The status must be `Valid` and the signer subject must contain
`SignPath Foundation`. Releases that fail this check do not come from this
project's build pipeline.

Only the GitHub release page of this repository is the official download
location. SHA-256 checksums are published next to each release asset.

## Workflow configuration

Signing is performed by `.github/workflows/build.yml` and runs only for `v*`
tag releases. Builds from branches, pull requests and forks are never signed,
even when the SignPath variables are configured. The following repository
variables and secret are required:

| Name | Type | Purpose |
| --- | --- | --- |
| `SIGNPATH_API_TOKEN` | Secret | API token of a SignPath user with submitter permissions |
| `SIGNPATH_ORGANIZATION_ID` | Variable | SignPath organization ID |
| `SIGNPATH_PROJECT_SLUG` | Variable | SignPath project slug |
| `SIGNPATH_SIGNING_POLICY_SLUG` | Variable | SignPath signing policy slug |
| `SIGNPATH_APP_CONFIG_SLUG` | Variable | Artifact configuration that signs `Blockys.exe` inside the application build |
| `SIGNPATH_INSTALLER_CONFIG_SLUG` | Variable | Artifact configuration that signs `Blockys-Setup-<version>.exe` |

The artifact configurations are maintained in SignPath and target only the
files listed under "What is signed". The workflow uploads the unsigned build as
a workflow artifact, waits for the manually approved signing request, and
replaces the build with the signed output before the installer is assembled.

## Related documents

- [Privacy policy](PRIVACY.md)
- [System changes and uninstallation](README.md#data-and-uninstall)
- [License (GNU GPL v3.0)](LICENSE)
