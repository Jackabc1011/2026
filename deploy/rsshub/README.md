# 用 RSSHub 免费获取 KOL 推文

X 官方 API 按调用量收费。[RSSHub](https://github.com/DIYgod/RSSHub) 是一个开源服务，可以用一个已登录 X 账号的 Cookie 把用户时间线转成 RSS。Alpha 雷达的采集器可以直接读取这些 RSS。

> ⚠️ 这种方式实际是用你的 X 账号去抓取数据，不属于 X 官方授权的用法，账号有可能被限流甚至封禁。**请用一个小号**，不要用主号。

## 第 1 步：获取 `TWITTER_AUTH_TOKEN`

1. 用小号在浏览器里登录 x.com。
2. 打开开发者工具（F12），依次进入 Application → Cookies → `https://x.com`。
3. 复制名为 `auth_token` 的那条 Cookie 的值。

这个值就等于账号的登录凭证，**不要泄露**。如果在 X 上退出登录，它会失效，需要重新获取。

## 第 2 步：选一种部署方式

### 方式 A：在 GitHub Actions 里临时运行（推荐，不需要服务器）

每次定时任务开始时启动一个 RSSHub 容器，采集结束后自动销毁。

1. 进入仓库的 Settings → Secrets and variables → Actions：
   - **Secrets** 里添加 `TWITTER_AUTH_TOKEN`
   - **Variables** 里添加 `USE_RSSHUB`，值填 `true`
2. 手动运行一次工作流 “Alpha Radar”，打开面板看数据源状态里 “X / KOL” 是不是 ✓。

说明：
- 如果同时配置了 `X_BEARER_TOKEN`，会优先使用 X 官方 API。
- 每次运行都要重新下载 RSSHub 镜像，会多花大约 30–60 秒。
- 这个容器只在当次任务里能访问，不需要设置访问密钥。

### 方式 B：部署在自己的服务器上

适合本地运行 `python -m collector --loop`，或者想和其他工具共用一个 RSSHub。

```bash
cd deploy/rsshub
cp .env.example .env        # 填入 TWITTER_AUTH_TOKEN 和 ACCESS_KEY（随机长字符串）
docker compose up -d
curl "http://localhost:1200/twitter/user/cz_binance?key=你的ACCESS_KEY" | head
```

然后把地址告诉采集器：

```bash
export RSS_TEMPLATE="https://你的域名/twitter/user/{handle}?key=你的ACCESS_KEY"
python -m collector
```

如果用 GitHub Actions 读取这个服务器，就把同样的地址存进 Secret `RSS_TEMPLATE`。

几点建议：
- 服务器对公网开放时，一定要设置 `ACCESS_KEY`，并在前面加一层 HTTPS 反向代理（比如 Caddy 或 Nginx）。
- `CACHE_EXPIRE=600` 表示同一个账号的时间线 10 分钟内只抓一次，这样可以降低被限流的概率。

## 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 面板提示 “X / KOL ✕”，错误信息里有 401/403 | `auth_token` 失效了，重新登录后再获取一次 |
| 部分 KOL 没有推文 | 这段时间里对方没有发推（默认只看最近 24 小时），或者该账号被限流，可以稍后再试 |
| 推文互动数都是 0 | RSS 里不包含点赞/转发数，这些推文的“社交”分数只按 KOL 权重和发布时间计算 |
