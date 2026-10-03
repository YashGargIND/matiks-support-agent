import {ServiceError,isMerch,normalize,type Ticket} from "./core";
export async function clickup(path:string, fetcher:typeof fetch=fetch) {
 const token=process.env.CLICKUP_API_TOKEN,list=process.env.CLICKUP_LIST_ID;
 if(!token||!list)throw new ServiceError("Add CLICKUP_API_TOKEN and CLICKUP_LIST_ID to .env.local.",503);
 if(!/^\d+$/.test(list))throw new ServiceError("CLICKUP_LIST_ID must be numeric.",503);
 let response:Response|undefined;
 for(let attempt=0;attempt<4;attempt++){
  try {response=await fetcher(`https://api.clickup.com/api/v2/${path}`,{headers:{Authorization:token},cache:"no-store",signal:AbortSignal.timeout(20000)})}catch{throw new ServiceError("ClickUp could not be reached. Retry shortly.")}
  if(response.status!==429||attempt===3)break;
  const reset=Number(response.headers.get("X-RateLimit-Reset"));
  const retry=Number(response.headers.get("Retry-After"));
  const wait=reset>0?(reset>1e12?reset:reset*1000)-Date.now()+1000:retry>0?retry*1000:30000;
  if(wait>60000)throw new ServiceError("ClickUp rate limit reached. Wait a minute and refresh again.");
  await new Promise(resolve=>setTimeout(resolve,Math.max(1000,wait)));
 }
 if(!response)throw new ServiceError("ClickUp could not load reports.");
 if(!response.ok)throw new ServiceError(response.status===429?"ClickUp rate limit reached. Retry shortly.":response.status===401||response.status===403?"ClickUp access was denied. Check the token and list access.":"ClickUp could not load reports.");
 return response.json();
}
export async function allMerch(fetcher:typeof fetch=fetch):Promise<{tickets:Ticket[];scanned:number;pages:number}> {
 const tickets=new Map<string,Ticket>();let scanned=0;
 for(let page=0;page<200;page++) {
  const data=await clickup(`list/${process.env.CLICKUP_LIST_ID}/task?include_closed=true&subtasks=true&order_by=created&reverse=false&page=${page}`,fetcher);
  if(!Array.isArray(data.tasks))throw new ServiceError("ClickUp returned an unexpected report format.");
  scanned+=data.tasks.length;
  for(const task of data.tasks)if(isMerch(task))tickets.set(String(task.id),normalize(task));
  if(data.last_page===true||data.tasks.length<100)return{tickets:[...tickets.values()],scanned,pages:page+1};
 }
 throw new ServiceError("The list exceeds 20,000 reports. No partial result is shown; use a smaller dedicated support list.");
}
export async function getTicket(id:string):Promise<Ticket> {
 if(!/^[a-zA-Z0-9_-]{1,80}$/.test(id))throw new ServiceError("Invalid report ID.",400);
 const raw=await clickup(`task/${id}`);
 if(String(raw.list?.id)!==process.env.CLICKUP_LIST_ID||!isMerch(raw))throw new ServiceError("This report is not a merch issue in the configured list.",400);
 return normalize(raw);
}

let cached:Awaited<ReturnType<typeof allMerch>>|null=null,expires=0,inflight:Promise<Awaited<ReturnType<typeof allMerch>>>|null=null;
export async function merchSnapshot(refresh=false){
 if(!refresh&&cached&&Date.now()<expires)return cached;
 if(inflight)return inflight;
 inflight=allMerch().then(data=>{cached=data;expires=Date.now()+300000;return data}).finally(()=>{inflight=null});return inflight;
}
