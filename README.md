# Matiks support dashboards

Three independent dashboards in the same private repository. Each folder has its own dependencies, setup instructions and environment template. Existing work is preserved in `full-dashboard/`.

| Dashboard | Folder | Local URL | Purpose |
| --- | --- | --- | --- |
| Merch Dashboard | [merch-dashboard](merch-dashboard/README.md) | http://127.0.0.1:8510 | Fetch merch reports, suggest an editable OpenRouter reply, and email the reporter after review. |
| Feature suggestion dashboard | [feature-suggestion-dashboard](feature-suggestion-dashboard/README.md) | http://127.0.0.1:8511 | Fetch suggestions, summarize all by module, and send to configured Slack channels or PMs. |
| Full Dashboard | [full-dashboard](full-dashboard/README.md) | http://127.0.0.1:8508 | Preserved earlier React/Python support workbench; actions remain dry-run. |

## Get started

```sh
git clone https://github.com/YashGargIND/matiks-support-agent.git
cd matiks-support-agent
```

For either focused dashboard, use Node.js 22 or newer:

```sh
cd merch-dashboard # or feature-suggestion-dashboard
npm ci
cp .env.example .env.local
# Fill your authorized credentials in .env.local.
npm run dev
```

The focused apps use only Next.js API routes for ClickUp, OpenRouter and email/Slack requests. They do not require the Agents SDK or the full dashboard. Follow each app README for credentials, routing and verification. Do not commit populated environment files, source exports, local caches or send receipts. A fresh clone needs its own credentials and Slack routing; report data is not checked in.

For the preserved Full Dashboard:

```sh
cd full-dashboard
make setup
make dev
```

Full-fetch checks, synthetic OpenRouter requests and Gmail SMTP authentication have passed on the owner's machine. Actual email delivery, actual Slack delivery and final browser acceptance remain human-testing steps. A missing Slack token or destination is shown explicitly. The preserved full dashboard has a separate scope and validation history in its README.

## Team checks

Run `npm test` and `npm run build` inside the focused app you change. Run `make check` inside `full-dashboard` for that app. GitHub Actions checks all three folders without provider credentials or outbound messages.

[Private progress page](https://matiks-support-progress.yashgarg.chatgpt.site)
