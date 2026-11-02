# vps-watch

GitHub Actions 版 VPS 补货监控：每 5 分钟抓一次公开 TG 频道预览和几个官网页面，命中关键词后推 Telegram + 微信 PushPlus。

代码里没有 token，全部走仓库 Secrets：

- `TG_BOT_TOKEN`
- `TG_CHAT_ID`
- `PUSHPLUS_TOKEN`

手动测试：Actions → vps-watch → Run workflow。

注意：定时任务由 GitHub 调度，高峰期可能延迟几分钟；限量款抢购不要依赖它。
