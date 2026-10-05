import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fetchSuggestions, isSuggestion } from "../lib/clickup";
import { validateCoverage, summarize } from "../lib/summarize";
import { sendRun } from "../lib/slack";
import { getRun, saveRun } from "../lib/storage";
import { configSchema } from "../lib/config";
import { requireLocalRequest } from "../lib/http";
import type { Config, Run, Ticket } from "../lib/types";
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
const config: Config = {
  modules: [
    { id: "feed", name: "Feed", keywords: ["feed"], destination: "C12345678" },
    { id: "other", name: "Other", keywords: [], destination: "U12345678" },
  ],
};
const tickets: Ticket[] = [
  {
    id: "a",
    title: "Suggestion: hide posts",
    body: "Hide feed posts",
    createdAt: "",
    status: "open",
    url: "https://app.clickup.com/t/a",
  },
  {
    id: "b",
    title: "Suggestion: custom sound",
    body: "Optional sound",
    createdAt: "",
    status: "closed",
    url: "https://app.clickup.com/t/b",
  },
];
let directory = "";
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "matiks-feature-test-"));
  process.env.FEATURE_DATA_DIR = directory;
  process.env.CLICKUP_API_TOKEN = "test-clickup";
  process.env.CLICKUP_LIST_ID = "901611930428";
  process.env.OPENROUTER_API_KEY = "test-openrouter";
  process.env.SLACK_BOT_TOKEN = "test-slack";
  delete process.env.CLICKUP_TOPIC_FIELD_ID;
  delete process.env.CLICKUP_SUGGESTION_OPTION;
});
afterEach(async () => {
  await rm(directory, { recursive: true, force: true });
  delete process.env.FEATURE_DATA_DIR;
});
test("Suggestion dropdown uses verified field, creator/title unrelated data is ignored", () => {
  assert.equal(
    isSuggestion({
      id: "1",
      name: "Merch",
      custom_fields: [{ id: "a5e3ce45-2379-4f5d-945b-b2dc9db92917", value: 1 }],
    }),
    true,
  );
  assert.equal(
    isSuggestion({
      id: "2",
      name: "Bug",
      custom_fields: [{ id: "unrelated", value: 1 }],
    }),
    false,
  );
  assert.equal(
    isSuggestion({ id: "3", name: "Feature request: sounds" }),
    true,
  );
  assert.equal(
    isSuggestion({ id: "4", name: "I have a suggestion", custom_fields: [] }),
    false,
  );
});
test("fetches every page including closed tasks and deduplicates report IDs", async () => {
  let calls = 0;
  const urls: string[] = [];
  const result = await fetchSuggestions((async (input) => {
    const url = String(input);
    urls.push(url);
    const page = new URL(url).searchParams.get("page");
    calls++;
    return response(
      page === "0"
        ? {
            tasks: [{ id: "a", name: "Suggestion: feed", date_created: "1" }],
            last_page: false,
          }
        : {
            tasks: [
              { id: "a", name: "Suggestion: feed", date_created: "1" },
              { id: "b", name: "Suggestion: sounds", date_created: "2" },
              { id: "bug", name: "Crash" },
            ],
            last_page: true,
          },
    );
  }) as typeof fetch);
  assert.equal(calls, 2);
  assert.equal(result.fetchedTasks, 3);
  assert.equal(result.tickets.length, 2);
  assert.ok(
    urls.every(
      (u) => u.includes("include_closed=true") && !u.includes("date_created"),
    ),
  );
  assert.equal(result.complete, true);
});
test("pagination failure and repeated pages cannot produce partial summaries", async () => {
  let calls = 0;
  await assert.rejects(
    fetchSuggestions((async () =>
      ++calls === 1
        ? response({
            tasks: [{ id: "a", name: "Suggestion: x" }],
            last_page: false,
          })
        : response({}, 429)) as typeof fetch),
    /429/,
  );
  await assert.rejects(
    fetchSuggestions((async () =>
      response({ tasks: [{ id: "a" }], last_page: false })) as typeof fetch),
    /repeated a page/,
  );
});
test("429 reset retries the same page without losing reports", async () => {
  let calls = 0;
  const pages: string[] = [];
  const result = await fetchSuggestions((async (input) => {
    pages.push(new URL(String(input)).searchParams.get("page") || "");
    calls++;
    if (calls === 1)
      return new Response("{}", {
        status: 429,
        headers: { "X-RateLimit-Reset": String(Math.floor(Date.now() / 1000)) },
      });
    return response({
      tasks: [{ id: "a", name: "Suggestion: sound", date_created: "1" }],
      last_page: true,
    });
  }) as typeof fetch);
  assert.deepEqual(pages, ["0", "0"]);
  assert.equal(result.tickets.length, 1);
});
test("coverage rejects missing, duplicate, invented and unknown module assignments", () => {
  const valid = {
    groups: [
      { moduleId: "feed", summary: "One idea", ticketIds: ["a"] },
      { moduleId: "other", summary: "Other idea", ticketIds: ["b"] },
    ],
  };
  assert.equal(validateCoverage(valid, tickets, config).length, 2);
  for (const value of [
    { groups: [valid.groups[0]] },
    {
      groups: [
        ...valid.groups,
        { moduleId: "other", summary: "Again", ticketIds: ["a"] },
      ],
    },
    {
      groups: [{ moduleId: "invented", summary: "Bad", ticketIds: ["a", "b"] }],
    },
    {
      groups: [{ moduleId: "feed", summary: "Bad", ticketIds: ["a", "fake"] }],
    },
  ])
    assert.throws(() => validateCoverage(value, tickets, config));
});
test("structured OpenRouter request covers input and identical preview is cached", async () => {
  let calls = 0;
  const fake = (async (_url, init) => {
    calls++;
    const body = JSON.parse(String(init?.body));
    assert.equal(body.response_format.type, "json_schema");
    assert.ok(body.messages[0].content.includes("untrusted"));
    return response({
      choices: [
        {
          message: {
            content: JSON.stringify({
              groups: [
                {
                  moduleId: "feed",
                  summary: "Hide unwanted posts.",
                  ticketIds: ["a"],
                },
                {
                  moduleId: "other",
                  summary: "Optional sound.",
                  ticketIds: ["b"],
                },
              ],
            }),
          },
        },
      ],
    });
  }) as typeof fetch;
  const run = await summarize(tickets, config, 10, fake);
  assert.equal(run.totalTickets, 2);
  assert.equal(run.modelCalls, 1);
  assert.equal((await summarize(tickets, config, 10, fake)).id, run.id);
  assert.equal(calls, 1);
});
test("oversized report fails before any model call instead of truncating", async () => {
  let calls = 0;
  await assert.rejects(
    summarize(
      [{ ...tickets[0], body: "x".repeat(25000) }],
      config,
      1,
      (async () => {
        calls++;
        return response({});
      }) as typeof fetch,
    ),
    /too long/,
  );
  assert.equal(calls, 0);
});
test("bounded batches retain every report and complete module summaries", async () => {
  const longTickets = ["a", "b", "c", "d", "e", "f"].map((id) => ({
    ...tickets[0],
    id,
    body: "x".repeat(18000),
  }));
  let calls = 0;
  const fake = (async (_url, init) => {
    calls++;
    const input = JSON.parse(String(init?.body));
    const reports = JSON.parse(input.messages[1].content).reports;
    assert.ok(reports.length >= 1 && reports.length <= 5);
    assert.equal(reports[0].body.length, 18000);
    return response({
      choices: [
        {
          message: {
            content: JSON.stringify({
              groups: [
                {
                  moduleId: "other",
                  summary: `Idea ${reports[0].id}`,
                  ticketIds: reports.map((report: Ticket) => report.id),
                },
              ],
            }),
          },
        },
      ],
    });
  }) as typeof fetch;
  const run = await summarize(longTickets, config, 6, fake);
  assert.equal(calls, 2);
  assert.equal(run.modelCalls, 2);
  assert.deepEqual(run.summaries[0].ticketIds, ["a", "b", "c", "d", "e", "f"]);
  assert.equal(run.summaries[0].summary, "Idea a\n\nIdea f");
});
function fixture(): Run {
  return {
    id: "a".repeat(64),
    createdAt: "2026-10-03T00:00:00Z",
    totalTickets: 2,
    fetchedTasks: 2,
    modelCalls: 1,
    config,
    summaries: [
      {
        moduleId: "feed",
        summary: "Hide posts <@U12345678>.",
        ticketIds: ["a"],
      },
      { moduleId: "other", summary: "Add sound.", ticketIds: ["b"] },
    ],
    deliveries: {
      feed: { state: "unsent", destination: "C12345678" },
      other: { state: "unsent", destination: "U12345678" },
    },
  };
}
test("summary requests run with at most three concurrent batches", async () => {
  const many = Array.from({ length: 22 }, (_, index) => ({
    ...tickets[0],
    id: `ticket-${index}`,
    body: "x".repeat(18000),
  }));
  let active = 0;
  let peak = 0;
  let calls = 0;
  const fake = (async (_url, init) => {
    active++;
    calls++;
    peak = Math.max(peak, active);
    const input = JSON.parse(String(init?.body));
    const reports = JSON.parse(input.messages[1].content).reports;
    await new Promise((resolve) => setTimeout(resolve, 10));
    active--;
    return response({
      choices: [
        {
          message: {
            content: JSON.stringify({
              groups: [
                {
                  moduleId: "other",
                  summary: "Requested improvements.",
                  ticketIds: reports.map((report: Ticket) => report.id),
                },
              ],
            }),
          },
        },
      ],
    });
  }) as typeof fetch;
  const run = await summarize(many, config, 22, fake);
  assert.equal(peak, 3);
  assert.equal(calls, 5);
  assert.equal(run.summaries.flatMap((group) => group.ticketIds).length, 22);
});
test("Slack partial failure is persisted and retry skips successful module", async () => {
  await saveRun(fixture());
  let posts = 0;
  const fake = (async (input, init) => {
    const body = JSON.parse(String(init?.body));
    if (String(input).endsWith("conversations.open"))
      return response({ ok: true, channel: { id: "D12345678" } });
    posts++;
    assert.ok(!body.text.includes("<@"));
    return response(
      body.channel === "C12345678"
        ? { ok: true, ts: "1.2" }
        : { ok: false, error: "not_in_channel" },
    );
  }) as typeof fetch;
  let run = await sendRun("a".repeat(64), fake);
  assert.equal(run.deliveries.feed.state, "sent");
  assert.equal(run.deliveries.other.state, "failed");
  run = await sendRun(run.id, fake);
  assert.equal(posts, 3);
  assert.equal((await getRun(run.id)).deliveries.feed.state, "sent");
});
test("large coverage keeps all IDs saved while Slack gets clearly labelled example links", async () => {
  const run = fixture();
  run.summaries = [
    {
      moduleId: "feed",
      summary: "Requested feed improvements.",
      ticketIds: Array.from({ length: 2000 }, (_, index) => `report-${index}`),
    },
  ];
  run.totalTickets = 2000;
  await saveRun(run);
  const result = await sendRun(run.id, (async (_url, init) => {
    const message = JSON.parse(String(init?.body));
    assert.match(message.text, /2000 suggestions covered/);
    assert.match(message.text, /Example reports \(10 of 2000/);
    assert.equal(
      (message.text.match(/https:\/\/app\.clickup\.com/g) || []).length,
      10,
    );
    assert.ok(message.text.length < 39000);
    return response({ ok: true, ts: "2.3" });
  }) as typeof fetch);
  assert.equal(result.deliveries.feed.state, "sent");
  assert.equal((await getRun(run.id)).summaries[0].ticketIds.length, 2000);
});
test("ambiguous Slack delivery is never retried automatically", async () => {
  const run = fixture();
  run.deliveries.other.destination = "";
  await saveRun(run);
  let calls = 0;
  const fake = (async () => {
    calls++;
    throw new Error("timeout");
  }) as typeof fetch;
  const result = await sendRun(run.id, fake);
  assert.equal(result.deliveries.feed.state, "unknown");
  assert.equal(result.deliveries.other.state, "unconfigured");
  await sendRun(run.id, fake);
  assert.equal(calls, 1);
});
test("Slack success without a receipt remains uncertain and cannot duplicate", async () => {
  const run = fixture();
  run.deliveries.other.destination = "";
  await saveRun(run);
  let calls = 0;
  const fake = (async () => {
    calls++;
    return response({ ok: true });
  }) as typeof fetch;
  const result = await sendRun(run.id, fake);
  assert.equal(result.deliveries.feed.state, "unknown");
  await sendRun(run.id, fake);
  assert.equal(calls, 1);
});
test("no Slack token blocks sending before provider calls", async () => {
  delete process.env.SLACK_BOT_TOKEN;
  let calls = 0;
  await assert.rejects(
    sendRun("a".repeat(64), (async () => {
      calls++;
      return response({});
    }) as typeof fetch),
    /SLACK_BOT_TOKEN/,
  );
  assert.equal(calls, 0);
});
test("configuration accepts only explicit Slack IDs and unique modules", () => {
  assert.deepEqual(configSchema.parse(config), config);
  assert.throws(() =>
    configSchema.parse({
      modules: [{ ...config.modules[0], destination: "fake-pm" }],
    }),
  );
  assert.throws(() =>
    configSchema.parse({ modules: [config.modules[0], config.modules[0]] }),
  );
});
test("local endpoints reject foreign origins and hosts", () => {
  requireLocalRequest(
    new Request("http://localhost:8511/api/config", {
      headers: { Origin: "http://localhost:8511" },
    }),
  );
  assert.throws(() =>
    requireLocalRequest(
      new Request("http://localhost:8511/api/config", {
        headers: { Origin: "https://evil.example" },
      }),
    ),
  );
  assert.throws(() =>
    requireLocalRequest(new Request("https://public.example/api/config")),
  );
});

 test("Next loopback normalization preserves real Host origin checks", () => {
   const url = "http://localhost:8510/api/reply";
   requireLocalRequest(new Request(url, {headers: {Host: "127.0.0.1:8510", Origin: "http://127.0.0.1:8510"}}));
   requireLocalRequest(new Request(url, {headers: {Host: "localhost:8510", Origin: "http://localhost:8510"}}));
   requireLocalRequest(new Request(url, {headers: {Host: "[::1]:8510", Origin: "http://[::1]:8510"}}));
   for (const headers of [
     {Host: "127.0.0.1:8510", Origin: "http://evil.example"},
     {Host: "127.0.0.1:8510", Origin: "http://localhost:8510"},
     {Host: "127.0.0.1:8510", Origin: "http://127.0.0.1:8511"},
     {Host: "evil.example:8510", Origin: "http://evil.example:8510"},
     {Host: "127.0.0.1:8510", Origin: "null"},
     {Host: "127.0.0.1:8511", Origin: "http://127.0.0.1:8511"},
     {Host: "127.0.0.1:8510", Origin: "http://evil.example", "x-forwarded-host": "evil.example:8510"},
   ]) assert.throws(() => requireLocalRequest(new Request(url, {headers: headers as Record<string, string>})));
 });
