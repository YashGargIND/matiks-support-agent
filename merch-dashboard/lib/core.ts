export type Ticket={id:string; title:string; description:string; status:string; createdAt:string; url:string; recipient:string|null; names:string[]};
export class ServiceError extends Error { constructor(message:string, public status=502) {super(message)} }
export const emailPattern=/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/;
export function isMerch(task:any):boolean {
 const text=`${task.name||""} ${task.description||task.text_content||""}`;
 const topic=(task.custom_fields||[]).find((f:any)=>f.id==="a5e3ce45-2379-4f5d-945b-b2dc9db92917")?.value;
 if(String(topic)==="1"||topic==="2cc005ec-16a0-44cb-9a1f-a6737e867e25"||/^Suggestion:/i.test(task.name||""))return false;
 return (/\b(?:merch(?:andise)?|t[ -]?shirts?|shirts?|hoodies?|cakes?|physical rewards?)\b/i.test(text)||(/\b(?:50|100|200|365)\s*[- ]?days?\b/i.test(text)&&/\brewards?\b/i.test(text)));
}
export function normalize(task:any):Ticket {
 const expected=process.env.CLICKUP_EMAIL_FIELD_ID||(process.env.CLICKUP_LIST_ID==="901611930428"?"dc7038b0-24fd-4767-a5eb-f5d5f1d1ea17":"");
 const field=(task.custom_fields||[]).find((f:any)=>f.id===expected)?.value;
 const recipient=typeof field==="string"&&emailPattern.test(field.trim())?field.trim():null;
 const names=(task.custom_fields||[]).filter((f:any)=>f.id==="068dd0b6-7886-4775-aa84-fc0a36009a26").map((f:any)=>f.value).filter((v:any)=>typeof v==="string");
 return{id:String(task.id),title:String(task.name||"Untitled report"),description:String(task.description||task.text_content||task.markdown_description||""),status:String(task.status?.status||"unknown"),createdAt:new Date(Number(task.date_created)||0).toISOString(),url:`https://app.clickup.com/t/${encodeURIComponent(task.id)}`,recipient,names};
}
export function redact(text:string,names:string[]=[]):string {
 let result=text.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,"[email]").replace(/https?:\/\/[^\s<>]+/gi,"[link]").replace(/\b(?:\+?\d[\d ()-]{8,}\d)\b/g,"[number]");
 for(const name of names) if(name.length>=2) result=result.split(name).join("[name]");
 return result.slice(0,12000);
}
export function assertLocal(request:Request) {
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
    throw new ServiceError("Only same-origin local requests are supported.", 403);
  }
}
export function config() {
 return{clickup:!!(process.env.CLICKUP_API_TOKEN&&process.env.CLICKUP_LIST_ID),openrouter:!!process.env.OPENROUTER_API_KEY,email:!!(process.env.GOOGLE_OAUTH_CLIENT_ID&&process.env.GOOGLE_OAUTH_CLIENT_SECRET&&process.env.IMAP_USER&&process.env.IMAP_REFRESH_TOKEN)};
}
export function errorResponse(error:unknown) {return Response.json({error:error instanceof ServiceError?error.message:"The request could not be completed. Please retry."},{status:error instanceof ServiceError?error.status:502})}
