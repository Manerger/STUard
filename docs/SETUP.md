# Setup guide

This guide is for server admins running their own copy of STUard. Members don't need any of it: the [README](../README.md) covers everything they use.

**Contents**

1. [How verification works](#how-verification-works)
2. [Commands](#commands)
3. [Setup](#setup)
4. [Local development and tests](#local-development-and-tests)
5. [Data and privacy (GDPR)](#data-and-privacy-gdpr)
6. [Troubleshooting](#troubleshooting)

---

## How verification works

> **The bot never sees passwords.** Members sign in with their school Microsoft 365 account, and STU's Microsoft 365 hands the password step to STU's own login page (`idp.stuba.sk`). The bot only receives the login, the AIS ID and the account type from Microsoft.

1. **Get a link.** The member runs `/verify`, or clicks **Overiť sa** in the verification channel, and gets a personal one-time link. It is valid for 10 minutes and only they can see it.
2. **Confirm the Discord account.** The link opens the bot's web page. Discord first confirms the browser is logged into the same Discord account, so a forwarded link is useless.
3. **Sign in with Microsoft 365.** The member clicks **Prihlásiť sa cez Microsoft 365** and signs in with their `@stuba.sk` account; the password is typed on idp.stuba.sk.
4. **Checks.** The bot:
   - accepts only STU's Microsoft 365 organization (tenant `25733538-6b16-4aa3-8ed6-297eb79b8e06`) and `@stuba.sk` logins, and rejects guest accounts
   - verifies Microsoft's signed ID token (signature, app, issuer, expiry, one-time nonce) and uses PKCE
   - only finishes in the browser that started the flow
5. **Profile.** With the basic **User.Read** permission the bot reads exactly two fields from Microsoft: `employeeId` (the AIS ID) and `employeeType` (for example `student`).
6. **Roles.** The bot stores only a keyed hash (HMAC) of the AIS ID, so one school account can't verify two Discord accounts, then assigns roles.

| Microsoft `employeeType` | Result |
|---|---|
| `student` | **Študent** – then picks degree, programme and year |
| `employee`, `staff`, `faculty` | moderator review for **Vyučujúci** (never automatic; STU's exact staff value is unconfirmed) |
| anything else, or missing | moderator review (`microsoft.unmatched: student` gives Študent instead) |

Change the lists in `config.yaml` → `microsoft`. The raw `employeeType` is written to the audit log, so you can see what STU uses for staff.

If Microsoft shows **"Need admin approval"**, STU requires an administrator to review third-party apps before students can sign in to them. Switch the Microsoft login off (`/admin microsoft off`) and keep using manual review, which needs no approval. Allowing the app is STU IT's decision; if you ask them, explain what the bot does and the one permission it requests (`User.Read`).

### Email-code verification (optional, `/verify-email` → `/verify-code`)

Verifies **students** with a one-time code sent to `<login>@stuba.sk`. The member runs `/verify-email login:<xlogin>` (or their AIS ID), the bot emails a code, and `/verify-code code:<CODE>` proves they control a real STU mailbox → **Študent**. No password is involved, and it needs no STU IT approval. Applicants (no mailbox) still use manual review. Toggle at runtime with **`/admin email on|off`**.

**Prerequisite — SMTP.** Set `SMTP_*` in `.env` (a Gmail account with an *App Password* works: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`, `SMTP_USER`/`SMTP_FROM` = the address, `SMTP_PASSWORD` = the app password). Without SMTP configured, `/verify-email` reports it's not set up.

**Optional LDAP enrichment** (`email.ldap.enabled`). Looks the login up in STU's directory to add **faculty** (so only MTF students auto-verify), **student/staff type** (staff → a Vyučujúci moderator review, never automatic), and the **AIS ID** (so the identity fingerprint matches the Microsoft/SAML one — needed for cross-method duplicate detection). Anonymous LDAPS bind, so **the bot must run inside STU's network** — a VPN sidecar on the Pi (the STU OpenVPN profile), like the FEI bot. Without LDAP, a verified mailbox simply becomes Študent (`email.without_ldap`), with faculty/type unknown.

Identity binding stores an HMAC of `<AIS ID>@stuba.sk` (with LDAP) or `<login>@stuba.sk` (without), so one account can't verify two Discords. Pending codes are hashed, expire after `code_ttl_minutes`, and are deleted on use.

### Manual review (applicants)

- Members run `/verify-manual` and upload a screenshot of their UIS portal, or applicants a screenshot of their e-prihláška.
- This is the route for applicants: they have no school Microsoft 365 account, and idp.stuba.sk doesn't recognise e-prihláška accounts.
- The request goes to `channels.mod_review` (by default the channel named `admin_room_verifikacie`) with **Schváliť / Zamietnuť** buttons.
- The screenshot is deleted as soon as a moderator decides.

### Optional: STU login (idp.stuba.sk)

The bot can also sign members in directly through STU's SAML login server. It's off by default and only works if STU IT or the safeID federation choose to register the bot, which is entirely their decision. STU sends `eduPersonPrincipalName` = `<AIS ID>@stuba.sk`, the same identifier as the Microsoft login, so one account still can't verify two Discord accounts.

There are two ways to get registered, set with `sso.identity_attribute` and `sso.entity_categories`:

| Route | What STU sends | Notes |
|---|---|---|
| STU IT, or safeID with Code of Conduct v2 | `eduPersonPrincipalName` = `<AIS ID>@stuba.sk` | same identifier as Microsoft, so both logins can run side by side |
| safeID with **Pseudonymous Access** (`identity_attribute: pairwise_id`) | a random ID made only for this bot, plus the student/staff status | shares the least personal data. It can't be matched with the Microsoft login, so run only one automatic login at a time |

The bot lists the entity categories it asks for in its SAML metadata; the federation decides which, if any, to grant.

| Affiliation from `idp.stuba.sk` | Result |
|---|---|
| `student` | **Študent** |
| `alum` | **Absolvent** |
| `affiliate` (*unconfirmed* who gets it) | moderator review, suggested **Uchádzač** |
| `faculty`, `staff`, `employee` | moderator review for **Vyučujúci** (never automatic) |
| anything else | moderator review |

### Status lifecycle

- **Bývalý študent** (dropout) keeps general access but loses degree, programme and year roles. A student becomes one when:
  - a moderator sets it with `/mod status`
  - they miss the re-verification deadline
  - with the STU login only: they re-verify and STU no longer reports them as a student

  A Microsoft login never removes a status by itself.
- **Yearly re-verification** runs 20 Sep – 31 Oct (configurable). Reminders are sent by DM 30, 14 and 3 days before the deadline.
- **Manual role edits.** If a moderator removes **Študent** by hand, the bot turns the member into Bývalý študent. If someone adds **Študent** by hand, the bot removes it again; use `/mod status` instead.

---

## Commands

| Command | Who | What |
|---|---|---|
| `/verify` | everyone | Personal link to sign in with Microsoft 365 (and the STU login, if enabled) |
| `/verify-manual rola screenshot [poznamka]` | everyone | Manual verification request |
| `/profile` | verified | Status, validity, and degree/programme/year picker |
| `/privacy` | everyone | Privacy notice and a JSON copy of your data |
| `/forget-me` | everyone | Delete your data and verified roles |
| `/mod status member status reason` | moderators | Set Študent / Uchádzač / Absolvent / Bývalý študent / neoverený |
| `/mod teacher member add\|remove reason` | moderators | Vyučujúci role |
| `/mod info member` | moderators | Verification details |
| `/mod unlink member` | moderators | Detach a school account from a member |
| `/mod reverify member [days]` | moderators | Ask a member to re-verify |
| `/mod requests` | moderators | Pending reviews |
| `/mod lookup ais_id` | admins | Which member uses an AIS ID (audited) |
| `/setup check\|roles\|panels\|sync\|reload-config` | admins | Setup |
| `/admin microsoft on\|off\|default` | admins | Switch Microsoft 365 sign-in without editing config |
| `/admin sso on\|off\|default` | admins | Switch the STU login without editing config |
| `/admin reverify-status`, `/admin reverify-run` | admins | Re-verification |

Moderators are members with a role listed in `moderator_role_ids` (or admins). Admins have Administrator permission or a role in `admin_role_ids`.

---

## Setup

### 1. Discord application

1. Go to https://discord.com/developers/applications → **New Application**.
2. On the **Bot** page:
   - Reset and copy the token (`DISCORD_TOKEN`).
   - Enable **Server Members Intent**.
3. On the **OAuth2** page:
   - Copy the Client ID and Client Secret.
   - Add the redirect `https://<your host>/oauth/discord/callback`.
4. Invite the bot (replace `CLIENT_ID`). This URL grants View Channels, Send Messages, Embed Links, Attach Files, Read Message History and Manage Roles:
   ```
   https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=268553216
   ```
5. Copy the server ID (`DISCORD_GUILD_ID`): Developer Mode → right-click the server → Copy ID.

### 2. Configuration

```bash
cp .env.example .env
cp config.example.yaml config.yaml
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # → SUBJECT_HMAC_KEY
```

**`.env`** holds the secrets:
- Discord token and OAuth client
- Microsoft app ID and secret (section 3)
- `PUBLIC_BASE_URL`
- `SUBJECT_HMAC_KEY` – back it up separately from the database

**`config.yaml`** holds everything else:
- channels, by name or ID – verification requests go to `admin_room_verifikacie` (make it private: moderators and the bot only)
- moderator and admin role IDs – put the ID of your **Server admin** role in `admin_role_ids` (members with the Administrator permission count as admins anyway)
- role names – year roles already use the server's existing names `1-BC`, `2-BC`, `3-BC`, `1-ing`, `2-ing`, plus `1-PhD` … `4-PhD` (`study.degrees.*.year_role`); no separate `Bc.`/`Ing.` roles unless you set `study.role_names.degree`
- the programme list (already filled in with MTF Bc./Ing./PhD. programmes; roles look like `Bc. Mechatronika`)
- which Microsoft account types give which role (`microsoft`)
- re-verification dates
- the privacy contact

### 3. Microsoft 365 app

1. Open https://entra.microsoft.com with a Microsoft account that has its own Entra directory (a free Azure account creates one; STU accounts usually can't register apps) → **App registrations → New registration**.
2. **Supported account types:** "Accounts in any organizational directory (Any Microsoft Entra ID tenant – Multitenant)".
3. **Redirect URI:** platform **Web**, `https://<your host>/oauth/microsoft/callback`. For testing on your own computer also add `http://localhost:8080/oauth/microsoft/callback`.
4. Copy the **Application (client) ID** into `MICROSOFT_CLIENT_ID`. Under **Certificates & secrets → New client secret**, copy the secret *value* into `MICROSOFT_CLIENT_SECRET`. The secret expires, so note the date and renew it in time.
5. **API permissions:** keep **Microsoft Graph → User.Read** (delegated). The bot uses it to read `employeeId` and `employeeType` and nothing else.
6. Start the bot, run `/verify` and try **Prihlásiť sa cez Microsoft 365** with your own STU account:
   - **It works:** you're done – check `/mod info` on yourself and the audit log for `employee_type`.
   - **Microsoft says "Need admin approval":** STU reviews third-party apps before students can use them. Run `/admin microsoft off` and keep using manual review. Allowing the app is up to STU IT.

### 4. Run

**On a server with Docker (recommended).** `docker-compose.yml` runs the bot together with a `cloudflared` connector, so HTTPS is terminated by Cloudflare and **no port is published on the host and none is opened on the router**. Set `CLOUDFLARE_TUNNEL_TOKEN` in `.env` from a tunnel of its own (Zero Trust → Networks → Tunnels), and point that tunnel's public hostname at `http://bot:8080` — `bot` is the compose service name, reachable only from inside the stack. Don't reuse a token from a tunnel that already serves something else: Cloudflare would treat the two connectors as replicas and route that other hostname here, where it can't be served.

To run without Cloudflare, delete the `cloudflared` service, restore the `caddy` service from `Caddyfile`, and point a domain at the server with ports 80 and 443 open.

```bash
docker compose up -d --build
docker compose logs -f bot
```

**Directly on macOS or Linux** (Python 3.12+):

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m stuard
```

The web server must be reachable over HTTPS at `PUBLIC_BASE_URL` for the Microsoft and Discord sign-in, for example behind Caddy, nginx or Cloudflare Tunnel. In manual-review-only mode no public URL is needed.

### 5. First run in Discord

1. Run `/setup check`. It shows what is missing.
2. Run `/setup roles`. Roles that already exist with the same name (ignoring case), such as `1-BC` … `2-ing`, are linked instead of duplicated; only the missing ones are created (Študent, Uchádzač, Vyučujúci, Absolvent, Bývalý študent, Overený, PhD years, programmes).
   - If `/setup check` warns that members hold year roles without being verified students, remove those roles by hand or ask the members to `/verify`. The bot never strips roles from members it hasn't verified.
3. In **Server Settings → Roles**, drag the **bot's role above all STUard roles**, including the existing `1-BC` … `2-ing`. Discord doesn't let a bot manage roles above its own.
4. Run `/setup panels`. It posts the verification panel to `channels.verify` and the study panel to `channels.study_panel`.
5. Run `/setup check` again. Everything should be ✅.

### 6. Channel permissions

The bot manages roles; you set channel permissions once:

| Channel / category | @everyone | Overený | Študent | e.g. `Bc. Mechatronika`, `2-BC` |
|---|---|---|---|---|
| #vitaj, #overenie | view | view | view | view |
| general channels | – | view | view | view |
| study category (all students) | – | – | view | view |
| programme or year channel | – | – | – | view (that role only) |
| admin_room_verifikacie, audit | – | – | – | – (moderators only) |

Every verified member has **Overený**, including Bývalý študent. Programme and year roles exist only alongside **Študent**, and the bot enforces that. Former students automatically lose study channels.

### 7. Optional: STU login (idp.stuba.sk)

1. Create the SAML keys and pin STU's metadata:
   ```bash
   scripts/gen_sp_keys.sh verify.example.sk            # secrets/sp.key + secrets/sp.crt
   .venv/bin/python scripts/fetch_idp_metadata.py      # saml/idp_metadata.xml + certificate fingerprints
   ```
   With Docker, run `sudo chown 10001:10001 secrets/sp.key` (the container runs as uid 10001).
2. Apply to STU IT or the safeID federation. Registration is their decision: describe what the bot does and the minimum data it needs, follow their requirements, and confirm the IdP certificate fingerprints with them.
3. If the service is registered, test with your own account: `/admin sso on`, then `/verify`. Check the audit channel for the affiliation values STU sent.
4. Set `sso.enabled: true` in `config.yaml` and run `/admin sso default`.

---

## Local development and tests

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # unit, Microsoft and SAML token checks, web-flow and round-trip tests
.venv/bin/ruff check .
```

To test the Microsoft sign-in on your computer before hosting, add the localhost redirect URI (section 3) and use in `.env`:

```
PUBLIC_BASE_URL=http://localhost:8080
DEV_ALLOW_HTTP=true
DISCORD_OAUTH_REQUIRED=false        # or add http://localhost:8080/oauth/discord/callback as a Discord redirect
```

For the STU login there's a **dev IdP** that signs any test identity you click (local use only):

```bash
.venv/bin/python dev/dev_idp.py     # http://localhost:8081, writes dev/idp_metadata.xml
```

Add `SAML_IDP_METADATA_FILE=dev/idp_metadata.xml` and `SAML_IDP_ENTITY_ID=http://localhost:8081/metadata` to `.env`, run `scripts/gen_sp_keys.sh localhost`, start the bot and run `/admin sso on`. Use a separate test Discord server and bot application.

---

## Data and privacy (GDPR)

**Stored:**
- Discord ID
- status and its dates
- HMAC of the AIS ID (or of the school login, for accounts without an AIS ID)
- account type / affiliation values
- degree, programme and year
- review metadata
- audit log

**Not stored:**
- passwords
- logins, AIS IDs, names or emails in readable form
- screenshots after a decision

**Retention:**
- unfinished verifications: 24 h
- members who left the server: 30 days
- audit log: 180 days

Members can export their data (`/privacy`) and delete it (`/forget-me`). The privacy notice is also at `https://<host>/privacy`. Set `privacy_contact` in `config.yaml`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `PrivilegedIntentsRequired` on start | Enable **Server Members Intent** in the Developer Portal |
| Slash commands don't appear | `SYNC_COMMANDS=true` for one start, or `/setup sync` |
| Roles are not assigned | `/setup check` – move the bot role above the managed roles; give it Manage Roles |
| Microsoft shows "Need admin approval" | STU requires administrator review of third-party apps. Run `/admin microsoft off` and use manual review; allowing the app is STU IT's decision |
| Microsoft sign-in fails with code `microsoft_profile` in the audit log | The app registration is missing the **User.Read** permission |
| Members get a moderator review instead of Študent | Check `employee_type` in the audit log and add the value to `microsoft.student_types` |
| `SAML service provider disabled, missing files` | Only matters for the STU login: run `scripts/gen_sp_keys.sh` and `scripts/fetch_idp_metadata.py` |
| `lxml & xmlsec libxml2 library version mismatch` | Use the Docker image, or `pip install --no-binary lxml,xmlsec lxml xmlsec` |
