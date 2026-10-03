# Matiks merch dashboard

Independent Next.js app. ClickUp fetching, OpenRouter drafting and Google email sending happen only in Next.js API routes. No Agents SDK, Python service or existing dashboard dependency.

## Run

```sh
cd merch-dashboard
npm ci
cp .env.example .env.local
# Fill the server-side credentials in .env.local.
npm run dev
```

Open http://127.0.0.1:8510. The original dashboard stays untouched.

## Use

1. Wait for all ClickUp pages to load. The first fetch includes all statuses and can take a minute or more for a large list. Completed snapshots are cached for five minutes; Refresh explicitly refetches. Concurrent refreshes share one fetch.
2. Search or filter status locally. Merch keywords cover tshirts, shirts, hoodies, cake and physical rewards. Explicit suggestion tickets are excluded. Keyword filtering is deliberately simple; ambiguous wording may need adjustment.
3. Select a report. Optionally enter **verified** operator details. Suggest reply uses OpenRouter and redacts known names, email addresses, links and long numbers. Free-form text can still contain unidentified personal data, so keep operator notes factual and minimal.
4. Edit the draft, check the recipient and tick the review box. **Send email sends a real email** to the verified reporter custom field through Gmail SMTP OAuth, never to the task creator. Copy reply is available independently.

ClickUp uses GET only and its tasks are not modified. Reporter email mapping defaults only for the verified Matiks feedback list; other lists require CLICKUP_EMAIL_FIELD_ID. Google SMTP authenticates over TLS on port 465 using the existing OAuth refresh grant with full https://mail.google.com/ scope. It does not require Gmail API to be enabled. The configured IMAP_USER must match the OAuth account; AUTH verifies that before sending. Readiness uses AUTH/QUIT only and never sends a message. Emails count as sent only when Google SMTP acknowledges acceptance of the verified reporter recipient. This is provider acceptance, not proof of delivery or reading.

Send receipts are private local files in ignored .data/. Idempotency prevents automatic retries/double-click duplicates for the same request key, including after process restarts. An interrupted send is blocked until you check Gmail Sent. Selecting another report or regenerating a draft creates a new request, so operators must check previous send status before manually starting another attempt. Local routes reject cross-origin requests; this app binds localhost and is not an authenticated public deployment.

`npm test` mocks provider boundaries and never sends a real email. `npm run build` checks the production app. Credentials remain in ignored .env.local; never commit that file.

## Design fidelity

- White canvas, black type and lime #B1FA63 primary actions match design/concept.png.
- Simple brand header plus Refresh reports; no old navigation dashboard.
- Search/status toolbar above a 42% list / 58% selected-report pane.
- Selected row has a pale green background and lime left border.
- Original report, operator notes, editable reply and Copy/Send actions maintain the intended order.

Actual source, status, dates, report counts and recipients come from ClickUp. Review checkbox, missing credentials and provider errors are functional additions; no fictional reports or promise-filled example replies are inserted.
