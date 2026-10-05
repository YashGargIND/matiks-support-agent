import { fixtureResponse } from "./model-fixture";
import { test, beforeEach, afterEach, mock } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, readdir } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import nextServer from "next/server";
import {
  POST as createJobRoute,
  GET as latestRoute,
} from "../app/api/summaries/route";
import { GET as statusRoute } from "../app/api/jobs/[id]/route";
import { POST as retryRoute } from "../app/api/jobs/[id]/retry/route";
import { acceptJob, getJob, processJob, retryJob } from "../lib/jobs";
import { saveConfig, saveJson, readJson, withRunLock } from "../lib/storage";
import { summarize } from "../lib/summarize";
import { jobActive, jobProgress } from "../lib/job-view";
import type { Job, Ticket } from "../lib/types";
const config = {
  modules: [{ id: "other", name: "Other", keywords: [], destination: "" }],
};
const request = (path: string, body?: unknown) =>
  new Request(`http://127.0.0.1:8511/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Origin: "http://127.0.0.1:8511",
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
let directory = "";
let scheduled: (() => Promise<void>)[] = [];
const originalFetch = globalThis.fetch;
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "feature-job-"));
  process.env.FEATURE_DATA_DIR = directory;
  process.env.OPENROUTER_API_KEY = "test";
  process.env.CLICKUP_API_TOKEN = "test";
  process.env.CLICKUP_LIST_ID = "998";
  delete process.env.SLACK_BOT_TOKEN;
  scheduled = [];
  mock.method(nextServer, "after", (work: () => Promise<void>) =>
    scheduled.push(work),
  );
  await saveConfig(config);
});
afterEach(async () => {
  mock.restoreAll();
  globalThis.fetch = originalFetch;
  await rm(directory, { recursive: true, force: true });
  delete process.env.FEATURE_DATA_DIR;
});
function fakeProvider(): typeof fetch {
  return (async (input, init) => {
    if (String(input).includes("clickup.com"))
      return fixtureResponse({
        tasks: [
          {
            id: "a",
            name: "Suggestion: offline lessons",
            description: "Fictional lessons suggestion",
            date_created: "1",
          },
        ],
        last_page: true,
      });
    const data = JSON.parse(String(init?.body));
    const reports = JSON.parse(data.messages[1].content).reports;
    return fixtureResponse({
      choices: [
        {
          message: {
            content: JSON.stringify({
              groups: [
                {
                  moduleId: "other",
                  summary: "Requested product improvements.",
                  ticketIds: reports.map((r: Ticket) => r.id),
                },
              ],
            }),
          },
        },
      ],
    });
  }) as typeof fetch;
}
test("POST returns202 before reads/model calls and duplicate clicks schedule one job", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls++;
    throw new Error("not yet");
  }) as typeof fetch;
  const start = Date.now();
  const response = await createJobRoute(request("summaries", { send: false }));
  const { job } = await response.json();
  assert.equal(response.status, 202);
  assert.ok(Date.now() - start < 1000);
  assert.equal(job.status, "queued");
  assert.equal(calls, 0);
  assert.equal(scheduled.length, 1);
  assert.ok(!("owner" in job));
  const repeat = await createJobRoute(request("summaries", { send: false }));
  assert.equal((await repeat.json()).job.id, job.id);
  assert.equal(scheduled.length, 1);
  globalThis.fetch = fakeProvider();
  await scheduled[0]();
  assert.equal((await getJob(job.id)).status, "done");
});
test("request abort after acceptance does not cancel background work; refresh reads saved completion", async () => {
  globalThis.fetch = fakeProvider();
  const controller = new AbortController();
  const response = await createJobRoute(
    new Request("http://127.0.0.1:8511/api/summaries", {
      method: "POST",
      body: JSON.stringify({ send: false }),
      signal: controller.signal,
    }),
  );
  const { job } = await response.json();
  controller.abort();
  await scheduled[0]();
  const status = await statusRoute(request(`jobs/${job.id}`), {
    params: Promise.resolve({ id: job.id }),
  });
  const data = await status.json();
  assert.equal(data.job.status, "done");
  assert.equal(data.job.run.totalTickets, 1);
  assert.equal(data.job.completedBatches, data.job.totalBatches);
  assert.equal(data.job.run.deliveries.other.state, "unsent");
  const restored = await latestRoute(request("summaries"));
  assert.equal((await restored.json()).job.id, job.id);
  assert.equal(scheduled.length, 1);
});
test("failed provider is persisted as error and job status exposes completed batch count", async () => {
  const accepted = await acceptJob(false);
  const fake = (async (input) =>
    String(input).includes("clickup.com")
      ? fixtureResponse({
          tasks: [{ id: "a", name: "Suggestion: fake", date_created: "1" }],
          last_page: true,
        })
      : Promise.reject(
          new DOMException("timeout", "TimeoutError"),
        )) as typeof fetch;
  await processJob(accepted.job.id, fake);
  const job = await getJob(accepted.job.id);
  assert.equal(job.status, "error");
  assert.match(job.error!, /batch timed out/);
  assert.equal(job.totalTickets, 1);
  assert.equal(job.fetchedPages, 1);
  assert.equal(job.completedBatches, 0);
  assert.equal(job.totalBatches, 1);
  assert.equal(job.run, undefined);
});
test("restart marks saved running job interrupted; retry keeps config/send intent and checks credentials", async () => {
  process.env.SLACK_BOT_TOKEN = "test";
  const accepted = await acceptJob(true);
  const saved = {
    ...accepted.job,
    status: "summarizing",
    owner: "previous-server",
  } as Job;
  await saveJson(`job-${saved.id}.json`, saved);
  delete process.env.SLACK_BOT_TOKEN;
  const interrupted = await getJob(saved.id);
  assert.equal(interrupted.status, "interrupted");
  assert.equal(interrupted.send, true);
  await assert.rejects(retryJob(saved.id), /SLACK_BOT_TOKEN/);
  assert.equal((await getJob(saved.id)).status, "interrupted");
  process.env.SLACK_BOT_TOKEN = "test";
  const result = await retryRoute(request(`jobs/${saved.id}/retry`, {}), {
    params: Promise.resolve({ id: saved.id }),
  });
  assert.equal(result.status, 202);
  const { job } = await result.json();
  assert.equal(job.send, true);
  assert.deepEqual(job.config, config);
  assert.equal(job.status, "queued");
  assert.equal(scheduled.length, 1);
});
test("timeout retries only failed batch and never charges successful checkpoint batches again", async () => {
  const tickets = ["a", "b", "c"].map((id) => ({
    id,
    title: `Suggestion: ${id}`,
    body: "x".repeat(18000),
    createdAt: "",
    status: "test",
    url: "",
  }));
  let initialCalls = 0;
  const progress: number[] = [];
  const failOne = (async (_url, init) => {
    initialCalls++;
    const reports = JSON.parse(
      JSON.parse(String(init?.body)).messages[1].content,
    ).reports;
    if (reports[0].title === "Suggestion: b")
      throw new DOMException("timeout", "TimeoutError");
    return fixtureResponse({
      choices: [
        {
          message: {
            content: JSON.stringify({
              groups: [
                {
                  moduleId: "other",
                  summary: `Idea ${reports[0].title.slice(-1)}`,
                  ticketIds: [reports[0].id],
                },
              ],
            }),
          },
        },
      ],
    });
  }) as typeof fetch;
  await assert.rejects(
    summarize(tickets, config, 3, failOne, async (completed) => {
      progress.push(completed);
    }),
    /batch timed out/,
  );
  assert.equal(initialCalls, 3);
  assert.equal(progress.at(-1), 2);
  assert.equal(
    (await readdir(directory)).filter((name) => name.startsWith("run-")).length,
    0,
  );
  let retryCalls = 0;
  const resume = (async (_url, init) => {
    retryCalls++;
    const reports = JSON.parse(
      JSON.parse(String(init?.body)).messages[1].content,
    ).reports;
    assert.equal(reports[0].title, "Suggestion: b");
    return fixtureResponse({
      choices: [
        {
          message: {
            content: JSON.stringify({
              groups: [
                { moduleId: "other", summary: "Idea b", ticketIds: ["r1"] },
              ],
            }),
          },
        },
      ],
    });
  }) as typeof fetch;
  const run = await summarize(tickets, config, 3, resume);
  assert.equal(retryCalls, 1);
  assert.deepEqual(run.summaries[0].ticketIds, ["a", "b", "c"]);
  assert.equal(run.summaries[0].summary, "Idea a\n\nIdea b\n\nIdea c");
});
test("live lock is preserved, dead owner lock is reclaimed on explicit retry", async () => {
  const id = "b".repeat(64);
  await saveJson(`${id}.lock`, { pid: process.pid, runtime: "alive" });
  let worked = false;
  await assert.rejects(
    withRunLock(id, async () => {
      worked = true;
    }),
    /already being processed/,
  );
  assert.equal(worked, false);
  assert.equal(
    (await readJson<{ pid: number }>(`${id}.lock`)).pid,
    process.pid,
  );
  await saveJson(`${id}.lock`, { pid: 2147483647, runtime: "dead" });
  await withRunLock(id, async () => {
    worked = true;
  });
  assert.equal(worked, true);
  assert.ok(!(await readdir(directory)).includes(`${id}.lock`));
});
test("UI progress distinguishes active preview/send, saved counts, errors and safe retries", () => {
  const job = {
    status: "summarizing",
    totalTickets: 1991,
    totalBatches: 40,
    completedBatches: 7,
    send: false,
  } as Job;
  assert.equal(jobActive(job), true);
  assert.match(jobProgress(job), /7 of 40 batches/);
  assert.match(jobProgress(job), /1991/);
  assert.equal(jobActive({ ...job, status: "error" }), false);
  assert.equal(jobActive({ ...job, status: "interrupted" }), false);
  assert.match(jobProgress({ ...job, status: "done" }), /nothing sent/);
  assert.match(
    jobProgress({ ...job, status: "done", send: true }),
    /delivery status/,
  );
});
