import type { Job } from "./types";
export const jobActive = (job: Pick<Job, "status"> | null) =>
  Boolean(
    job &&
    ["queued", "fetching", "summarizing", "sending"].includes(job.status),
  );
export function jobProgress(job: Job) {
  if (job.status === "queued")
    return "Summary queued. You can leave this page and return later.";
  if (job.status === "fetching")
    return `Fetching all ClickUp pages: ${job.fetchedPages} pages read, ${job.fetchedTasks} reports fetched. No partial dataset will be summarized.`;
  if (job.status === "summarizing")
    return `Summarizing ${job.totalTickets} suggestions: ${job.completedBatches} of ${job.totalBatches} batches completed. Completed batches are saved.`;
  if (job.status === "sending")
    return "All suggestions covered. Sending to the saved Slack destinations…";
  if (job.status === "done")
    return job.send
      ? "Finished. Check each module’s Slack delivery status."
      : `Preview ready. All ${job.totalTickets} suggestions covered; nothing sent.`;
  return (
    job.error || "Summary interrupted. Retry to continue using saved batches."
  );
}
