// Deploy a copy replacing TOKEN_SHA256 with the hash of a generated server-only token.
// The plaintext token stays in Render secrets; Supabase's own service key stays in Supabase.
const TOKEN_SHA256 = 'CONFIGURE_AT_DEPLOYMENT';
const MAX_BYTES = 20 * 1024 * 1024;
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const pathPattern = new RegExp('^'+UUID+'/'+UUID+'/(pdf|text)/'+UUID+'/[0-9a-f]{64}\\.(pdf|json)$');
const deny = (status:number) => new Response('Request refused', {status,headers:{'Cache-Control':'no-store'}});
Deno.serve(async (req: Request) => {
  if (!['GET','POST'].includes(req.method)) return deny(405);
  const token = req.headers.get('X-Storage-Token') ?? '';
  if (token.length < 32 || token.length > 256) return deny(401);
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(token)));
  const expected = TOKEN_SHA256;
  const actual = [...hash].map(x=>x.toString(16).padStart(2,'0')).join('');
  let difference = expected.length ^ actual.length;
  for (let i=0;i<actual.length;i++) difference |= actual.charCodeAt(i) ^ (expected.charCodeAt(i) || 0);
  if (difference !== 0) return deny(401);
  const path = new URL(req.url).searchParams.get('path') ?? '';
  if (!pathPattern.test(path) || (path.includes('/pdf/') !== path.endsWith('.pdf'))) return deny(400);
  const base = Deno.env.get('SUPABASE_URL');
  const key = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
  if (!base || !key) return deny(503);
  const headers:Record<string,string> = {apikey:key,Authorization:'Bearer '+key};
  let body:Uint8Array<ArrayBuffer>|undefined;
  if (req.method==='POST') {
    const declared = Number(req.headers.get('Content-Length') ?? '0');
    if (declared>MAX_BYTES) return deny(413);
    if (!req.body) return deny(400);
    const reader=req.body.getReader();const chunks:Uint8Array[]=[];let size=0;
    while(true){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;if(size>MAX_BYTES){await reader.cancel();return deny(413);}chunks.push(part.value);}
    body=new Uint8Array(size);let offset=0;for(const chunk of chunks){body.set(chunk,offset);offset+=chunk.byteLength;}
    const mime=path.endsWith('.pdf')?'application/pdf':'application/json';
    if(mime==='application/pdf' && new TextDecoder().decode(body.slice(0,5))!=='%PDF-')return deny(415);
    if(mime==='application/json'){try{JSON.parse(new TextDecoder().decode(body));}catch{return deny(415);}}
    headers['Content-Type']=mime;headers['x-upsert']='true';
  }
  const upstream=await fetch(base+'/storage/v1/object/fullmark-private/'+path,{method:req.method,headers,body});
  if (!upstream.ok) return deny(upstream.status);
  return new Response(upstream.body,{status:upstream.status,headers:{'Content-Type':req.method==='GET'?(path.endsWith('.pdf')?'application/pdf':'application/json'):'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
});
