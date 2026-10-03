import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { GET as getTickets } from "../app/api/tickets/route";
import { GET as getConfig, PUT as putConfig } from "../app/api/config/route";
import { POST as createSummary } from "../app/api/summaries/route";
import { POST as sendSummary } from "../app/api/runs/[id]/send/route";
const nativeFetch = globalThis.fetch;
let directory = "";
const req = (path: string, method = "GET", body?: unknown) =>
  new Request(`http://127.0.0.1:8511/api/${path}`, {
    method,
    headers: {
      Origin: "http://127.0.0.1:8511",
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "feature-route-test-"));
  process.env.FEATURE_DATA_DIR = directory;
  process.env.CLICKUP_API_TOKEN = "test";
  process.env.CLICKUP_LIST_ID = "999";
  process.env.OPENROUTER_API_KEY = "test";
  delete process.env.SLACK_BOT_TOKEN;
});
afterEach(async () => {
  globalThis.fetch = nativeFetch;
  await rm(directory, { recursive: true, force: true });
  delete process.env.FEATURE_DATA_DIR;
});
test("real configuration handler saves validated routes without exposing secret values", async () => {
  let response = await getConfig(req("config"));
  const initial = await response.json();
  assert.equal(initial.credentials.slack, false);
  assert.ok(!JSON.stringify(initial).includes("test"));
  const config = {
    modules: [
      { id: "other", name: "Product", keywords: [], destination: "C12345678" },
    ],
  };
  response = await putConfig(req("config", "PUT", config));
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).config, config);
  response = await putConfig(req("config", "PUT", { modules: [] }));
  assert.equal(response.status, 400);
});
test("actual Next tickets and summary handlers fetch complete data and save preview", async () => {
  await putConfig(
    req("config", "PUT", {
      modules: [
        { id: "other", name: "Product", keywords: [], destination: "" },
      ],
    }),
  );
  let reads = 0;
  let models = 0;
  globalThis.fetch = (async (input) => {
    if (String(input).includes("clickup.com")) {
      reads++;
      return Response.json({
        tasks: [
          {
            id: "suggestion1",
            name: "Suggestion: dark mode",
            description: "Dark theme please",
            date_created: "1",
          },
          { id: "bug1", name: "Crash" },
        ],
        last_page: true,
      });
    }
    if (String(input).includes("openrouter.ai")) {
      models++;
      return Response.json({
        choices: [
          {
            message: {
              content: JSON.stringify({
                groups: [
                  {
                    moduleId: "other",
                    summary: "Add an optional dark theme.",
                    ticketIds: ["suggestion1"],
                  },
                ],
              }),
            },
          },
        ],
      });
    }
    throw new Error("Unexpected provider");
  }) as typeof fetch;
  let response = await getTickets(req("tickets?refresh=true"));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).tickets.length, 1);
  response = await createSummary(req("summaries", "POST", { send: false }));
  assert.equal(response.status, 200);
  const run = await response.json();
  assert.equal(run.totalTickets, 1);
  assert.equal(run.deliveries.other.state, "unsent");
  assert.equal(reads, 1);
  assert.equal(models, 1);
  response = await sendSummary(req(`runs/${run.id}/send`, "POST", {}), {
    params: Promise.resolve({ id: run.id }),
  });
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /SLACK_BOT_TOKEN/);
});
test("send-all route fails before model/read calls when Slack is missing", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls++;
    throw new Error("should not call");
  }) as typeof fetch;
  const response = await createSummary(
    req("summaries", "POST", { send: true }),
  );
  assert.equal(response.status, 400);
  assert.equal(calls, 0);
});
test("actual endpoint rejects cross-origin configuration mutation", async () => {
  const response = await putConfig(
    new Request("http://127.0.0.1:8511/api/config", {
      method: "PUT",
      headers: { Origin: "https://foreign.example" },
      body: "{}",
    }),
  );
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /Cross-origin/);
});
