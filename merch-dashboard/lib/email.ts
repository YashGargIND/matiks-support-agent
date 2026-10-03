import nodemailer from "nodemailer";
import {createHash} from "node:crypto";
import {mkdir,writeFile,readFile} from "node:fs/promises";
import {join} from "node:path";
import {config,emailPattern,ServiceError,type Ticket} from "./core";
export function mimeMessage(sender:string,recipient:string,subject:string,reply:string):string {
 if(!emailPattern.test(sender)||!emailPattern.test(recipient))throw new ServiceError("The sender or reporter email is invalid.",400);
 const cleanSubject=subject.replace(/[\r\n]/g," ").slice(0,160);
 const message=`From: ${sender}\r\nTo: ${recipient}\r\nSubject: =?UTF-8?B?${Buffer.from(cleanSubject).toString("base64")}?=\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n${Buffer.from(reply).toString("base64")}\r\n`;
 return Buffer.from(message).toString("base64url");
}
type Transport={verify:()=>Promise<unknown>;sendMail:(message:any)=>Promise<{accepted?:unknown[];messageId?:string}>;close?:()=>void};
export type TransportFactory=(token:string)=>Transport;
export const makeTransport:TransportFactory=(token)=>nodemailer.createTransport({host:"smtp.gmail.com",port:465,secure:true,auth:{type:"OAuth2",user:process.env.IMAP_USER!,accessToken:token},connectionTimeout:20000,greetingTimeout:20000,socketTimeout:30000,logger:false,debug:false});
async function accessToken(fetcher:typeof fetch):Promise<string>{
 const response=await fetcher("https://oauth2.googleapis.com/token",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},signal:AbortSignal.timeout(20000),body:new URLSearchParams({client_id:process.env.GOOGLE_OAUTH_CLIENT_ID!,client_secret:process.env.GOOGLE_OAUTH_CLIENT_SECRET!,refresh_token:process.env.IMAP_REFRESH_TOKEN!,grant_type:"refresh_token"})});
 if(!response.ok)throw new ServiceError("Google OAuth refresh was denied. Reconnect the account with full Gmail access.");
 const data=await response.json();
 if(data.scope&&!String(data.scope).split(" ").includes("https://mail.google.com/"))throw new ServiceError("Google SMTP OAuth needs the full https://mail.google.com/ scope.");
 if(typeof data.access_token!=="string")throw new ServiceError("Google did not return an access token.");return data.access_token;
}
export async function sendEmail(ticket:Ticket,reply:string,key:string,fetcher:typeof fetch=fetch,storage=join(process.cwd(),".data","send-receipts"),factory:TransportFactory=makeTransport) {
 if(!config().email)throw new ServiceError("Google email credentials are missing. Add the OAuth and IMAP settings to .env.local.",503);
 if(!ticket.recipient)throw new ServiceError("This report has no verified reporter email custom field. Sending is unavailable.",400);
 if(!/^[a-zA-Z0-9-]{16,80}$/.test(key)||reply.trim().length<10||reply.length>10000)throw new ServiceError("Review the reply before sending.",400);
 await mkdir(storage,{recursive:true,mode:0o700});
 const payload=createHash("sha256").update(JSON.stringify([ticket.id,ticket.recipient,reply])).digest("hex");
 const file=join(storage,createHash("sha256").update(key).digest("hex")+".json");
 try{await writeFile(file,JSON.stringify({state:"pending",payload}),{flag:"wx",mode:0o600})}catch(error:any){
  if(error.code!=="EEXIST")throw error;
  const previous=JSON.parse(await readFile(file,"utf8"));
  if(previous.payload!==payload)throw new ServiceError("This send request was already used for another draft.",409);
  if(previous.state==="sent")return {id:previous.id,duplicate:true};
  throw new ServiceError("This send was already attempted. Check Gmail Sent before retrying; delivery may be uncertain.",409);
 }
 let dispatched=false,transport:Transport|undefined;
 try{
  const token=await accessToken(fetcher);transport=factory(token);
  // AUTH verifies the configured sender matches this OAuth account before any message.
  await transport.verify();
  dispatched=true;
  const result=await transport.sendMail({envelope:{from:process.env.IMAP_USER!,to:[ticket.recipient]},raw:Buffer.from(mimeMessage(process.env.IMAP_USER!,ticket.recipient,`Re: ${ticket.title}`,reply),"base64url")});
  if(!result.accepted?.some(address=>String(address).toLowerCase()===ticket.recipient!.toLowerCase())||typeof result.messageId!=="string")throw new ServiceError("Google returned no recipient acceptance. Check Gmail Sent before retrying.",409);
  await writeFile(file,JSON.stringify({state:"sent",payload,id:result.messageId}),{mode:0o600});return{id:result.messageId,duplicate:false};
 }catch(error:any){
  if(error?.code==="EAUTH"||error?.code==="EENVELOPE"||Number(error?.responseCode)>=400)dispatched=false;
  await writeFile(file,JSON.stringify({state:dispatched?"uncertain":"failed",payload}),{mode:0o600});
  if(dispatched)throw new ServiceError("Email acceptance was interrupted. Check Gmail Sent before attempting another send.",409);
  throw error instanceof ServiceError?error:new ServiceError(error?.code==="EAUTH"?"Google SMTP authentication was denied. Check IMAP_USER and reconnect the OAuth grant with full Gmail access.":"Google email could not be reached or rejected the message. Check the account before retrying.");
 }finally{transport?.close?.()}
}
export async function emailStatus(fetcher:typeof fetch=fetch,factory:TransportFactory=makeTransport):Promise<{ready:boolean;reason:string}> {
 if(!config().email)return{ready:false,reason:"Google email credentials are missing from .env.local."};
 let transport:Transport|undefined;
 try{transport=factory(await accessToken(fetcher));await transport.verify();return{ready:true,reason:"Google SMTP account verified. Emails are sent only after your review."}}
 catch(error:any){return{ready:false,reason:error instanceof ServiceError?error.message:error?.code==="EAUTH"?"Google SMTP authentication was denied. Check IMAP_USER and the full Gmail OAuth grant.":"Google SMTP could not be reached. Refresh to retry."}}
 finally{transport?.close?.()}
}
