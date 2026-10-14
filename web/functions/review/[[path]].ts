// /review/*: slides, live check and decisions, behind Cloudflare Access (the handler verifies
// the token, D29).
import { serve } from "../_lib/review/serve";

export const onRequest = serve;
