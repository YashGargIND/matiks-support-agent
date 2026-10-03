import {getTicket} from "../../../lib/clickup";
import {suggest} from "../../../lib/reply";
import {assertLocal,errorResponse,ServiceError} from "../../../lib/core";
export async function POST(request:Request){try{assertLocal(request);const body=await request.json();if(typeof body.ticketId!=="string"||typeof body.context!=="string"||body.context.length>3000)throw new ServiceError("Choose a report and keep context below 3,000 characters.",400);return Response.json({reply:await suggest(await getTicket(body.ticketId),body.context)})}catch(error){return errorResponse(error)}}
