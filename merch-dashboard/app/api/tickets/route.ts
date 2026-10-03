import {merchSnapshot} from "../../../lib/clickup";
import {assertLocal,config,errorResponse} from "../../../lib/core";
export async function GET(request:Request){try{assertLocal(request);return Response.json({...await merchSnapshot(new URL(request.url).searchParams.get("refresh")==="1"),configured:config()})}catch(error){return errorResponse(error)}}
