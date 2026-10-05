import { test, beforeEach, afterEach, mock } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import nextServer from "next/server";
import { GET, POST } from "../app/api/demo/route";
import { acceptJob, getJob, latestJob } from "../lib/jobs";
import { saveJson, getRun } from "../lib/storage";
import { newestDemoTickets } from "../lib/demo";
import { sendRun } from "../lib/slack";
import { jobProgress } from "../lib/job-view";
import type { Ticket } from "../lib/types";
let directory = "";
let scheduled: (() => Promise<void>)[] = [];
const originalFetch = globalThis.fetch;
const sourceId = "a".repeat(64);
const tickets: Ticket[] = Array.from({ length: 35 }, (_, i) => ({
  id: `report-${String(i).padStart(2, "0")}`,
  title: "Suggestion: fictional feature",
  body: "Fictional request for offline lessons.",
  createdAt: new Date(i * 1000).toISOString(),
  status: "test",
  url: "",
}));
const request = (body?: unknown) =>
  new Request("http://127.0.0.1:8511/api/demo", {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Origin: "http://127.0.0.1:8511",
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "feature-demo-"));
  process.env.FEATURE_DATA_DIR = directory;
  process.env.OPENROUTER_API_KEY = "test";
  process.env.SLACK_BOT_TOKEN = "test";
  scheduled = [];
  mock.method(nextServer, "after", (work: () => Promise<void>) =>
    scheduled.push(work),
  );
  await saveJson(`job-tickets-${sourceId}.json`, {
    tickets,
    complete: true,
    pages: 2,
    fetchedTasks: 100,
    fetchedAt: "2026-10-05T09:00:00Z",
  });
});
afterEach(async () => {
  mock.restoreAll();
  globalThis.fetch = originalFetch;
  await rm(directory, { recursive: true, force: true });
  delete process.env.FEATURE_DATA_DIR;
});
test("newest20 selection is deterministic, includes date/ID tie-break and leaves source untouched", () => {
  const original = JSON.stringify(tickets);
  const selected = newestDemoTickets(tickets);
  assert.equal(selected.length, 20);
  assert.equal(selected[0].id, "report-34");
  assert.equal(selected.at(-1)!.id, "report-15");
  assert.equal(JSON.stringify(tickets), original);
  const tied = [
    { ...tickets[0], id: "a" },
    { ...tickets[0], id: "b" },
  ];
  assert.equal(newestDemoTickets(tied)[0].id, "b");
});
test("GET serves honest cached subset without provider calls or starting/resuming jobs", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls++;
    throw new Error("must not fetch");
  }) as typeof fetch;
  const response = await GET(request());
  const data = await response.json();
  assert.equal(response.status, 200);
  assert.equal(data.tickets.length, 20);
  assert.equal(data.sourceTickets, 35);
  assert.equal(data.scope, "demo");
  assert.equal(data.snapshotAt, "2026-10-05T09:00:00Z");
  assert.equal(data.job, null);
  assert.equal(calls, 0);
  assert.equal(scheduled.length, 0);
});
test("demo job is preview-only, one batch, separate from active normal all-report job", async () => {
  const normal = await acceptJob(false);
  const normalId = normal.job.id;
  let calls = 0;
  globalThis.fetch = (async (input, init) => {
    calls++;
    assert.ok(String(input).includes("openrouter.ai"));
    const reports = JSON.parse(
      JSON.parse(String(init?.body)).messages[1].content,
    ).reports;
    assert.equal(reports.length, 20);
    return Response.json({
      choices: [
        {
          message: {
            content: JSON.stringify({
              groups: [
                {
                  moduleId: "other",
                  summary: "Users request offline learning.",
                  ticketIds: reports.map((r: { id: string }) => r.id),
                },
              ],
            }),
          },
        },
      ],
    });
  }) as typeof fetch;
  const response = await POST(request({ send: false }));
  const accepted = await response.json();
  assert.equal(response.status, 202);
  assert.equal(accepted.job.scope, "demo");
  assert.equal(accepted.job.send, false);
  assert.notEqual(accepted.job.id, normalId);
  assert.equal((await latestJob())!.id, normalId);
  await scheduled[0]();
  const job = await getJob(accepted.job.id);
  assert.equal(job.status, "done");
  assert.equal(job.totalTickets, 20);
  assert.equal(job.sourceTickets, 35);
  assert.equal(job.totalBatches, 1);
  assert.equal(calls, 1);
  assert.equal(job.run!.scope, "demo");
  assert.equal((await getRun(job.run!.id)).scope, "demo");
  assert.match(jobProgress(job), /20 of 35/);
  assert.equal((await latestJob())!.id, normalId);
  const restored = await GET(request());
  const data = await restored.json();
  assert.equal(data.job.id, job.id);
  assert.equal(data.sourceTickets, 35);
  assert.equal(scheduled.length, 1);
  assert.equal(calls, 1);
  await assert.rejects(
    sendRun(job.run!.id, (async () => {
      throw new Error("must not send");
    }) as typeof fetch),
    /cannot be sent to Slack/,
  );
  assert.equal(calls, 1);
});
test("demo rejects Slack send intent and does not create jobs", async () => {
  const response = await POST(request({ send: true }));
  assert.equal(response.status, 400);
  assert.equal(scheduled.length, 0);
  assert.equal(await latestJob("demo"), null);
});
test("demo requires complete snapshot and never falls back to partial ClickUp pages", async () => {
  await rm(join(directory, `job-tickets-${sourceId}.json`));
  await saveJson(`job-tickets-${"b".repeat(64)}.json`, {
    tickets,
    complete: false,
    pages: 1,
    fetchedTasks: 35,
  });
  const response = await GET(request());
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /No complete cached snapshot/);
  assert.equal(scheduled.length, 0);
});
