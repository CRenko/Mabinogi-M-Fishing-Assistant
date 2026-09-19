import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker from '../src/worker.js';

// Exercise actual worker handlers and migration SQL against SQLite, not canned rows.
function environment() {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../migrations/0001_devices.sql', import.meta.url), 'utf8'));
  const prepare = sql => ({bind(...args) {
    const stmt = db.prepare(sql);
    return {first: async () => stmt.get(...args) || null,
      all: async () => ({results: stmt.all(...args)}), run: async () => stmt.run(...args)};
  }, all: async () => ({results: db.prepare(sql).all()})});
  return {DB: {prepare, batch: async statements => Promise.all(statements.map(s => s.run()))},
    ADMIN_TOKEN: 'admin-'.repeat(8), MAX_DEVICES: '25', db};
}
async function api(env, path, method='GET', data, token='') {
  const response = await worker.fetch(new Request('https://relay.example'+path, {
    method, headers: {'Content-Type':'application/json', Authorization:`Bearer ${token}`},
    ...(data === undefined ? {} : {body: JSON.stringify(data)})
  }), env);
  return {status: response.status, data: await response.json()};
}
async function activate(env, token='a'.repeat(64)) {
  const issued = await api(env, '/admin/codes', 'POST', {}, env.ADMIN_TOKEN);
  const code = issued.data.codes[0];
  const result = await api(env, '/v1/activate', 'POST', {code, write_token:token});
  assert.equal(result.status, 201);
  return {token, code, id:result.data.device_id};
}
const status = {monitoring:true, calibrated:true, state:'waiting_bite', strategy:'fixed_delay',
  recognition:'ok', version:'0.6.4', observed_at:123, reason:''};

test('one-time activation, lost-response retry and server-enforced capacity', async () => {
  const env=environment(); env.MAX_DEVICES='1';
  const first=await activate(env);
  assert.equal((await api(env,'/v1/activate','POST',{code:first.code,write_token:first.token})).status,200);
  assert.equal((await api(env,'/v1/activate','POST',{code:first.code,write_token:'b'.repeat(64)})).status,403);
  const issued=await api(env,'/admin/codes','POST',{},env.ADMIN_TOKEN);
  assert.equal((await api(env,'/v1/activate','POST',{code:issued.data.codes[0],write_token:'b'.repeat(64)})).status,409);
  env.db.close();
});
test('pairing is single-phone, tokens role-separated, latest status only', async () => {
  const env=environment(), pc=await activate(env), reader='b'.repeat(64);
  const pair=await api(env,'/v1/pair','POST',{},pc.token);
  const claim={pair_code:pair.data.pair_code,read_token:reader};
  assert.equal((await api(env,'/v1/pair/claim','POST',claim)).status,200);
  assert.equal((await api(env,'/v1/pair/claim','POST',claim)).status,200);
  assert.equal((await api(env,'/v1/pair/claim','POST',{...claim,read_token:'c'.repeat(64)})).status,403);
  assert.equal((await api(env,'/v1/status','PUT',status,reader)).status,401);
  assert.equal((await api(env,'/v1/status','GET',undefined,pc.token)).status,401);
  assert.equal((await api(env,'/v1/status','PUT',{...status,window_title:'PRIVATE'},pc.token)).status,200);
  const view=await api(env,'/v1/status','GET',undefined,reader);
  assert.equal(view.data.status.state,'waiting_bite');
  assert.equal(view.data.stale,false);
  assert.equal(view.data.status.window_title,undefined);
  assert.equal((await api(env,'/v1/status','PUT',status,pc.token)).status,429);
  const row=env.db.prepare('SELECT * FROM devices').get();
  assert.ok(!JSON.stringify(row).includes(pc.token));
  assert.ok(!JSON.stringify(row).includes(reader));
  assert.ok(!JSON.stringify(row).includes(pair.data.pair_code));
  await api(env,'/v1/unpair','POST',{},pc.token);
  assert.equal((await api(env,'/v1/status','GET',undefined,reader)).status,401);
  env.db.close();
});
test('expiry, stale status, user isolation and admin revocation', async () => {
  const env=environment(), a=await activate(env), b=await activate(env,'d'.repeat(64));
  const pair=await api(env,'/v1/pair','POST',{},a.token), reader='b'.repeat(64);
  await api(env,'/v1/pair/claim','POST',{pair_code:pair.data.pair_code,read_token:reader});
  await api(env,'/v1/status','PUT',status,b.token);
  const empty=await api(env,'/v1/status','GET',undefined,reader);
  assert.equal(empty.data.device_id,a.id); assert.equal(empty.data.status,null); assert.equal(empty.data.stale,true);
  env.db.prepare('UPDATE devices SET pair_expires_at=0 WHERE id=?').run(a.id);
  assert.equal((await api(env,'/v1/pair/claim','POST',{pair_code:pair.data.pair_code,read_token:reader})).status,403);
  assert.equal((await api(env,`/admin/devices/${a.id}`,'DELETE',undefined,'bad')).status,401);
  await api(env,`/admin/devices/${a.id}`,'DELETE',undefined,env.ADMIN_TOKEN);
  assert.equal((await api(env,'/v1/status','GET',undefined,reader)).status,401);
  assert.equal((await api(env,'/v1/status','PUT',status,a.token)).status,401);
  env.db.close();
});
test('reject invalid state, oversized requests, missing admin secret and rate abuse', async () => {
  const env=environment(), pc=await activate(env);
  assert.equal((await api(env,'/v1/status','PUT',{...status,state:'click'},pc.token)).status,400);
  assert.equal((await api(env,'/v1/activate','POST',{code:'x'.repeat(5000)})).status,413);
  env.ADMIN_TOKEN='';
  assert.equal((await api(env,'/admin/codes','POST',{})).status,503);
  env.IP_LIMIT={limit:async()=>({success:false})};
  assert.equal((await api(env,'/v1/info')).status,429);
  env.db.close();
});
