# Deploy account signup

Signup requires both the new Django backend and the new frontend. Local source changes do not update Render or Vercel automatically until the changes reach their connected Git branch and deploy successfully.

## 1. Deploy the backend first

For the current backend, `https://employee-management-v2pz.onrender.com`, use the following Render settings:

| Setting | Value |
| --- | --- |
| Root Directory | `backend` |
| Build Command | `bash build.sh` |
| Start Command | `bash start.sh` |
| Health Check Path | `/api/health/` |

If Root Directory is empty instead, use `bash backend/build.sh` and `bash backend/start.sh`.

The start script runs migrations before Gunicorn starts. Confirm migration `api.0006_business_alter_employee_email_alter_holiday_date_and_more` completes in Render's logs. It creates the business/account tables and adds workspace ownership; existing records remain in the original managers' workspace. No existing accounts or records are assigned to new public employers.

Keep the existing production `SECRET_KEY` and `DATABASE_URL` configured. Set these frontend settings on the **active backend service**:

```dotenv
DEBUG=false
FRONTEND_URL=https://employee-management-one-sooty.vercel.app
CORS_ALLOWED_ORIGINS=https://employee-management-one-sooty.vercel.app,https://employee-management-idwumevl9-ndinayo-erics-projects.vercel.app
```

Use the origins without quotes, paths, trailing slashes or `#sign-in`. Add another exact origin if you use a different preview deployment URL. Save and deploy the environment changes. A healthy API responds to `/api/health/` with `{"status":"ok"}`.

Public signup does not require an initial admin account. If bootstrap admin environment variables are configured, they still must be valid because `start.sh` runs `bootstrap_admin` before Gunicorn. Existing administrator passwords are not changed by signup.

## 2. Deploy the frontend

Vercel should use `frontend` as its Root Directory. Its committed `vercel.json` runs the build and handles client routes. Set this environment variable for the environment being deployed:

```dotenv
VITE_API_URL=https://employee-management-v2pz.onrender.com
```

Do not append `/api`. Rebuild/redeploy after changing this variable: Vite embeds it into the built JavaScript.

Use the production site at `https://employee-management-one-sooty.vercel.app/#sign-in`. The longer deployment URL may require Vercel authentication before it displays the application.

## 3. Verify after deployment

1. Open the production frontend in a private browser window and choose **Create account**.
2. Choose **Employer**, enter a business name, email, unique username, password and matching confirmation. Submit and confirm the business dashboard opens with the entered business name.
3. Sign out and sign back in using that username and password. Refresh the dashboard to confirm the session restores.
4. In a separate browser session, create an **Employee** account. It should open the personal account page without requiring a business name. It must not open the employer dashboard.
5. Confirm required fields, mismatched passwords, duplicate usernames and wrong passwords produce clear errors.

Employee signup creates a login account only. Connecting employees to businesses, invitations and employee self-service are outside this signup flow. Employers manage employment records independently.

## Troubleshooting

- **Create account is missing:** Vercel is still serving the old frontend build.
- **Signup or account endpoint returns 404:** Render is serving the old backend revision; deploy the new code first.
- **Database table/column missing:** Check migration `0006` and ensure Render uses `bash start.sh`.
- **Cannot reach the server / browser CORS error:** Check `VITE_API_URL` and the allowed origin on the active Render service. A successful health check alone does not verify CORS.
- **Username or password is incorrect:** Use the username created through signup and its password. Local database accounts are separate from the deployed database. Public signup does not create an account named `admin` automatically.
- **Server taking too long:** Check Render readiness and startup logs; the form times out after 60 seconds and allows retrying.

Deployment should retain the existing persistent upload storage configuration. Business scoping applies to file endpoints as well as database records.
