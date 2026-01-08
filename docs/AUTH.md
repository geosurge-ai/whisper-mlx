# Google Authentication (OAuth2)

This guide explains how OAuth2 works for the QweN daemon's Gmail and Calendar sync.

## Cost: Completely Free

**Everything is free.** Anyone with a Google account (personal Gmail or Workspace) can:

- Access Google Cloud Console - **free**
- Create projects - **free**
- Create OAuth credentials - **free**
- Use Gmail/Calendar APIs - **free** (generous quotas for personal use)

No credit card required. No trial period. Just a Google account.

---

## Quick Start

```bash
# 1. Store your OAuth client secret in passveil (one-time)
passveil set google/qwen-sync-oauth < ~/.qwen/client_secrets.json

# 2. Authenticate each user account
python -m daemon.sync.auth --account myname

# 3. Start the daemon - sync happens automatically
./run-daemon
```

---

## Understanding OAuth2

### The Key Insight: One App, Many Users

```
┌─────────────────────────────────────────────────────────────────┐
│                     ONE OAuth Client                             │
│              (client_secrets.json / passveil)                    │
│                                                                  │
│  This is YOUR APP's identity. Created once in Google Cloud.     │
│  Think of it as your app's "API key" for talking to Google.     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────┴─────────────────────┐
        │                                           │
        ▼                                           ▼
┌───────────────────┐                     ┌───────────────────┐
│    User: ep       │                     │    User: jm       │
│  credentials.json │                     │  credentials.json │
│                   │                     │                   │
│  "ep@memorici.de  │                     │  "jm@memorici.de  │
│   allows this app │                     │   allows this app │
│   to read email"  │                     │   to read email"  │
└───────────────────┘                     └───────────────────┘
```

**Key terms:**

| Term | What it is | Where it lives |
|------|------------|----------------|
| **Client Secrets** | Your app's identity (ID + secret) | `passveil:google/qwen-sync-oauth` |
| **User Credentials** | A user's permission to your app | `~/.qwen/accounts/<name>/credentials.json` |
| **Access Token** | Short-lived token (1 hour) for API calls | Inside credentials.json |
| **Refresh Token** | Long-lived token to get new access tokens | Inside credentials.json |

### Token Lifecycle

```
User clicks "Allow" in browser
         │
         ▼
┌─────────────────────┐
│  Refresh Token      │ ◄── Lives "forever" (with caveats, see below)
│  (stored locally)   │
└─────────────────────┘
         │
         │ Used to get...
         ▼
┌─────────────────────┐
│  Access Token       │ ◄── Expires after 1 hour
│  (used for API)     │
└─────────────────────┘
         │
         │ When expired, daemon auto-refreshes
         ▼
┌─────────────────────┐
│  New Access Token   │ ◄── Another 1 hour
└─────────────────────┘
```

---

## Setup Instructions

### Step 1: Create OAuth Client (One-Time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new project (e.g., "qwen-sync") or select existing
3. Enable APIs:
   - [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com)
   - [Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)

4. Configure OAuth consent screen:
   - Go to [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
   - Choose **Internal** (for Workspace) or **External** (for personal Gmail)
   - Fill in app name: "QweN Sync"
   - Add your email as support contact

5. Create credentials:
   - Go to [Credentials](https://console.cloud.google.com/apis/credentials)
   - Click **Create Credentials** → **OAuth 2.0 Client ID**
   - Application type: **Desktop app**
   - Name: "QweN Sync Desktop"
   - Download the JSON file

### Step 2: Store Secret in Passveil

```bash
# Save the downloaded JSON to passveil
passveil set google/qwen-sync-oauth < ~/Downloads/client_secret_*.json

# Verify it worked
passveil show google/qwen-sync-oauth | head -3
```

The JSON looks like:
```json
{
  "installed": {
    "client_id": "123456789-xxx.apps.googleusercontent.com",
    "client_secret": "GOCSPX-...",
    ...
  }
}
```

### Step 3: Authenticate Users

For each person who wants to sync their email:

```bash
# The account name is just a local identifier (pick anything)
python -m daemon.sync.auth --account emilie

# This opens a browser. Sign in with the Google account (e.g., emilie.mchl@gmail.com)
# The credentials are saved to ~/.qwen/accounts/emilie/credentials.json
```

### Step 4: Start the Daemon

```bash
./run-daemon
```

The daemon automatically:
- Syncs all authenticated accounts on startup
- Re-syncs every 5 minutes
- Refreshes tokens before they expire

---

## User Types: Internal vs External

### Internal Users (Google Workspace)

If you have a Google Workspace organization (like `memorici.de`):

- Set OAuth consent to **Internal**
- Only users in your organization can authenticate
- Tokens never expire (refresh works forever)
- No verification required

### External Users (Personal Gmail)

For personal Gmail accounts (like `@gmail.com`) - **still completely free**:

1. Set OAuth consent to **External**
2. **IMPORTANT**: While in "Testing" mode, tokens expire after **7 days**!
3. To fix this, you must either:
   - **Add test users** (up to 100, free): They can use the app, but still 7-day token expiry
   - **Publish the app** (free, but slow): Tokens last forever, requires Google verification (takes weeks)

#### Adding Test Users

1. Go to [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
2. Under "Test users", click **Add Users**
3. Enter the Gmail address (e.g., `emilie.mchl@gmail.com`)
4. Now that user can authenticate

#### Publishing the App

For sensitive scopes (Gmail), Google requires:
- Privacy policy URL
- App verification (can take weeks)
- Homepage URL

For personal use, just add yourself/family as test users and re-auth weekly.

---

## Token Expiration Reference

| Scenario | Token Lifetime | Notes |
|----------|----------------|-------|
| Internal user (Workspace) | Forever* | Refresh token works indefinitely |
| External + Testing mode | 7 days | Must re-authenticate weekly |
| External + Published | Forever* | After Google verification |
| User revokes access | Immediate | User went to Google account settings |
| 6 months unused | Expires | Refresh token invalidated |

*"Forever" means the refresh token works as long as:
- User doesn't revoke access
- App credentials aren't changed
- Token is used at least once every 6 months

---

## Managing Accounts

```bash
# List all authenticated accounts
python -m daemon.sync.auth --list

# Authenticate a new account
python -m daemon.sync.auth --account newperson

# Re-authenticate (if token expired)
python -m daemon.sync.auth --account emilie
# (It will ask if you want to re-authenticate)
```

---

## Where Data is Stored

```
~/.qwen/
├── accounts/
│   ├── ep/
│   │   └── credentials.json      # ep's OAuth tokens
│   ├── jm/
│   │   └── credentials.json      # jm's OAuth tokens
│   └── emilie/
│       └── credentials.json      # emilie's OAuth tokens
│
└── data/
    ├── ep/
    │   ├── emails/               # ep's synced emails
    │   ├── attachments/          # ep's attachments
    │   └── calendar/             # ep's calendar events
    ├── jm/
    │   └── ...
    └── emilie/
        └── ...
```

**Security notes:**
- `credentials.json` files are chmod 600 (owner read/write only)
- Never commit `~/.qwen/` to version control
- The `client_secrets.json` should be in passveil, not filesystem

---

## Troubleshooting

### "Access blocked: This app's request is invalid"

The OAuth consent screen isn't configured. Go to:
https://console.cloud.google.com/apis/credentials/consent

### "Error 403: access_denied"

For external users: You haven't added them as test users, or the app isn't published.

### "Token has been expired or revoked"

The refresh token is dead. Re-authenticate:
```bash
python -m daemon.sync.auth --account theaccount
```

### "client_secrets.json not found"

Either:
1. Store it in passveil: `passveil set google/qwen-sync-oauth < client_secrets.json`
2. Or put it at: `~/.qwen/client_secrets.json`

### Tokens keep expiring after 7 days

You're in "Testing" mode with external users. Either:
- Accept weekly re-auth
- Publish the app (requires verification)
- Switch to Internal (if all users are in your Workspace)

---

## Security Best Practices

1. **Never commit secrets**: The `client_secrets.json` contains your app's secret key
2. **Use passveil**: Store `client_secrets.json` in passveil, not filesystem
3. **Minimal scopes**: We only request read-only access to Gmail and Calendar
4. **Local storage**: All synced data stays on your machine in `~/.qwen/data/`
5. **No cloud sync**: Your emails are never sent anywhere except local disk
