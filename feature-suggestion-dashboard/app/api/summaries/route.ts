import nextServer from "next/server";
import { acceptJob, latestJob, processJob, publicJob } from "@/lib/jobs";
import { failure, requireLocalRequest } from "@/lib/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  try {
    requireLocalRequest(request);
    const job = await latestJob();
    return Response.json({ job: job ? publicJob(job) : null });
  } catch (e) {
    return failure(e);
  }
}
export async function POST(request: Request) {
  try {
    requireLocalRequest(request);
    const body = await request.json();
    if (body.send !== true && body.send !== false)
      throw new Error("Choose preview or send.");
    const result = await acceptJob(body.send);
    if (result.scheduled) nextServer.after(() => processJob(result.job.id));
    return Response.json({ job: publicJob(result.job) }, { status: 202 });
  } catch (e) {
    return failure(e);
  }
}
