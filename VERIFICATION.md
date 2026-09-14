# Verification

## Automated

- Python unit tests: run with `python3 -m unittest discover -s tests -v`.
- Python syntax: `python3 -m py_compile monitor.py`.
- Workflow YAML parsed locally when PyYAML is available.
- Telegram notification step uses Python standard library only; no third-party package/API key beyond Telegram secrets.

## Behavior

- First successful run creates baseline and does not notify.
- A new normalized `CTKM:` title creates `data/notification.md`.
- Workflow attempts Telegram first.
- If Telegram step fails, GitHub Issue fallback runs.
- PDF URLs are not promotion detail URLs.
- Zero parsed cards fails closed.

## Not verified here

- Live GitHub Actions runner accessing Amway.
- Live Telegram delivery using the user's bot token/chat ID.

Those require the user's GitHub repository and Telegram credentials and must be verified after deployment.
