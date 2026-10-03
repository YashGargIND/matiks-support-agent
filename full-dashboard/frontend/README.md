# Matiks Support dashboard

React + TypeScript dashboard for the local support API, using the actual Matiks logo, local Nunito Sans and lime brand token. Real metrics and evidence come from /ui endpoints.

Start the API on 127.0.0.1:8517, then:

```sh
cd /Users/yashgarg/code/matiks-support-agent/frontend
npm install
npm run dev
```

Open http://127.0.0.1:8508/. Existing Streamlit on 8507 is separate. Vite proxies /ui, /health and /openapi.json to the local API and binds only to localhost.

```sh
npm run api:types  # refresh generated OpenAPI types after API changes
npm run build     # TypeScript checks and production bundle
```

The bundle is in dist/. No external deployment is configured.

Safe mode stays visible. Replies and internal actions have separate named local approvals. Synthetic examples are labelled and excluded from real metrics. Secret values are never returned. Unsupported adapters and bulk approval are disabled based on current API registry/safeguards.

See design/plan.txt and design/fidelity-ledger.txt for decisions, concept references, browser observations and verification limits. Final screenshots are in design/.
