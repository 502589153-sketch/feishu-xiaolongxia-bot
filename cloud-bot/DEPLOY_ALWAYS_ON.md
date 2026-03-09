# 龙虾常驻部署（电脑关机后继续运行）

下面两种方式都能做到“你电脑关机，龙虾仍在线”。

## 方式 A：云平台（推荐，最省事）

基于 `render.yaml` 部署，平台会给你固定 HTTPS 域名。

1. 把项目推到 Git 仓库。
2. 在 Render 创建 `Blueprint`，选择本仓库。
3. 在服务环境变量里填入：
   - `FEISHU_APP_ID`
   - `FEISHU_APP_SECRET`
   - `FEISHU_APP_VERIFICATION_TOKEN`
   - `FEISHU_OPENAI_API_KEY`
4. 等服务启动完成，拿到 URL，例如 `https://xxx.onrender.com`
5. 飞书后台回调地址填：`https://xxx.onrender.com/feishu/callback`

## 方式 B：你自己的云主机（Docker）

要求：一台 Linux 云主机（常开）+ 公网域名（HTTPS）。

1. 上传项目到云主机。
2. 准备配置文件：
   - `cp .env.feishu.example .env.feishu`
   - 编辑 `.env.feishu` 填入真实密钥
3. 启动：
   - `docker compose -f docker-compose.bot.yml up -d --build`
4. 查看状态：
   - `docker compose -f docker-compose.bot.yml ps`
   - `curl http://127.0.0.1:9000/healthz`

然后把你的反向代理（Nginx/Caddy）指向 `127.0.0.1:9000`，并启用 HTTPS，
飞书回调地址填写 `https://你的域名/feishu/callback`。

## 备注

- 机器人支持平台 `PORT` 环境变量，适配云平台容器运行。
- 如需会话记忆跨重启保留，可设置 `FEISHU_STATE_FILE`（例如 `/data/state.json`）。
