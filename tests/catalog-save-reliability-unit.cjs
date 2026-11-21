const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const source=fs.readFileSync('api-client.js','utf8');
function client(fetch,storage=new Map()) {
 const context={window:{},location:{protocol:'https:',hostname:'oimo.test',origin:'https://oimo.test',pathname:'/admin',search:''},
  sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  crypto:webcrypto,TextEncoder,Uint8Array,URLSearchParams,AbortController,setTimeout,clearTimeout,fetch};
 vm.runInNewContext(source,context);return context.window.AshkanaApi;
}
const reply=(body,status=200)=>({ok:status<400,status,headers:{get:()=> 'application/json'},json:async()=>body});
(async()=>{
 const calls=[];
 const api=client(async(url,options)=>{calls.push([url,options]);if(options.method==='POST')throw new Error('acknowledgement lost');return reply({confirmed:true,entity:{type:'recipe',id:'101'},version:2,state:{recipes:[]}});});
 const recovered=await api.action('recipe.upsert',{name:'Манты'},{expectedRevision:'new',compactCatalog:true});
 assert.equal(recovered.confirmed,true);
 const posts=calls.filter(([,options])=>options.method==='POST').map(([,options])=>JSON.parse(options.body));
 assert.ok(posts.length>=1);assert.ok(posts.every(row=>row.request_id===posts[0].request_id));
 assert.equal(posts[0].expected_revision,'new');assert.equal(posts[0].payload.requestId,undefined);
 assert.ok(calls.some(([url])=>url.includes('/catalog-operations/')));
 // An unresolved attempt keeps its identity even across a page reload.
 const storage=new Map(),ids=[];
 let fail=true;
 const fetch=async(url,options)=>{
  if(options.method==='POST'){ids.push(JSON.parse(options.body).request_id);return fail?reply({detail:'unavailable'},503):reply({version:2});}
  return reply({confirmed:false});
 };
 await assert.rejects(client(fetch,storage).action('preparation.upsert',{id:'dough',name:'Тесто'},{expectedRevision:'old-revision'}));
 fail=false;
 await client(fetch,storage).action('preparation.upsert',{id:'dough',name:'Тесто'},{expectedRevision:'old-revision'});
 assert.equal(ids[0],ids.at(-1));
 assert.ok(![...storage.keys()].some(key=>key.startsWith('oimo-pending-operation-')));
 // A conflict is returned directly; never silently reapply against the new version.
 let conflicts=0;
 await assert.rejects(client(async()=>{conflicts++;return reply({detail:'changed in another tab'},409);}).action('recipe.upsert',{id:1},{expectedRevision:'stale'}),error=>error.status===409);
 assert.equal(conflicts,1);
 for(const action of ['ingredient.upsert','product.upsert','product.group.upsert','supplier.upsert','category.upsert']){
  const sent=[];
  const api=client(async(url,options)=>{
    if(options.method==='POST'){sent.push(JSON.parse(options.body));return reply({detail:'unavailable'},503);}
    return reply({confirmed:true,version:2});
  });
  const result=await api.action(action,{id:'test',name:'Changed'},{expectedRevision:'opened-revision'});
  assert.equal(result.confirmed,true);
  assert.ok(sent[0].request_id);assert.equal(sent[0].expected_revision,'opened-revision');
 }
 console.log('Lost acknowledgements, persistent operation identity and edit conflicts: passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
