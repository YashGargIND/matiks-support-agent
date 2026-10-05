import { randomUUID, createHash } from "node:crypto";
import { getConfig, readJson, saveJson } from "./storage";
import { fetchSuggestions } from "./clickup";
import { summarize } from "./summarize";
import { sendRun } from "./slack";
import type { Job, Ticket } from "./types";
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
export async function latestJob(): Promise<Job | null> {
  try {
    const pointer = await readJson<{ id: string }>("latest-job.json");
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
): Promise<{ job: Job; scheduled: boolean }> {
  if (send && !process.env.SLACK_BOT_TOKEN)
    throw new Error(
      "Add SLACK_BOT_TOKEN before summarizing and sending. Preview is available now.",
    );
  if (!process.env.OPENROUTER_API_KEY)
    throw new Error("Configure OPENROUTER_API_KEY in .env.local.");
  return exclusive(async () => {
    const previous = await latestJob();
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
      config,
      fetchedPages: 0,
      fetchedTasks: 0,
      totalTickets: 0,
      completedBatches: 0,
      totalBatches: 0,
      owner: runtime().runtime,
    };
    await saveJob(job);
    await saveJson("latest-job.json", { id: job.id });
    return { job, scheduled: true };
  });
}
export async function retryJob(
  id: string,
): Promise<{ job: Job; scheduled: boolean }> {
  return exclusive(async () => {
    const job = await getJob(id);
    const current = await latestJob();
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
    await saveJson("latest-job.json", { id: job.id });
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
    let snapshot: { tickets: Ticket[]; fetchedTasks: number; pages: number };
    try {
      snapshot = await readJson(`job-tickets-${id}.json`);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
      const fetchingJob = job;
      snapshot = await fetchSuggestions(fetcher, false, async (progress) => {
        fetchingJob.fetchedPages = progress.pages;
        fetchingJob.fetchedTasks = progress.fetchedTasks;
        await saveJob(fetchingJob);
      });
      await saveJson(`job-tickets-${id}.json`, snapshot);
    }
    job.fetchedPages = snapshot.pages;
    job.fetchedTasks = snapshot.fetchedTasks;
    job.totalTickets = snapshot.tickets.length;
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
    );
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
