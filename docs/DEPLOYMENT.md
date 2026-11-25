# Deployment guide

## 1. GitHub

Create a repository called `PriceSense` on GitHub. Choose public if you want to share the code. Extract the release ZIP and open the folder containing `README.md` and `render.yaml`. Upload its contents (including `.github`, `.gitignore` and `.python-version`), not the ZIP or a second enclosing folder. If using Git, run from that folder:

```sh
git init
git add .
git commit -m "Initial PriceSense release"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/PriceSense.git
git push -u origin main
```

Replace `YOUR_USERNAME`. Use an empty repository if using these commands; do not initialize a second README. GitHub Desktop is an alternative if you prefer a GUI. No credentials or virtual environment belong in the repository.

## 2. Render (recommended: Blueprint)

1. Sign in to https://dashboard.render.com/ and connect GitHub.
2. Choose **New > Blueprint** and select your PriceSense repository.
3. Review the service declared by `render.yaml`: Python, free plan, one web service. Confirm deployment.
4. Open the web service's generated public HTTPS URL after it becomes live.
5. Check `/health`, then open the dashboard and generate a forecast. `/docs` shows the API documentation.

The Blueprint configures a single process, Python version via `.python-version`, numeric thread limits and health check. It doesn't need any API key, persistent disk, database or separate static site. Render automatically sets `PORT`.

## 3. Manual alternative

Choose **New > Web Service**, connect GitHub and select the `main` branch. Leave Root Directory blank. Select Python and Free. Set:

- Build: `pip install -r requirements.txt`
- Start: `python -m uvicorn pricesense_api_scraper.api:app --host 0.0.0.0 --port $PORT --workers 1`
- Health check: `/health`
- Environment variables: `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `NUMEXPR_NUM_THREADS=1`.

## 4. Troubleshooting

- **Could not find requirements.txt**: check the repo root and make sure you uploaded the extracted files, not the ZIP.
- **Could not import module**: verify `pricesense_api_scraper/api.py` exists and use the exact start command above from the repository root.
- **Dependency error**: verify `.python-version` is committed and Render is using Python 3.13. Check the build log for the precise dependency error.
- **Slow loading**: free Render services spin down after 15 minutes of inactivity; waking can take around a minute. The first forecast also trains several models. Open the site before a presentation. Test locally with `run_pricesense.bat` as backup.
- **Out of memory or timeout**: check Render logs. Free compute is limited; use a paid instance or local server for larger workloads. Keep a single worker and the thread limits. The application is an academic prototype without production authentication or rate limiting; avoid sharing it for high-volume public use.
- **No GitHub Actions checks**: confirm the hidden `.github/workflows/checks.yml` file was uploaded. Actions must be enabled in your repo.

Official hosting docs: https://render.com/docs/deploy-fastapi and https://render.com/docs/free.

The original frontend, model source code and datasets are unchanged by deployment packaging. The smoke tests passed locally using the pinned installed Python packages; actual deployment requires your GitHub and Render accounts and has not been performed here.
