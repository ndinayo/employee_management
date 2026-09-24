# Employee Management frontend

React, React Router, Vite, and PDF.js power the responsive manager dashboard.
The complete setup, PostgreSQL configuration, API reference, and technical
assumptions are documented in the project [README](../README.md).

Run these commands from `frontend/` after completing the backend setup:

```sh
npm ci
npm run dev
```

Keep Django running at `http://127.0.0.1:8000`. Vite proxies development
requests under `/api/` to this address. Open the URL printed by Vite, normally
`http://localhost:5173`, and sign in with a manager or administrator account.

For verification and a local build preview:

```sh
npm run lint
npm run build
npm run preview
```

The npm dev/build scripts prepare local PDF assets automatically. Built assets
use `VITE_API_URL` (see `.env.example`); development uses the proxy in
`vite.config.js`. See the root README's [configuration instructions](../README.md#5-install-frontend-dependencies)
for details. In PowerShell, use `npm.cmd` if script policy blocks `npm.ps1`.
