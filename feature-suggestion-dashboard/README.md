# Matiks feature requests

A standalone Next.js dashboard. ClickUp, OpenRouter and Slack requests run only in Next.js route handlers. No dependency on the existing Python app or Agents SDK.

## Run locally

1. Install Node.js 20.9 or newer and run `npm ci` in this folder.
2. Copy `.env.example` to `.env.local`, add the ClickUp and OpenRouter credentials, and add a Slack bot token when ready to send.
3. Run `npm run dev` and open http://127.0.0.1:8511.

Secrets stay on the server. `.env.local` and `data/` are ignored by Git. This is a local dashboard, bound to localhost; do not expose it publicly without adding authentication.

## Use

Refresh reports fetches every page in the configured ClickUp list, including closed tasks and subtasks, with no date cutoff. Feature requests are selected using the verified Suggestion dropdown field or an explicit `Suggestion:` / `Feature request:` title. For a different list, set its topic field and suggestion option IDs. Unrelated fields, task creators and incidental text are not used to infer a suggestion. A failed page aborts the complete fetch; partial results are never summarized. Complete snapshots are reused for five minutes, and Refresh forces a new snapshot.

Edit module names, keywords and Slack destinations, then save routing. Use channel IDs (`C…` or `G…`) or PM user IDs (`U…`), not display names. Blank destinations stay unconfigured. The bot needs `chat:write`; PM DMs also need `im:write`. Invite it to the target channels. Module labels in the list use keyword matching; OpenRouter performs the final grouping.

Preview summaries covers **all** fetched suggestions, regardless of the visible search/module filter. Summarize and send creates the same complete summary and sends to configured destinations. Preview is available without a Slack token. The dashboard reports each destination’s real success or failure, and never labels unconfigured destinations as sent.

Slack messages include the complete module summary and coverage count, plus ten example report links; every covered report ID remains visible in the saved dashboard preview. This avoids filling Slack’s message limit with thousands of links. Module summaries that exceed Slack’s message limit fail explicitly and are not silently shortened.

Inputs are chunked into at most 96,000 serialized characters without truncating report text, with three independent model calls at a time. Every report must appear exactly once in a known module or the operation fails before sending. Large datasets retain separate batch summaries within each module, rather than silently dropping ideas; exceptionally long single reports fail with a clear message. Summaries and routing snapshots are saved locally. Identical report/config/model snapshots reuse a saved summary, and successful Slack sends are skipped on retries. Timeout/uncertain delivery is blocked from automatic retry and requires checking Slack manually. A process crash can leave a lock or `sending` state: check Slack before manually recovering the corresponding files in `data/`.

Routing changes apply to newly generated summaries; saved previews keep their original destinations. Contact email/phone patterns are removed before sending text to OpenRouter, but free-form descriptions may contain other personal details. No model request is made until a human clicks a summary button. No scheduled sends.

## Verify

`npm test` tests full pagination, filtering, coverage, model validation, Slack partial failure, duplicate prevention and local request restrictions. `npm run build` builds the actual route handlers and dashboard. Provider tests mock network calls and send no real Slack messages.

Optional live provider check: `node --import tsx scripts/openrouter-smoke.ts` makes one OpenRouter call with two fictional suggestions and verifies complete module grouping. It uses the app's private environment, saves temporary output outside the project, and sends no Slack messages. This is separate from the offline test suite.

Provider contracts: [Next route handlers](https://nextjs.org/docs/app/getting-started/route-handlers), [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [Slack messages](https://api.slack.com/methods/chat.postMessage), [Slack DMs](https://docs.slack.dev/reference/methods/conversations.open/).
