# Olladex desktop packaging

The desktop shell starts the project-scoped FastAPI service and the production Next.js server on loopback only, then opens them in a hardened Electron window. Node integration is disabled, context isolation and sandboxing are enabled, external navigation is sent to the system browser, and application data is stored in the operating system's Olladex user-data directory.

Development launch:

```bash
./start-desktop.sh
```

Create a native installer for the current operating system:

```bash
npm --prefix desktop install
npm --prefix desktop run dist
```

The build prepares the standalone frontend and freezes the Python API with PyInstaller before Electron Builder creates AppImage/DEB, DMG or NSIS output. Build each target on its native operating system. Pushing a `v*` tag runs the cross-platform GitHub Actions release workflow.

For signed builds, configure `CSC_LINK` and `CSC_KEY_PASSWORD` as repository secrets. Apple notarization additionally uses `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD` and `APPLE_TEAM_ID`. The workflow remains usable without these secrets and produces unsigned installers.

For a Linux x64 bundle that does not require AppImage tooling:

```bash
npm --prefix desktop run portable:linux
```
