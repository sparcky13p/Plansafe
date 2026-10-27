# Deploying PlanSafe

Everything runs locally with no keys (SQLite, dev user, drawing-label detection).
Each service below switches on when its environment variables are set.

## Local development

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Windows
npm --prefix web install
.venv/Scripts/uvicorn api.index:app --reload --port 8000                   # API
npm --prefix web run dev                                                    # http://localhost:5173
.venv/Scripts/python -m pytest                                              # tests
```

Copy `.env.example` to `.env` for local keys (never commit it).

## Vercel (one-time setup)

1. **Import the repo** in Vercel (New Project → GitHub → `Plansafe`). Framework preset: *Other*.
   `vercel.json` already sets install/build commands, the output directory and the functions.
2. **Neon Postgres**: Project → Storage → Marketplace → Neon → connect.
   Sets `DATABASE_URL`/`POSTGRES_URL`. Tables are created on first request.
3. **Vercel Blob**: Storage → Create → Blob → connect. Sets `BLOB_READ_WRITE_TOKEN`
   (enables uploads > 4.5 MB).
4. **Clerk**: create an application at clerk.com, then set
   - `VITE_CLERK_PUBLISHABLE_KEY` (Publishable key)
   - `CLERK_ISSUER` (Frontend API URL, e.g. `https://xxx.clerk.accounts.dev`)
   - `CLERK_AUTHORIZED_PARTIES` = your deployment URL(s), comma separated
   Without Clerk, a deployed app refuses requests unless `ALLOW_DEV_AUTH=1` (single shared user, demo only).
5. **Muse Spark**: `MUSE_API_KEY`, `MUSE_API_BASE`, `MUSE_MODEL` from the Meta Model API console.
   The client speaks the OpenAI-compatible chat-completions format (`safetyplan/detect/muse.py`).
6. **SAM 3.1** (photo check): `SAM_API_KEY`, `SAM_API_BASE`, `SAM_MODEL`.
   The request/response shape is assumed in `safetyplan/photo/sam.py` (`HttpSam`); adapt it to the provider.
7. Redeploy after setting variables (`VITE_*` values are baked in at build time).

## After the first deploy, check

- `GET /api/me` shows `database: postgres`, `blob_uploads: true`, `vision_model: muse`.
- Upload a real 5–10 MB DXF (exercises Blob + function timeout).
- Function bundle size in the deployment's *Functions* tab stays under 250 MB.
- Download the PDF report and the purchase-order XLSX.

## Before a pilot

- Have a safety professional verify the `is_bocw` and `site_practice` rule packs
  (`safetyplan/rules/library/*.yaml`) and set `verified: true` rule by rule.
- Replace the demo supplier catalogues with real price lists (Suppliers page).
