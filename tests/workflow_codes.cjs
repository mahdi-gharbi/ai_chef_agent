// Exercises the exported Code nodes locally. This is not an n8n import test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const wf = JSON.parse(fs.readFileSync(path.join(__dirname, '../n8n/workflows/kooki_chat.json'), 'utf8'));
const nodes = Object.fromEntries(wf.nodes.map(n => [n.name, n]));
function run(name, json, execution = '42') {
  return new Function('$json', '$execution', nodes[name].parameters.jsCode)(json, {id:execution})[0].json;
}
const body = {user_id:'alice',session_id:'chat1',message:' Dinner ',metadata:{city:'Tunis'}};
const valid = run('Validate - Normalize',{body});
assert.equal(valid.valid, true);
assert.equal(valid.payload.message, 'Dinner');
assert.equal(valid.payload.idempotency_key, 'n8n-42');
assert.equal(valid.payload.metadata.channel, 'n8n');
assert.equal(run('Validate - Normalize',{body:{...body,user_id:'../bad'}}).http_status,422);
assert.equal(run('Validate - Normalize',{body:{...body,metadata:[]}}).valid,false);
assert.equal(run('Validate - Normalize',{body:{...body,idempotency_key:'caller-key'}}).payload.idempotency_key,'caller-key');
const context = run('Set Execution Context',valid);
assert.deepEqual(context.payload,valid.payload);
for (const i of [1,2,3]) {
  const name = `Assess response ${i}`;
  assert.equal(run(name,{body:{status:'success',response:'dinner'},statusCode:200}).result.status,'success');
  assert.equal(run(name,{body:{status:'error',retryable:false},statusCode:409}).http_status,409);
  assert.equal(run(name,{body:{status:'error',retryable:true},statusCode:429}).result.retryable,true);
  assert.equal(run(name,{error:'private transport detail'}).result.error_type,'API_TRANSPORT_ERROR');
  assert.equal(JSON.stringify(run(name,{error:'private transport detail'})).includes('private transport detail'),false);
}
console.log('Workflow Code nodes: 23 assertions passed; n8n runtime import not exercised.');
