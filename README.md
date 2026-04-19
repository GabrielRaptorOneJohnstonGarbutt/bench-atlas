# Fly Tying Materials Tracker

Multi-page mobile-friendly web app for tracking fly tying materials, storage spots, rebuy items, flies, recipe notes, bug reports, and photos. The app has a side-menu layout and optional Google sign-in so each signed-in user can access their own list across devices.

## What changed

- Reworked the interface into a page-based layout with a side menu.
- Added separate pages for dashboard, inventory, rebuy list, material entry, storage spots, and account settings.
- Added a dedicated flies and recipes page with linked materials and pattern photos.
- Added a bug report page with a saved report list backed by SQLite.
- Added Google account login support with user-scoped data in SQLite.
- Added cookie-backed sessions so a signed-in user sees their own inventory on any device using the same server.
- Kept guest mode available when Google sign-in is not configured.

## Run it

Use the bundled Python runtime:

```powershell
C:\Users\25gea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe server.py
```

Then open:

```text
http://127.0.0.1:8000
```

## Google sign-in setup

To enable Google login, set these environment variables before starting the server:

```powershell
$env:GOOGLE_CLIENT_ID="your-google-oauth-client-id.apps.googleusercontent.com"
$env:SESSION_SECRET="replace-this-with-a-long-random-secret"
C:\Users\25gea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe server.py
```

Notes:

- `GOOGLE_CLIENT_ID` should be a web application client ID from Google Cloud.
- `SESSION_SECRET` should be a long random string for signing session cookies.
- Without `GOOGLE_CLIENT_ID`, the app still works in guest mode on the local server.

## Publish it

This app can be published as a single-instance web service.

Current deployment notes:

- The app now supports `HOST`, `PORT`, `APP_DATA_DIR`, and `DB_PATH` environment variables for production hosting.
- SQLite is fine for a simple first public release, but it should run as a single instance with persistent disk storage.
- Google sign-in will only work in production after you add your deployed site URL to the allowed origins in your Google Cloud OAuth settings.

### Render

This project includes a [render.yaml](C:/Users/25gea/Documents/Codex/2026-04-18-i-want-to-make-an-app/render.yaml) file for Render.

What it does:

- Runs the app as a Python web service.
- Stores SQLite data on a persistent disk.
- Adds a health check at `/api/config`.
- Generates a production session secret automatically.

To publish on Render:

1. Push this project to GitHub.
2. In Render, create a new Blueprint service from that repo.
3. Keep the persistent disk enabled.
4. Set `GOOGLE_CLIENT_ID` in the Render environment if you want cross-device Google sign-in.
5. In Google Cloud OAuth settings, add your final Render URL as an authorized JavaScript origin.
6. Deploy and open the public URL.

## Data model

- `users`: local guest user plus Google-backed users.
- `sessions`: cookie-based signed-in sessions.
- `locations`: storage spots scoped to a specific user.
- `materials`: inventory items scoped to a specific user.
- `flies`: saved fly patterns scoped to a specific user.
- `fly_materials`: links between a fly recipe and the materials it uses.
- `bug_reports`: saved bug reports scoped to a specific user.

## API routes

- `GET /api/config`
- `POST /api/auth/google`
- `POST /api/auth/logout`
- `GET /api/materials`
- `POST /api/materials`
- `GET /api/flies`
- `POST /api/flies`
- `GET /api/bug-reports`
- `POST /api/bug-reports`
- `PATCH /api/materials/:id/status`
- `GET /api/locations`
- `POST /api/locations`
- `GET /api/summary`
