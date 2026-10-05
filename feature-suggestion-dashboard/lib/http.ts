export function requireLocalRequest(request: Request) {
  try {
    const url = new URL(request.url);
    const host = request.headers.get("host") || url.host;
    // Next.js normalizes loopback URLs to localhost. The HTTP Host retains
    // the address used by the browser; validate it before comparing origins.
    const local = new URL(`${url.protocol}//${host}`);
    const loopback = ["127.0.0.1", "localhost", "[::1]"];
    const origin = request.headers.get("origin");
    if (
      !loopback.includes(url.hostname) ||
      !loopback.includes(local.hostname) ||
      !["http:", "https:"].includes(url.protocol) ||
      local.host !== host.toLowerCase() ||
      local.port !== url.port ||
      (origin && new URL(origin).origin !== local.origin)
    ) throw new Error("Rejected local request");
  } catch {
    throw new Error("Cross-origin requests are not allowed; use this dashboard from localhost.");
  }
}
export function failure(error: unknown) {
  return Response.json(
    { error: error instanceof Error ? error.message : "Request failed." },
    { status: 400 },
  );
}
