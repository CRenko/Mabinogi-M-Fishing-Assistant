# 手机远程查看（预备功能，暂不开放）

按当前安排先保存代码，不部署、不发布。电脑设置入口已隐藏，也不会读取远程凭据、创建上报线程或发送远程状态；之前测试保存过开启设置也不会自动恢复。正式版本仍为 0.6.4。

Android、中转服务、桌面接入与测试代码均保留。以后继续开发时，由维护者在 `fishing_assistant/constants.py` 中将 `REMOTE_PREVIEW_ENABLED` 改为 `True`，才能显示桌面测试入口。此开关不是普通用户设置，暂不随正式版本开启。下面的连接步骤仅适用于重新开启后的开发测试；待验收项见 [验证记录](VERIFICATION.md)。

电脑继续负责钓鱼，手机只查看状态。远程开关默认关闭；不需要激活码也能照常使用本地钓鱼。

目前已经有桌面接入、Android 测试端和中转源码。官方中转地址尚未填写，需要项目维护者部署后才能开放试用。不要把未部署的地址当作可用服务发给用户。

## 用户怎么连接

1. 电脑助手：设置 → 手机远程查看，输入中转管理员给的激活码。自建服务先勾选“使用自建中转”，填入 HTTPS 地址。
2. 打开状态上报，再生成配对二维码。生成新二维码会撤销旧手机的访问权限。
3. 手机端：设备 → 扫描配对二维码。核对中转地址，选择是否“记住此设备”，再点连接。
4. 不勾选只保留本次连接；退出应用或进程被系统结束后需要重新扫码。勾选后会加密保存，下次自动连接。

手机可查看校准、运行状态、模式、版本和停止原因。电脑每 60 秒上报，手机只在前台每 60 秒查询，手动刷新也受频率限制。状态可能延迟约 1～2 分钟，超过 3 分钟会标记过期。网络错误与电脑停止分开显示，电脑识别事件长时间不更新也会单独提示。

首版没有远程按键、自动清理控制、截图上传或锁屏即时推送。网络故障不会停止本地钓鱼。暂停上报后，手机暂时显示最后一次收到的状态，而不是立即知道关闭了上报。

## 激活码与自建中转

激活码是中转服务的准入凭证，不是客户端软件锁。开源客户端可以修改，但官方服务仍在服务端校验凭据和名额。

- 默认最多 25 台已激活电脑，每台绑定一部手机。
- 激活码为随机 128 位、一次性兑换，默认 7 天内可兑换；兑换后的设备授权直到管理员撤销。
- 手机二维码包含一次性随机配对码，10 分钟内有效，不包含电脑的上报密钥。
- 上报凭据与读取凭据分开；手机不能发送状态、游戏按键或管理指令。
- 服务只保存凭据的 SHA-256 摘要和最新状态。电脑使用 Windows DPAPI，手机使用 Android Keystore + AES-GCM 保存凭据，不放进普通配置、备份或诊断 ZIP。
- 手机“忘记此设备”删除本机连接；电脑“解除手机绑定”才会让旧手机密钥立即失效。
- 自建服务实现同一套 [接口协议](PROTOCOL.md) 即可。当前提供的中转也由自建管理员发码，官方激活码不能在另一个中转通用。

二维码含临时访问凭证，请勿截图公开。扫描外部二维码时要核对地址，不会仅凭扫描就自动连接陌生中转。

## 部署中转

需要维护者自己的 Cloudflare 账号。以下命令会创建云端资源，请确认只使用 Workers Free，不要为此开启付费套餐。

```powershell
cd remote/relay
npm ci
npx wrangler login
npx wrangler d1 create fishing-remote
```

将返回的 `database_id` 填入 `wrangler.jsonc`；不要把 Cloudflare API Token 写进代码。`MAX_DEVICES` 默认为 25。

```powershell
npx wrangler d1 migrations apply fishing-remote --remote
npx wrangler secret put ADMIN_TOKEN
npx wrangler deploy
```

`ADMIN_TOKEN` 使用密码管理器生成的至少 32 字符随机字符串。只交给管理人员，不能放进 APK、二维码、README 或 Git。

部署并用不同网络实测后，将官方 HTTPS 地址填入电脑端 `fishing_assistant/remote.py` 的 `OFFICIAL_RELAY_URL`。Android 会从二维码读取实际服务地址，`app/build.gradle` 也预留了 `OFFICIAL_RELAY` 字段。

### 发码与撤销

工具会从环境变量 `OK_REMOTE_ADMIN_TOKEN` 读取管理密钥。请在自己的终端安全设置，不要把真实密钥贴进 issue 或提交到仓库。

```powershell
node scripts/admin.mjs issue https://你的服务.workers.dev 5 7
node scripts/admin.mjs list https://你的服务.workers.dev
node scripts/admin.mjs revoke https://你的服务.workers.dev 设备ID
```

`issue` 后两个参数分别是数量和兑换有效天数。生成的激活码只显示这一次，妥善保存并私下分发；服务端不保留明文。`revoke` 会立即撤销该电脑及其手机访问，删除云端最近状态，但不会改变用户的本地钓鱼。

### 免费额度

按 25 人、一台电脑和一部手机、每分钟各请求一次估算，全天约 72,000 次 Worker 请求。上报约 36,000 次状态行更新；凭据、索引、管理操作也有少量开销，需要观察实际使用量。

免费账户的额度是整个账户共享，不是每个项目单独分配。限流能减少误操作，不能保证挡住所有恶意请求；无效请求也会消耗 Worker 调用额度。建议先 2～3 人测试，再逐步放到 25 人。不要在这个服务保存录像或长期历史。

官方额度：[Workers](https://developers.cloudflare.com/workers/platform/limits/)、[D1](https://developers.cloudflare.com/d1/platform/pricing/)。超额时远程查看会暂时不可用，不要为了恢复测试直接开通付费套餐。

## 本地测试与 Android 构建

### 中国大陆直连

客户端扫码使用本地 ZXing，不依赖 Google Play 服务。状态查询与 GitHub 更新检查分开执行，更新连接失败不会阻塞状态查询。

免费额度不等于国内网络可用性。Cloudflare China Network 是另行订阅的企业服务；不能据此推断免费 workers.dev 在大陆能稳定访问。EdgeOne 的平台项目域名也有区域和临时预览限制，不能直接视为稳定的免费国内入口。

部署前在电脑和手机设置里点“测试中转连接”，测试时关闭系统代理 / VPN；还应分别使用手机流量、家庭宽带测试。客户端测试只说明当前这条网络通路，不代表全国运营商都能访问。

维护者尚需确定国内可达的 HTTPS 入口；如改用其他平台，必须保留一次性兑换和人数限制的原子性，不能把 SQLite 随意改成不支持原子操作的 KV。官方地址在实际验证前保持空白。APK 可以通过其他下载渠道分发，但须使用同一维护者签名；当前手机更新源仍是 GitHub，国内网络下可能检查失败，可关闭自动检查。

参考：[Cloudflare China Network](https://developers.cloudflare.com/china-network/)、[EdgeOne 域名规则](https://edgeone.cloud.tencent.com/pages/document/175191784523485184)。

### 开发命令

```powershell
# 无需云账号：真实接口逻辑 + 内存 SQLite
cd remote/relay
npm test
# 只打包校验，不部署
npx wrangler deploy --dry-run

# 项目根目录
.\.venv\Scripts\python.exe -m unittest discover -s tests -q

# Android：JDK 17+、Android SDK 36
cd remote/android
.\gradlew.bat testDebugUnitTest assembleDebug
```

Android 工程可直接用 Android Studio 打开。测试 APK 在 `remote/android/app/build/outputs/apk/debug/app-debug.apk`；这是独立包名的开发版，不要作为正式更新附件发布。正式发布需要维护者自己的签名密钥，后续版本必须沿用同一密钥。

手机端独立使用 `android-v0.1.0` 形式的 Release 标签。附件命名为 `ok-MabinogiFishing-remote-v0.1.0.apk`。只有含对应 APK 的非草稿、非预发布 Release 才会触发更新弹窗，不会把电脑 EXE 的版本当成手机更新。弹窗显示 Release 正文，允许关闭或前往下载，不静默安装。

第三方组件：二维码生成 [python-qrcode](https://github.com/lincolnloop/python-qrcode)（BSD）、扫码 [ZXing Android Embedded](https://github.com/journeyapps/zxing-android-embedded)（Apache-2.0）及其 ZXing / AndroidX 依赖。
