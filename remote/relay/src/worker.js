const TOKEN = /^[a-f0-9]{64}$/;
const CODE = /^[A-F0-9]{32}$/;
const STATES = new Set(['idle', 'paused', 'running', 'waiting_bite', 'ready_to_cast',
  'fish_hooked', 'idle_recovery', 'cleaning', 'stopped', 'unresponsive']);
const REASONS = new Set(['', 'manual', 'inventory_full', 'rod_required', 'retry_limit', 'error']);
const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { 'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' },
});
class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
const fail = (status, code, message) => { throw new ApiError(status, code, message); };
export async function digest(value) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
}
function secret(bytes = 32) {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), b => b.toString(16).padStart(2, '0')).join('');
}
async function body(request) {
  if (!request.headers.get('content-type')?.startsWith('application/json'))
    fail(415, 'json_required', '请使用 JSON 请求');
  // Bound the stream too: Content-Length can be absent or dishonest.
  const reader = request.body?.getReader();
  if (!reader) fail(400, 'invalid_body', '请求内容为空');
  const chunks = []; let size = 0;
  while (true) {
    const {done, value} = await reader.read(); if (done) break;
    size += value.length;
    if (size > 4096) { await reader.cancel(); fail(413, 'too_large', '请求内容过大'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  try {
    const result = JSON.parse(new TextDecoder().decode(bytes));
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error();
    return result;
  } catch { fail(400, 'invalid_body', '请求格式不正确'); }
}
async function limited(binding, key) {
  if (binding && !(await binding.limit({key})).success)
    fail(429, 'rate_limited', '操作过于频繁，请一分钟后再试');
}
async function auth(request, env, role) {
  const token = request.headers.get('Authorization')?.replace(/^Bearer /, '') || '';
  if (!TOKEN.test(token)) fail(401, 'unauthorized', '设备未绑定或已被解除绑定');
  const hashed = await digest(token);
  await limited(env.DEVICE_LIMIT, `${role}:${hashed}`);
  const field = role === 'writer' ? 'write_hash' : 'read_hash';
  const device = await env.DB.prepare(`SELECT * FROM devices WHERE ${field} = ? AND revoked = 0`).bind(hashed).first();
  if (!device) fail(401, 'unauthorized', '设备未绑定或已被解除绑定');
  return device;
}
async function admin(request, env) {
  // Missing secret fails closed. No admin credential is distributed with the clients.
  if (!env.ADMIN_TOKEN || env.ADMIN_TOKEN.length < 32)
    fail(503, 'admin_unconfigured', '尚未配置管理密钥');
  const actual = request.headers.get('Authorization') || '';
  if (await digest(actual) !== await digest(`Bearer ${env.ADMIN_TOKEN}`))
    fail(401, 'unauthorized', '无管理权限');
}
export function cleanStatus(data) {
  if (typeof data.monitoring !== 'boolean' || typeof data.calibrated !== 'boolean' || !STATES.has(data.state))
    fail(400, 'invalid_status', '状态字段不正确');
  if (!['stamina_bounce', 'fixed_delay', 'instant'].includes(data.strategy) ||
      !['ok', 'pixel'].includes(data.recognition) || !REASONS.has(data.reason || ''))
    fail(400, 'invalid_status', '状态字段不正确');
  // Explicit allowlist; never persist extra fields, paths, screenshots, or raw logs.
  return {monitoring: data.monitoring, calibrated: data.calibrated, state: data.state,
    strategy: data.strategy, recognition: data.recognition, reason: data.reason || '',
    version: /^[0-9.]{1,24}$/.test(data.version) ? data.version : '',
    observed_at: Number.isSafeInteger(data.observed_at) && data.observed_at > 0 ? data.observed_at : 0};
}
async function handle(request, env) {
  const url = new URL(request.url), path = url.pathname, method = request.method;
  const now = Math.floor(Date.now() / 1000);
  await limited(env.IP_LIMIT, request.headers.get('CF-Connecting-IP') || 'local');
  if (method === 'GET' && path === '/v1/info')
    return json({protocol: 1, name: env.SERVICE_NAME || 'OK 钓鱼远程查看', activation_required: true, interval_seconds: 60});
  if (path.startsWith('/admin/')) {
    await admin(request, env);
    if (method === 'POST' && path === '/admin/codes') {
      const data = await body(request), count = data.count ?? 1, days = data.days ?? 7;
      if (!Number.isInteger(count) || count < 1 || count > 25 || !Number.isInteger(days) || days < 1 || days > 365)
        fail(400, 'invalid_count', '数量为 1～25，兑换有效期为 1～365 天');
      const codes = Array.from({length: count}, () => secret(16).toUpperCase());
      await env.DB.batch(await Promise.all(codes.map(async code => env.DB.prepare(
        'INSERT INTO devices(code_hash, code_expires_at, created_at) VALUES(?, ?, ?)'
      ).bind(await digest(code), now + days * 86400, now))));
      return json({codes: codes.map(c => c.match(/.{4}/g).join('-')), expires_at: now + days * 86400}, 201);
    }
    if (method === 'GET' && path === '/admin/devices') {
      const result = await env.DB.prepare('SELECT id, revoked, created_at, received_at FROM devices WHERE id IS NOT NULL ORDER BY created_at DESC LIMIT 200').all();
      return json({devices: result.results});
    }
    const revoke = path.match(/^\/admin\/devices\/([a-f0-9-]{36})$/);
    if (method === 'DELETE' && revoke) {
      await env.DB.prepare('UPDATE devices SET revoked=1, read_hash=NULL, pair_hash=NULL, status_json=NULL WHERE id=?').bind(revoke[1]).run();
      return json({ok: true});
    }
    fail(404, 'not_found', '接口不存在');
  }
  if (method === 'POST' && path === '/v1/activate') {
    const data = await body(request), code = String(data.code || '').replace(/[-\s]/g, '').toUpperCase();
    if (!CODE.test(code) || !TOKEN.test(data.write_token || '')) fail(400, 'invalid_code', '激活码格式不正确');
    const hash = await digest(code), tokenHash = await digest(data.write_token);
    const existing = await env.DB.prepare('SELECT * FROM devices WHERE code_hash=?').bind(hash).first();
    if (existing?.id && !existing.revoked && existing.write_hash === tokenHash)
      return json({device_id: existing.id, interval_seconds: 60}); // Lost-response retry.
    if (!existing || existing.revoked || existing.id || existing.code_expires_at < now)
      fail(403, 'code_unavailable', '激活码无效、过期或已被使用');
    const id = crypto.randomUUID(), capacity = Math.max(1, Math.min(1000, Number(env.MAX_DEVICES) || 25));
    // A single SQLite statement serializes capacity checks and code redemption.
    const claimed = await env.DB.prepare(`UPDATE devices SET id=?, write_hash=?
      WHERE code_hash=? AND id IS NULL AND revoked=0 AND code_expires_at>=?
      AND (SELECT count(*) FROM devices WHERE id IS NOT NULL AND revoked=0) < ? RETURNING id`
    ).bind(id, tokenHash, hash, now, capacity).first();
    if (!claimed) fail(409, 'capacity_or_used', '试验名额已满，或激活码已被使用');
    return json({device_id: id, interval_seconds: 60}, 201);
  }
  if (method === 'PUT' && path === '/v1/status') {
    const device = await auth(request, env, 'writer'), status = cleanStatus(await body(request));
    const updated = await env.DB.prepare(`UPDATE devices SET status_json=?, received_at=?
      WHERE id=? AND revoked=0 AND received_at<=? RETURNING id`
    ).bind(JSON.stringify(status), now, device.id, now - 55).first();
    if (!updated) fail(429, 'report_too_soon', '每分钟上报一次即可');
    return json({ok: true, received_at: now, interval_seconds: 60});
  }
  if (method === 'GET' && path === '/v1/status') {
    const device = await auth(request, env, 'reader');
    return json({device_id: device.id, server_time: now, received_at: device.received_at,
      stale: !device.received_at || now - device.received_at > 180,
      status: device.status_json ? JSON.parse(device.status_json) : null});
  }
  if (method === 'POST' && path === '/v1/pair') {
    const device = await auth(request, env, 'writer'), code = secret(24);
    await env.DB.prepare(`UPDATE devices SET pair_hash=?, pair_expires_at=?, read_hash=NULL
      WHERE id=? AND revoked=0`).bind(await digest(code), now + 600, device.id).run();
    return json({pair_code: code, expires_at: now + 600});
  }
  if (method === 'POST' && path === '/v1/pair/claim') {
    const data = await body(request);
    if (!/^[a-f0-9]{48}$/.test(data.pair_code || '') || !TOKEN.test(data.read_token || ''))
      fail(400, 'invalid_pair', '配对链接不正确');
    const hash = await digest(data.read_token);
    const device = await env.DB.prepare(`UPDATE devices SET read_hash=? WHERE pair_hash=?
      AND pair_expires_at>=? AND revoked=0 AND (read_hash IS NULL OR read_hash=?) RETURNING id`
    ).bind(hash, await digest(data.pair_code), now, hash).first();
    if (!device) fail(403, 'pair_unavailable', '配对链接已过期或已使用，请在电脑上重新生成');
    return json({device_id: device.id, interval_seconds: 60});
  }
  if (method === 'POST' && path === '/v1/unpair') {
    const device = await auth(request, env, 'writer');
    await env.DB.prepare('UPDATE devices SET read_hash=NULL, pair_hash=NULL WHERE id=? AND revoked=0').bind(device.id).run();
    return json({ok: true});
  }
  fail(404, 'not_found', '接口不存在');
}
export default {
  async fetch(request, env) {
    try { return await handle(request, env); }
    catch (error) {
      if (error instanceof ApiError) return json({error: error.code, message: error.message}, error.status);
      // Do not return SQL, credentials, request bodies or stack traces to clients.
      return json({error: 'service_unavailable', message: '中转暂时不可用，请稍后再试'}, 503);
    }
  }
};
