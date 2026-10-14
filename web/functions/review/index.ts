// GET /review: the queue page, behind Cloudflare Access (the handler verifies the token, D29).
import { serve } from "../_lib/review/serve";

export const onRequest = serve;
