import {getTicket} from "../../../lib/clickup";
import {sendEmail} from "../../../lib/email";
import {assertLocal,errorResponse,ServiceError} from "../../../lib/core";
export async function POST(request:Request){try{assertLocal(request);const body=await request.json();if(typeof body.ticketId!=="string"||typeof body.reply!=="string"||typeof body.key!=="string"||body.reviewed!==true)throw new ServiceError("Review the email and recipient before sending.",400);return Response.json(await sendEmail(await getTicket(body.ticketId),body.reply,body.key))}catch(error){return errorResponse(error)}}
