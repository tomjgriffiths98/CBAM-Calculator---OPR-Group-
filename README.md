# CBAM UK and EU Calculator (static web page)

`docs/index.html` is the calculator. It reads `docs/data.json` (UK rate, EU price, mills, default values).
`update_data.py` rewrites `data.json`. GitHub Pages serves the `docs/` folder.

## IMPORTANT: who can see it
A GitHub Pages site from a normal (free/Team) repo is **public to anyone with the link**, even if the repo is private.
`data.json` contains each mill's embedded-emissions figures and OPR's default-value workings. Only publish this if
OPR is happy for that to be public. For a staff-only page use GitHub Enterprise Cloud (Pages with access control),
or keep using the shared Claude page.

## Set up
1. Create a repo on GitHub and push this folder to it (`git init`, `git add .`, `git commit`, `git remote add origin ...`, `git push -u origin main`).
2. Repo > Settings > Pages > Build and deployment: Source = "Deploy from a branch", Branch = `main`, folder = `/docs`. Save.
3. Your page appears at `https://<your-user-or-org>.github.io/<repo>/` after a minute or two.
4. Repo > Settings > Actions > General > Workflow permissions: "Read and write permissions".

## Keeping it current
- **Live prices (automatic):** `.github/workflows/update-data.yml` runs every weekday, reads the UK rate from GOV.UK and the EU carbon
  price from Purely Energy, and commits `docs/data.json` if it changed. If a page can't be read the old value stays and the run goes red (GitHub emails you).
- **Mills and default values (manual, from your computer):** the Excel workbooks live on SharePoint, which GitHub can't reach. Run:

      pip install -r requirements.txt
      python update_data.py --skip-web \
        --calculator-xlsx "CBAM UK AND EU CALCULATOR.xlsx" \
        --defaults-xlsx "Default Values Per Commodity Code NEW.xlsx"
      git add docs/data.json && git commit -m "Update mills and defaults" && git push

  (Use `--dry-run` first to see what would change; omit `--skip-web` to refresh prices at the same time.)
- **Official EU quarterly prices** (`eu_prices` in `data.json`) are added by hand when the Commission publishes them.

## Test locally
    cd docs && python -m http.server 8000     # then open http://localhost:8000

## Notes
- The workbook readers were tested against your two workbooks and reproduce the current data exactly.
- The GOV.UK and Purely Energy readers were tested on sample HTML only. If either site changes layout the script
  leaves the old value in place and warns rather than writing a wrong figure. Check the first scheduled run.
- `docs/index.html` contains a small shim that stands in for the Claude database when the page is not hosted by Claude.
