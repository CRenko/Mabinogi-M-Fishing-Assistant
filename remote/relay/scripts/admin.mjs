// Explicit operator tool; ADMIN_TOKEN never appears in command arguments or output.
const [action, origin, first, second] = process.argv.slice(2);
const token = process.env.OK_REMOTE_ADMIN_TOKEN;
if (!token || token.length < 32) throw new Error('请先安全设置 OK_REMOTE_ADMIN_TOKEN（至少 32 字符）');
const url = new URL(origin);
if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/')
  throw new Error('请输入不含路径或参数的 HTTPS 中转地址');
let method, path, body;
switch (action) {
  case 'issue':
    method='POST'; path='/admin/codes';
    body={count:Number(first||1), days:Number(second||7)}; break;
  case 'list': method='GET'; path='/admin/devices'; break;
  case 'revoke':
    if (!/^[a-f0-9-]{36}$/.test(first||'')) throw new Error('请提供要撤销的完整设备 ID');
    method='DELETE'; path='/admin/devices/'+first; break;
  default: throw new Error('用法：admin.mjs issue|list|revoke https://服务地址 [数量或设备ID] [兑换天数]');
}
const response=await fetch(url.origin+path,{method,redirect:'error',signal:AbortSignal.timeout(10000),
  headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
  ...(body?{body:JSON.stringify(body)}:{})});
if(!response.ok) throw new Error(`管理操作失败：HTTP ${response.status}`);
console.log(JSON.stringify(await response.json(),null,2));
