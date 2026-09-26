# Alpha 雷达：加密货币信息面板

把 X 上的 KOL（赵长鹏、马斯克、链上分析师等）、聪明钱钱包和市场热度这几路数据放在一起，每个币种按四个维度打分，得到一个排好序的**热门币种 / 交易机会榜**。结果展示在一个静态网页上。

```
 X 推文 (KOL) ─┐
 聪明钱钱包 ───┼─> 识别币种/合约 ─> 解析行情 ─> 四维打分 + 风险标记 ─> latest.json ─> 网页面板
 CoinGecko/DEX/币安 热度 ─┘                                   └─> (可选) Claude 中文简报
```

## 快速开始

```bash
pip install -r requirements.txt

# 1) 先用模拟数据看看面板效果（不需要联网，也不需要 Key）
python -m collector --demo
python -m http.server 8000 -d docs      # 打开 http://localhost:8000

# 2) 采集真实数据
export X_BEARER_TOKEN=...        # 可选：X API v2，用来拉 KOL 推文
export ETHERSCAN_API_KEY=...     # 可选：跟踪 EVM 聪明钱钱包
export HELIUS_API_KEY=...        # 可选：跟踪 Solana 聪明钱钱包
export ANTHROPIC_API_KEY=...     # 可选：生成 AI 简报
python -m collector              # 采集一次
python -m collector --loop 15    # 每 15 分钟采集一次（本地常驻）
```

不配置任何 Key 也能用：CoinGecko 热搜、DexScreener 推广榜、币安涨幅榜和恐慌贪婪指数都是免费、无需 Key 的公开接口。每配置一个 Key，就会多一个维度的数据。

## 数据源

| 维度 | 来源 | 需要 |
|---|---|---|
| 社交 KOL | X API v2 用户时间线；也可以用自建 RSSHub（`config.yaml` → `rss_template`） | `X_BEARER_TOKEN`（按量付费）或 RSS |
| 聪明钱 | Etherscan V2 `tokentx`（eth/bsc/base/arbitrum）、Helius SWAP 交易（solana） | `ETHERSCAN_API_KEY` / `HELIUS_API_KEY` |
| 价格动量 | DexScreener 交易对、币安现货（`data-api.binance.vision`） | 免费 |
| 榜单热度 | CoinGecko 热搜、DexScreener Boost（付费推广）、币安 24h 涨幅榜 | 免费 |
| 情绪 | alternative.me 恐慌贪婪指数 | 免费 |

推文里的 `$TICKER`、关键词别名（如“狗狗币”→DOGE）和合约地址（EVM `0x…` / Solana mint）都会被识别，合约地址会通过 DexScreener 解析成币种和行情。

## 打分方法

每个币种有四个维度的分数，范围都是 0–100：

- **社交**：每条提及的分数 = KOL 权重 × 时间衰减（默认半衰期 6 小时）× 互动量加成
- **聪明钱**：有多少个不同的钱包在买，按钱包权重和最近一次买入时间加权
- **动量**：24h 和 1h 涨跌幅。下跌记 0 分
- **热度**：在各个榜单上的排名。付费推广榜只按 0.4 倍计入

**综合分** = 四个维度加权求和 × (1 + 0.1 × (共振维度数 − 1))，然后每个风险标记扣 10%。

**风险标记**：流动性低、新币（上线不到 72 小时）、24h 涨幅超过 80%、FDV/流动性比过高、热度只来自付费推广。

**评级**：
- **重点关注**：综合分 ≥ 55，至少 3 个维度共振，风险标记不超过 1 个
- **观察**：综合分 ≥ 35，至少 2 个维度共振
- **噪音**：其余情况

权重和阈值都在 `config.yaml` 的 `scoring` 里调整。

## 评分历史与提醒

每次采集都会把各币种的得分记进 `docs/data/history.json`（保留最近 96 次，按每 30 分钟一次算约 48 小时）。面板上因此多了三样东西：

- 综合分旁边显示和上一次采集相比的变化（▲/▼），刚上榜的币种标一个「新」
- 展开某一行能看到最近 24 次的评分走势线，虚线是「重点关注」的门槛 55
- 筛选栏里多了「上升/新上榜」，只显示新上榜或者比上次涨了 5 分以上的币种

某个币种**这次刚升级成「重点关注」**时会推送提醒，每次运行最多推 5 条。要开启推送，配置下面任意一种渠道：

| 渠道 | 环境变量 |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` |
| 飞书 / 钉钉 / Discord / Slack 群机器人 | `ALERT_WEBHOOK_URL`（根据网址自动识别是哪家） |

提醒内容：综合分和变化、价格、主要信号、风险，以及行情链接。可以设置 `DASHBOARD_URL`，在提醒里附上面板地址。

第一次运行时还没有历史数据，所以不会推送。某次采集如果所有数据源都失败了，那一次不会写入历史，免得下一次把所有币种都当成新上榜。`--demo` 用的是模拟历史，不会写入 history.json。

## 配置 KOL 与钱包

编辑 `config.yaml`：

- `kols`：已经预置了 CZ、何一、马斯克、Vitalik、Ansem、Lookonchain、余烬、Ai 姨、吴说等账号。可以增删，也可以调 `weight`
- `wallets`：**默认为空**。去 GMGN、Nansen、Arkham、Lookonchain 的盈利榜挑一些地址，自己核实后填进去：
  ```yaml
  wallets:
    - {address: "0x...", chain: eth, label: "ETH 聪明钱 A", weight: 1.0}
    - {address: "...",   chain: solana, label: "SOL Meme 狙击手", weight: 0.8}
  ```

## 自动部署到 GitHub Pages

`.github/workflows/radar.yml` 每 30 分钟采集一次，结果发布到 GitHub Pages：

1. 进入仓库的 Settings → Pages，把 Source 设为 **GitHub Actions**
2. 在 Settings → Secrets and variables → Actions 里添加需要的 Key（包括提醒用的 `TELEGRAM_*`、`ALERT_WEBHOOK_URL`）
3. 在 Actions 页面手动运行一次 “Alpha Radar”

注意：
- GitHub 的定时任务只会在**默认分支**上运行，所以要先把代码合并到 main 才会自动跑。
- Actions 每次运行不会保留上次的文件，评分历史是从已经发布的站点 `<面板地址>/data/history.json` 读回来的。如果用了自定义域名，要在仓库变量里设置 `DASHBOARD_URL`。
- Pages 站点是**公开**的，钱包列表和面板内容所有人都能看到。私有仓库启用 Pages 需要付费套餐。
- X API 按调用量计费：14 个 KOL、每 30 分钟一次，每天大约 700 次请求。可以减少 KOL 数量或降低 cron 频率。
- AI 简报每次运行都会调用一次 Claude API。

## 目录

```
config.yaml              KOL / 钱包 / 打分参数
collector/
  sources/market.py      CoinGecko、DexScreener、币安、恐慌贪婪指数
  sources/x_kol.py       X API v2 / RSS
  sources/wallets.py     Etherscan V2 / Helius
  extract.py             从文本里识别币种和合约地址
  distill.py             四维打分、共振判断、风险标记
  brief.py               Claude 生成的中文简报（可选）
  history.py             评分历史：变化、新上榜、走势、新晋重点关注
  alerts.py              Telegram / 群机器人推送
  demo.py                离线模拟数据
docs/                    静态面板（index.html / app.js / style.css / data/latest.json）
tests/                   单元测试：python -m unittest discover -s tests
```

## 免责声明

本项目只做信息聚合和规则打分。KOL 提及不代表看多，付费推广也不代表项目有价值，新币和低流动性代币的风险极高。**本项目不构成投资建议。**
