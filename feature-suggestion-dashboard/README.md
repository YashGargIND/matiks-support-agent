# Matiks feature requests

A standalone Next.js dashboard. ClickUp, OpenRouter and Slack requests run only in Next.js route handlers. No dependency on the existing Python app or Agents SDK.

## Run locally

1. Install Node.js 20.9 or newer and run `npm ci` in this folder.
2. Copy `.env.example` to `.env.local`, add the ClickUp and OpenRouter credentials, and add a Slack bot token when ready to send.
3. Run `npm run dev` and open http://127.0.0.1:8511.

Secrets stay on the server. `.env.local` and `data/` are ignored by Git. This is a local dashboard, bound to localhost; do not expose it publicly without adding authentication.

## Use

For a quick **preview-only** demo, open http://127.0.0.1:8511/?demo=1. It reads the newest complete saved ClickUp snapshot locally, selects the latest 20 suggestions by date and report ID, and clearly shows the sample size, full source count and cached snapshot time. Click **Preview demo** for one bounded summary batch. The normal all-report job and its saved pointer remain separate. Refresh reconnects to the saved demo preview without starting a new model call or Slack send. Slack send controls are hidden, and the server rejects sending stored demo runs. If no complete snapshot exists, first refresh reports in the normal dashboard. The sample is real cached data, not fictional fixtures or a partial live page fetch.

Refresh reports fetches every page in the configured ClickUp list, including closed tasks and subtasks, with no date cutoff. Feature requests are selected using the verified Suggestion dropdown field or an explicit `Suggestion:` / `Feature request:` title. For a different list, set its topic field and suggestion option IDs. Unrelated fields, task creators and incidental text are not used to infer a suggestion. A failed page aborts the complete fetch; partial results are never summarized. Complete snapshots are reused for five minutes, and Refresh forces a new snapshot.

Edit module names, keywords and Slack destinations, then save routing. Use channel IDs (`C…` or `G…`) or PM user IDs (`U…`), not display names. Blank destinations stay unconfigured. The bot needs `chat:write`; PM DMs also need `im:write`. Invite it to the target channels. Module labels in the list use keyword matching; OpenRouter performs the final grouping.

Preview summaries covers **all** fetched suggestions, regardless of the visible search/module filter. Summarize and send creates the same complete summary and sends to configured destinations. Preview is available without a Slack token. The dashboard reports each destination’s real success or failure, and never labels unconfigured destinations as sent.

Slack messages include the complete module summary and coverage count, plus ten example report links; every covered report ID remains visible in the saved dashboard preview. This avoids filling Slack’s message limit with thousands of links. Module summaries that exceed Slack’s message limit fail explicitly and are not silently shortened.

Summary buttons return immediately with a saved job. The dashboard polls its fetch, batch and delivery progress; refreshing reconnects to the same job without starting another model request or send. Jobs run through Next.js `after()` in the local server process, so keep that process running. There is no external worker or queue. A restarted server marks unfinished jobs interrupted; use **Retry saved job** to resume explicitly with the original routing and send intent.

Inputs are chunked into at most 24,000 serialized characters and 60 reports per batch without truncating report text, with three independent model calls at a time. A provider timeout stops the job with a useful error. Successful batches are saved immediately, so retries only pay for missing batches and reuse the original complete ClickUp snapshot. Every report must appear exactly once in a known module or the operation fails before sending. Large datasets retain separate batch summaries within each module, rather than silently dropping ideas; exceptionally long single reports fail with a clear message. Summaries and routing snapshots are saved locally. Identical report/config/model snapshots reuse a saved summary, and successful Slack sends are skipped on retries. Timeout/uncertain Slack delivery is blocked from automatic retry and requires checking Slack manually. Dead-process locks are reclaimed on explicit retry; live locks are preserved. A process crash during Slack sending can leave a `sending` state: check Slack before manually recovering that uncertain delivery in `data/`.

The model receives short batch references (`r1`, `r2`, etc.) rather than long ClickUp IDs. The server maps references back to real report IDs and validates that every report appears exactly once. Invalid coverage or a summary above 800 characters gets one repair attempt for that batch. A second invalid response stops the job with an explicit nothing-sent error. Model request counts include repair and retry attempts; successful checkpoints are not regenerated.

Routing changes apply to newly generated summaries; saved previews keep their original destinations. Contact email/phone patterns are removed before sending text to OpenRouter, but free-form descriptions may contain other personal details. No model request is made until a human clicks a summary button. No scheduled sends.

## Verify

`npm test` tests full pagination, filtering, exact coverage, immediate job acceptance, status polling, browser refresh/abort, restart recovery, checkpoint reuse after provider timeout, live/dead process locks, Slack partial failure, duplicate prevention and local request restrictions. `npm run build` builds the actual route handlers and dashboard. Provider tests mock network calls and send no real Slack messages.

Optional live provider check: `node --import tsx scripts/openrouter-smoke.ts` makes one OpenRouter call with two fictional suggestions and verifies complete module grouping. It uses the app's private environment, saves temporary output outside the project, and sends no Slack messages. This is separate from the offline test suite.

Provider contracts: [Next route handlers](https://nextjs.org/docs/app/getting-started/route-handlers), [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [Slack messages](https://api.slack.com/methods/chat.postMessage), [Slack DMs](https://docs.slack.dev/reference/methods/conversations.open/).
