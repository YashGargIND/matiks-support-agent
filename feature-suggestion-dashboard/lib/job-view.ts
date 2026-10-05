import type { Job } from "./types";
export const jobActive = (job: Pick<Job, "status"> | null) =>
  Boolean(
    job &&
    ["queued", "fetching", "summarizing", "sending"].includes(job.status),
  );
export function jobProgress(job: Job) {
  const scopeLabel =
    job.scope === "demo"
      ? `Demo sample: ${job.totalTickets} of ${job.sourceTickets || job.totalTickets} suggestions`
      : `${job.totalTickets} suggestions`;
  if (job.status === "queued")
    return "Summary queued. You can leave this page and return later.";
  if (job.status === "fetching")
    if (job.scope === "demo")
      return "Loading the latest 20 suggestions from the cached complete snapshot. No live ClickUp fetch.";
  if (job.status === "fetching")
    return `Fetching all ClickUp pages: ${job.fetchedPages} pages read, ${job.fetchedTasks} reports fetched. No partial dataset will be summarized.`;
  if (job.status === "summarizing")
    return `Summarizing ${scopeLabel}: ${job.completedBatches} of ${job.totalBatches} batches completed. Completed batches are saved.`;
  if (job.status === "sending")
    return "All suggestions covered. Sending to the saved Slack destinations…";
  if (job.status === "done")
    return job.send
      ? "Finished. Check each module’s Slack delivery status."
      : job.scope === "demo"
        ? `Demo preview ready. Latest ${job.totalTickets} of ${job.sourceTickets} suggestions covered; nothing sent.`
        : `Preview ready. All ${job.totalTickets} suggestions covered; nothing sent.`;
  return (
    job.error || "Summary interrupted. Retry to continue using saved batches."
  );
}
