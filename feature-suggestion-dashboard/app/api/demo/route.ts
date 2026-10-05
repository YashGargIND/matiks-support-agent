import nextServer from "next/server";
import { demoSnapshot } from "@/lib/demo";
import { acceptJob, latestJob, processJob, publicJob } from "@/lib/jobs";
import { failure, requireLocalRequest } from "@/lib/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  try {
    requireLocalRequest(request);
    const snapshot = await demoSnapshot();
    const job = await latestJob("demo");
    return Response.json({ ...snapshot, job: job ? publicJob(job) : null });
  } catch (e) {
    return failure(e);
  }
}
export async function POST(request: Request) {
  try {
    requireLocalRequest(request);
    const body = await request.json();
    if (body.send !== false) throw new Error("Quick demo is preview only.");
    const result = await acceptJob(false, "demo");
    if (result.scheduled) nextServer.after(() => processJob(result.job.id));
    return Response.json({ job: publicJob(result.job) }, { status: 202 });
  } catch (e) {
    return failure(e);
  }
}
