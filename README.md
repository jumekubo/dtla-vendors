# DTLA Vendor Tracker

Vendor database for Good Vibe Design — local LA vendors in and around DTLA: what they sell, brands carried, wholesale policy, contacts, and notes. Runs entirely on GitHub Pages with data stored in this repo (`data/vendors.json`).

## One-time setup (about 5 minutes)

### 1. Turn on GitHub Pages
Repo **Settings → Pages → Source: Deploy from a branch → Branch: `main` / (root) → Save**.
After a minute the app is live at `https://<your-username>.github.io/dtla-vendors/`.

### 2. Create a personal access token (lets the app save edits)
1. Go to [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new)
2. Token name: `dtla-vendors`, expiration: 1 year
3. Repository access: **Only select repositories → dtla-vendors**
4. Permissions: **Contents → Read and write**, **Actions → Read and write**
5. Generate, copy the token, open the app, click **⚙ Settings**, paste it, save.

The token lives only in your browser's localStorage — it is never committed to the repo. Repeat step 5 on each device you use (e.g. phone at the Fashion District).

### 3. (Optional) Enable the auto-research button
The **↻ Update from Web** button can research every vendor automatically — verifying phones, addresses, hours, closures, and new brands carried — and open a pull request with proposed changes.

1. Get a **free** Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (Google account required, no credit card)
2. Repo **Settings → Secrets and variables → Actions → New repository secret**
   Name: `GEMINI_API_KEY`, value: your key
3. Repo **Settings → Actions → General → Workflow permissions**: select **Read and write permissions** and check **Allow GitHub Actions to create and approve pull requests**

Now the button works. Review the pull request it opens and merge if the changes look right. It also runs automatically on the 1st of each month (edit or delete the `schedule` block in `.github/workflows/update-vendors.yml` to change that).

No Gemini key? Use the button's second option — **Copy research prompt for Claude** — and paste it into a Claude/Cowork session instead.

## Daily use

- **Add / edit / delete** vendors in the app, then hit **Save Changes** to commit to the repo.
- Every change is a git commit, so you have full history and can revert anything.
- **Export** downloads a JSON backup.
- Vendors marked **unverified** have gaps the auto-research can likely fill.

## Data schema

Each vendor in `data/vendors.json`:

| Field | Meaning |
|---|---|
| `name`, `category`, `address`, `neighborhood`, `phone`, `email`, `website`, `instagram` | Basics |
| `contact_person` | Who you deal with there |
| `wholesale` | `Wholesale only` / `Wholesale + Retail` / `Retail only` / `Unknown` |
| `resale_permit_required` | Whether they ask for a seller's permit |
| `min_order` | Minimum order, e.g. "12 pcs per style" |
| `brands`, `items`, `tags` | Arrays — brands carried, what they sell, your labels |
| `hours`, `price_notes`, `parking_notes`, `notes` | Practical notes |
| `rating` | Your personal 0–5 rating (never touched by auto-research) |
| `status` | `active` / `unverified` / `closed` |
| `last_verified`, `added`, `updated` | Dates |

Auto-research only ever changes factual fields — your ratings, notes, and tags are never modified.
