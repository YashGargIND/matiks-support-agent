import nextServer from "next/server";
import { retryJob, processJob, publicJob } from "@/lib/jobs";
import { failure, requireLocalRequest } from "@/lib/http";
export const runtime = "nodejs";
export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    requireLocalRequest(request);
    const { id } = await context.params;
    const result = await retryJob(id);
    if (result.scheduled) nextServer.after(() => processJob(result.job.id));
    return Response.json({ job: publicJob(result.job) }, { status: 202 });
  } catch (e) {
    return failure(e);
  }
}
