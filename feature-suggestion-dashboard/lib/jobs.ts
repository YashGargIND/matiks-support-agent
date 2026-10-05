import { randomUUID, createHash } from "node:crypto";
import { getConfig, readJson, saveJson, saveRun } from "./storage";
import { fetchSuggestions } from "./clickup";
import { summarize } from "./summarize";
import { sendRun } from "./slack";
import type { Job, Ticket } from "./types";
import { demoSnapshot } from "./demo";
const state = globalThis as typeof globalThis & {
  featureJobs?: {
    runtime: string;
    active: Set<string>;
    tail: Promise<unknown>;
  };
};
state.featureJobs ??= {
  runtime: randomUUID(),
  active: new Set(),
  tail: Promise.resolve(),
};
const runtime = () => state.featureJobs!;
const terminal = (job: Job) =>
  ["done", "error", "interrupted"].includes(job.status);
const validId = (id: string) => {
  if (!/^[a-f0-9]{64}$/.test(id)) throw new Error("Invalid job ID.");
};
const saveJob = async (job: Job) => {
  job.updatedAt = new Date().toISOString();
  await saveJson(`job-${job.id}.json`, job);
};
export function publicJob(job: Job) {
  const { owner: _owner, ...result } = job;
  if (
    result.status === "error" &&
    !result.run &&
    !result.error?.includes("Nothing was sent")
  )
    result.error = `${result.error || "Summary failed."} Nothing was sent. Retry the saved job to continue from completed batches.`;
  return result;
}
export async function getJob(id: string): Promise<Job> {
  validId(id);
  const job = await readJson<Job>(`job-${id}.json`);
  if (!terminal(job) && job.owner !== runtime().runtime) {
    job.status = "interrupted";
    job.error =
      "The local server restarted. Retry to continue using saved batches. No new Slack send is started on refresh.";
    await saveJob(job);
  }
  return job;
}
export async function latestJob(
  scope: "all" | "demo" = "all",
): Promise<Job | null> {
  try {
    const pointer = await readJson<{ id: string }>(
      scope === "demo" ? "latest-demo-job.json" : "latest-job.json",
    );
    return await getJob(pointer.id);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw e;
  }
}
async function exclusive<T>(work: () => Promise<T>): Promise<T> {
  const result = runtime().tail.then(work, work);
  runtime().tail = result.catch(() => undefined);
  return result;
}
export async function acceptJob(
  send: boolean,
  scope: "all" | "demo" = "all",
): Promise<{ job: Job; scheduled: boolean }> {
  if (scope === "demo" && send)
    throw new Error("Quick demo is preview only. Slack sending is disabled.");
  if (send && !process.env.SLACK_BOT_TOKEN)
    throw new Error(
      "Add SLACK_BOT_TOKEN before summarizing and sending. Preview is available now.",
    );
  if (!process.env.OPENROUTER_API_KEY)
    throw new Error("Configure OPENROUTER_API_KEY in .env.local.");
  return exclusive(async () => {
    const previous = await latestJob(scope);
    if (previous && !terminal(previous))
      return { job: previous, scheduled: false };
    const config = await getConfig();
    const now = new Date().toISOString();
    const job: Job = {
      id: createHash("sha256").update(randomUUID()).digest("hex"),
      status: "queued",
      createdAt: now,
      updatedAt: now,
      send,
      scope,
      config,
      fetchedPages: 0,
      fetchedTasks: 0,
      totalTickets: 0,
      completedBatches: 0,
      totalBatches: 0,
      owner: runtime().runtime,
    };
    await saveJob(job);
    await saveJson(
      scope === "demo" ? "latest-demo-job.json" : "latest-job.json",
      { id: job.id },
    );
    return { job, scheduled: true };
  });
}
export async function retryJob(
  id: string,
): Promise<{ job: Job; scheduled: boolean }> {
  return exclusive(async () => {
    const job = await getJob(id);
    const current = await latestJob(job.scope || "all");
    if (current && !terminal(current))
      return { job: current, scheduled: false };
    if (job.status === "done") return { job, scheduled: false };
    if (!process.env.OPENROUTER_API_KEY)
      throw new Error("Configure OPENROUTER_API_KEY before retrying.");
    if (job.send && !process.env.SLACK_BOT_TOKEN)
      throw new Error(
        "This saved job includes Slack sending. Add SLACK_BOT_TOKEN before retrying; its original send intent is preserved.",
      );
    job.status = "queued";
    job.owner = runtime().runtime;
    delete job.error;
    await saveJob(job);
    await saveJson(
      job.scope === "demo" ? "latest-demo-job.json" : "latest-job.json",
      { id: job.id },
    );
    return { job, scheduled: true };
  });
}
export async function processJob(id: string, fetcher: typeof fetch = fetch) {
  validId(id);
  if (runtime().active.has(id)) return;
  runtime().active.add(id);
  let job: Job | undefined;
  try {
    job = await getJob(id);
    if (terminal(job)) return;
    job.status = "fetching";
    await saveJob(job);
    let snapshot: {
      tickets: Ticket[];
      fetchedTasks: number;
      pages: number;
      sourceTickets?: number;
      snapshotAt?: string;
    };
    try {
      snapshot = await readJson(`job-tickets-${id}.json`);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
      const fetchingJob = job;
      snapshot =
        job.scope === "demo"
          ? await demoSnapshot()
          : await fetchSuggestions(fetcher, false, async (progress) => {
              fetchingJob.fetchedPages = progress.pages;
              fetchingJob.fetchedTasks = progress.fetchedTasks;
              await saveJob(fetchingJob);
            });
      await saveJson(`job-tickets-${id}.json`, snapshot);
    }
    job.fetchedPages = snapshot.pages;
    job.fetchedTasks = snapshot.fetchedTasks;
    job.totalTickets = snapshot.tickets.length;
    job.sourceTickets = snapshot.sourceTickets ?? snapshot.tickets.length;
    job.snapshotAt = snapshot.snapshotAt;
    if (
      job.scope === "demo" &&
      snapshot.tickets.reduce(
        (sum, ticket) => sum + JSON.stringify(ticket).length,
        0,
      ) > 24000
    )
      throw new Error(
        "The latest20 reports exceed one bounded demo batch. Nothing was sent; use the normal dashboard for full coverage.",
      );
    job.status = "summarizing";
    await saveJob(job);
    const activeJob = job;
    job.run = await summarize(
      snapshot.tickets,
      job.config,
      snapshot.fetchedTasks,
      fetcher,
      async (completed, total) => {
        activeJob.completedBatches = completed;
        activeJob.totalBatches = total;
        await saveJob(activeJob);
      },
      job.scope || "all",
    );
    if (job.scope === "demo") {
      job.run = {
        ...job.run,
        scope: "demo",
        sourceTickets: job.sourceTickets,
        snapshotAt: job.snapshotAt,
      };
      await saveRun(job.run);
    }
    if (job.send) {
      job.status = "sending";
      await saveJob(job);
      job.run = await sendRun(job.run.id, fetcher);
    }
    job.status = "done";
    await saveJob(job);
  } catch (e) {
    if (job) {
      job.status = "error";
      job.error =
        e instanceof Error
          ? e.message
          : "Summary failed. Completed batches are saved; retry to continue.";
      await saveJob(job);
    }
  } finally {
    runtime().active.delete(id);
  }
}
