export function requireLocalRequest(request: Request) {
  const origin = request.headers.get("origin");
  const url = new URL(request.url);
  if (origin && origin !== url.origin)
    throw new Error("Cross-origin requests are not allowed.");
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname))
    throw new Error("This local dashboard must be used from localhost.");
}
export function failure(error: unknown) {
  return Response.json(
    { error: error instanceof Error ? error.message : "Request failed." },
    { status: 400 },
  );
}
