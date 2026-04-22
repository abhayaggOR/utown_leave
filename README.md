# UTown Leave Tracker

A lightweight leave-tracking web app for UTown with employee accounts and owner approval.

## What it does

- Gives the business owner a dedicated owner login ID and password
- Generates employee IDs like `UT001`, `UT002`, and employee passwords
- Lets employees submit one weekday leave request per month
- Blocks Saturday and Sunday leave requests
- Blocks two employees from using the same date
- Shows pending and approved requests on the shared live board
- Lets the owner approve or disapprove requests
- Lets the owner reset employee passwords and activate or deactivate employee accounts

## Run it

```bash
python3 server.py
```

Then open `http://127.0.0.1:8000` in your browser.

## Default owner credentials

- Owner login ID: `owner`
- Owner password: `utown-admin`

The owner can change both from the Owner panel after logging in.

## Handover flow

1. Log in to the Owner panel with the default owner credentials.
2. Create each employee account from the Owner panel.
3. The app generates an employee ID and password for each new employee.
4. Share those generated credentials with the business owner or directly with each employee.
5. Employees use their own employee ID and password to submit leave requests.
6. The owner approves or disapproves each request from the pending approvals list.

## Custom owner credentials on first run

You can still set a custom owner login and password from the terminal before starting the app:

```bash
UTOWN_OWNER_ID="owner1" UTOWN_OWNER_PASSWORD="your-password" python3 server.py
```

## Hosting for access from anywhere

If employees need to use the app from any network, deploy it on a public cloud host instead of running it from your laptop.

### Best fit for this version of the app

This app stores data in a local file, so it must be deployed with persistent storage.

- Recommended: Railway with a mounted volume
- Also works: Render web service with a persistent disk

### Important hosting requirements

- The app must listen on `0.0.0.0`
- The host must pass a public `PORT`
- The `data/store.json` file must live on persistent storage

This repo is already prepared for that:

- `Dockerfile` included
- `HOST` defaults to `0.0.0.0`
- `UTOWN_STORE_PATH` can point to a mounted persistent file path
- `UTOWN_TIMEZONE` can set the business timezone for the in-app "today" date
- Health check available at `/healthz`

### Example persistent file path setup

- Railway volume mounted to `/app/data`
  `UTOWN_STORE_PATH=/app/data/store.json`
- Render persistent disk mounted to `/opt/render/project/src/data`
  `UTOWN_STORE_PATH=/opt/render/project/src/data/store.json`
