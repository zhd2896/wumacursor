<<<<<<< HEAD
# 弈智五马：启动与开发手册

微信原生小程序（TypeScript）+ FastAPI + MySQL 的五马棋项目。棋规和 AI 搜索位于 `miniprogram/domain/`、`miniprogram/ai/`；后端通过 Node worker 调用同一引擎，并将联网棋局、复盘、教练提示和训练记录保存到 MySQL。

本项目的提交内容见 [更新记录](CHANGELOG.md)。完整的 FastAPI、Node Worker、MySQL 与 Nginx 容器部署步骤见 [Docker 部署手册](docs/deployment.md)；本手册继续说明本机开发流程。

> 根目录没有 `start`/`dev` 脚本：前端在**微信开发者工具**中编译运行，API 用 **Uvicorn** 启动。本手册以当前仓库代码为准。

## 功能与依赖

| 入口 | 需要后端和 MySQL | 当前行为 |
| --- | --- | --- |
| 首页、本地双人对弈 | 否 | 本地双人模式使用真实棋规；棋局和走棋状态保存在本机，可从历史记录继续。 |
| AI 对弈、远程双人 | 是 | AI 棋局关联匿名设备账号；远程双人支持私人房间和公开匹配，两台设备各执一方。 |
| AI 对弈中的局面分析、分级教练提示 | 是 | 引擎计算分析；教练文字可选用 LLM，未配置时使用确定性文案。 |
| 已结束棋局的复盘、复盘解说、训练题 | 是 | 复盘基于保存的棋步；训练题从复盘中的失误生成。首次生成复盘可能较慢。 |
| 历史记录 | 浏览本机记录不需要；查询账号云端历史、继续云端棋局和打开复盘需要 | 展示本机记录及当前匿名设备账号的云端棋局；进行中的棋局可继续，已结束的云端棋局可进入复盘。清除本机凭证后无法找回原账号，当前不支持跨设备找回。 |
| 独立的局面分析、AI 教练、我的棋力页面 | 云端局面分析、AI 教练和我的棋力需要；本地局面分析不需要 | 独立局面分析读取真实本地存档或云端权威版本，本地断网仍可分析；AI 教练绑定当前 AI 棋局并按权威版本逐级请求真实提示；我的棋力展示真实账号统计，六维能力指标因缺少评分公式显示“数据不足”。 |

## 环境准备

- Node.js **24+**、npm（后端 Node worker 需要 Node 24 的 TypeScript 运行能力）。
- Python **3.12+**、MySQL **8**（随仓库提供的 Compose 文件使用 MySQL 8.4）。
- 微信开发者工具；可选装 Docker Desktop 和 Docker Compose 来启动开发数据库。
- 以下命令在**仓库根目录**执行，示例终端为 Windows PowerShell。macOS/Linux 把虚拟环境的 Python 路径换为 `backend/.venv/bin/python`，环境变量改用 `export NAME=value`。

```powershell
node --version
npm --version
python --version
docker compose version # 仅 Docker 方案需要
```

## 本地完整启动（PowerShell）

### 1. 安装依赖

```powershell
npm ci
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

`npm ci` 按 `package-lock.json` 安装开发依赖。小程序由微信开发者工具编译，无须运行 `npm start`。

### 2. 启动 MySQL

**Docker 方案**：在同一个 PowerShell 窗口设置本地开发密码并启动容器；请替换示例密码。

```powershell
$env:DB_PASSWORD = 'replace-with-local-password'
$env:DB_ROOT_PASSWORD = 'replace-with-local-root-password'
docker compose -f backend/docker-compose.mysql.yml up -d
docker compose -f backend/docker-compose.mysql.yml ps
```

Compose 创建数据库 `wuma` 和同名用户，并映射到本机 `3306` 端口。首次启动要等 MySQL 就绪再执行迁移。若本机已有 MySQL 8，可跳过 Docker，提前创建数据库 `wuma` 和有权访问该库的用户，并设置下面的连接变量。

| 变量 | 默认值 / 用途 |
| --- | --- |
| `DB_HOST` | `127.0.0.1` |
| `DB_PORT` | `3306` |
| `DB_USER` | `wuma` |
| `DB_PASSWORD` | 无默认密码；Docker 方案须与创建容器时的密码一致。 |
| `DB_NAME` | `wuma` |
| `DATABASE_URL` | 可选的完整 `mysql+pymysql://...` 连接串；**设置后覆盖上述 `DB_*` 变量**。 |

配置样例在 `backend/.env.example`。后端**不会自动读取** `.env` 文件；请在迁移与启动后端的终端中设置环境变量，或通过自己的进程管理器注入。PowerShell 的 `$env:` 变量只在当前终端会话及其子进程中有效。不要把密码提交到仓库。

### 3. 迁移数据库并启动 API

继续使用设置了 `DB_PASSWORD` 的终端：

```powershell
.\backend\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

第二条命令会持续运行，保留此终端。若改用已有 MySQL，先在此终端设置匹配的 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`；若设置了 `DATABASE_URL`，请确认它指向**开发库**。当前迁移最终版本为 `0010_personal_history_indexes`。

在另一 PowerShell 窗口确认引擎和数据库都可用：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/game `
  -ContentType 'application/json' `
  -Body '{"first_player":"A","mode":"LOCAL"}'
```

`/health` 只检查 Node 引擎；第二条命令实际创建棋局，可同时检查 MySQL 写入。交互式接口文档：<http://127.0.0.1:8000/docs>。

### 4. 在微信开发者工具中运行

1. 导入**仓库根目录**，即含 `project.config.json` 的目录；其中已指定 `miniprogramRoot: "miniprogram/"` 和 TypeScript 编译插件。
2. 在开发者工具中使用可用的测试/自有 AppID。仓库配置带有现成 AppID；无使用权限时，在工具内切换自己的 AppID。
3. 确认开发环境的 API 地址为 `miniprogram/config/api.ts` 中的 `http://127.0.0.1:8000`，然后点击“编译”。本地调试若遇请求域名校验，检查开发者工具的“不校验合法域名”设置；仓库项目配置的 `urlCheck` 为 `false`。
4. 从首页进入“AI 对弈”或“远程双人”检查接口链路；“双人对战”可只用前端运行。远程双人可创建私人房间并分享 8 位房间码，另一台设备加入后各执一方；也可使用“匹配对手”。联机终局目前从历史查看终局棋盘；AI 对弈终局可进入真实复盘并生成训练题。

`127.0.0.1` 只适用于**运行后端的同一台电脑上的开发者工具模拟器**。真机、体验版和正式版需要可访问的 HTTPS API、微信小程序后台的合法 request 域名配置，并修改 `miniprogram/config/api.ts` 中相应地址。`trial` 使用 `test` 地址，`release` 使用 `production` 地址；两者当前都是空字符串，未配置就会报 `API base URL is not configured`。若后端和模拟器不在同一台电脑，也要把 `development` 地址改成模拟器可访问的地址。

远程双人席位凭证由服务端签发，只保存在建房/加入时使用的设备上；本机历史可恢复该设备持有的席位。清除小程序本机数据后无法仅凭房间码认领旧席位。两台真机验收前必须先配置两台设备都可访问的 HTTPS API，并将测试后端连接到已迁移的独立 `*_test` MySQL 库；本机 `127.0.0.1` 地址无法完成真机联机验收。阶段结果见 [远程双人验收记录](docs/remote-multiplayer-acceptance.md)。

## 可选的 LLM 解说与教练提示

不配置 LLM 也能运行棋局、复盘与训练；复盘解说和教练提示会使用后端的确定性回退文案。要接入兼容 OpenAI Chat Completions 的服务，在**后端进程启动前**设置：

```powershell
$env:LLM_API_KEY = 'your-key'
$env:LLM_BASE_URL = 'https://your-provider.example/v1'
$env:LLM_MODEL = 'your-model'
```

后端会在 `LLM_BASE_URL` 后追加 `/chat/completions`。可选变量 `LLM_PROVIDER`、`LLM_TIMEOUT_SECONDS`、`LLM_TOTAL_TIMEOUT_SECONDS`、`LLM_TEMPERATURE` 的示例见 `backend/.env.example`。密钥只放在后端环境中。请求失败、超时或结果校验失败时仍会回退到确定性文案。

## 检查与测试

在仓库根目录运行：

```powershell
npm run typecheck
npm run check
npm test
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
```

后端测试中的真实 MySQL 用例只有设置 `WUMA_TEST_DATABASE_URL` 后才运行。该 URL 必须指向**已迁移、名称以 `_test` 结尾的独立 MySQL 库**；不设置时这些用例会跳过。不要把开发库或生产库当作测试库。

微信开发者工具自动化 E2E 需开启工具的自动化接口。`npm run test:e2e:history` 只验证本地双人历史，并在结束时恢复原本机历史存储；设置 `WUMA_WECHAT_AUTO_ENDPOINT`（默认 `ws://127.0.0.1:9420`）后即可运行。其他 E2E 还需启动后端并连接隔离测试库：设置 `WUMA_TEST_DATABASE_URL`，必要时设置 `WUMA_PYTHON`，再按需运行 `npm run test:e2e:wechat`、`npm run test:e2e:review`、`npm run test:e2e:llm-review`、`npm run test:e2e:coach` 或 `npm run test:e2e:training`。这些脚本会创建并检查真实棋局数据，不适合连接日常开发库。

历史页到复盘页的隔离验收使用 `npm run test:e2e:history-review`。先将 `WUMA_TEST_DATABASE_URL` 指向已迁移的独立 `*_test` MySQL 库、让小程序所用后端连接同一库，并设置 `WUMA_HISTORY_E2E_GAME_ID` 为该库中一局已经结束的服务器 `LOCAL` 棋局 ID。脚本先比较测试库与后端返回的棋局状态，再从历史页导入并打开真实复盘；结束时恢复原本机历史与活动棋局 ID。未提供这些变量时脚本不会创建棋局或修改本机存储。

首页复盘卡片的无可复盘棋局状态可运行 `npm run test:e2e:home-review`：脚本在微信开发者工具中完成一局真实本地双人对局，确认它保留在普通历史、但不会误入只显示 AI/服务器终局的复盘列表，随后恢复本机存储。`test:e2e:history-review` 还会从首页实际点击复盘卡片，再验证服务器终局的复盘链路。

搜索与自对弈基准的命令和数据口径见 [Benchmark 指南](docs/phase25-benchmark.md)；最近性能优化验收见 [PHASE 26 报告](docs/phase26-performance.md)。

## 常见问题与停止服务

| 现象 | 检查方法 |
| --- | --- |
| `docker` 命令不存在或 3306 端口被占用 | 安装/启动 Docker Desktop，或改用已有 MySQL；若已有服务占用 3306，调整 Compose 端口映射并同步设置 `DB_PORT`。 |
| 迁移报连接失败、访问被拒绝 | 等待 MySQL 就绪；确认当前终端中的 `DB_PASSWORD` 与容器创建时一致；检查是否有旧的 `DATABASE_URL` 覆盖 `DB_*`。已创建的数据卷不会因修改环境变量而重置用户密码。 |
| `/health` 返回 503 或 `ENGINE_UNAVAILABLE` | 检查 `node --version` 是否为 24+，以及 `backend/engine_worker.mjs` 能被后端读取；后端可用 `WUMA_NODE_EXECUTABLE` 指定 Node 可执行文件。 |
| `/health` 正常但创建棋局失败 | 检查 MySQL 连接、数据库迁移和后端日志；健康检查本身不验证数据库。 |
| 小程序请求失败 | 确认 Uvicorn 正在运行，地址与端口和 `miniprogram/config/api.ts` 一致，并检查开发者工具的请求域名设置。真机不能用 `127.0.0.1` 连接电脑上的 API。 |
| 独立复盘页提示缺少棋局，AI 教练提示没有当前棋局，或训练页没有题目 | 从历史记录中选择**已结束的后端棋局**进入复盘；生成复盘后在复盘页创建训练题。独立局面分析可从本地或云端对局的“分析”入口打开；AI 教练需要先开始或恢复一局轮到玩家落子的 AI 对弈。 |

停止 API：在运行 Uvicorn 的终端按 `Ctrl+C`。停止 Docker 开发数据库：

```powershell
docker compose -f backend/docker-compose.mysql.yml down
```

此命令保留数据库卷，供下次启动继续使用。

## 目录索引

| 目录 / 文件 | 内容 |
| --- | --- |
| `miniprogram/` | 微信小程序页面、棋规、AI、组件与 API 客户端。 |
| `miniprogram/config/api.ts` | 开发、体验、正式环境的 API 地址。 |
| `backend/app/` | FastAPI 路由、服务、MySQL 持久化。 |
| `backend/engine_worker.mjs` | 后端到 TypeScript 棋规/AI 的 Node 桥接进程。 |
| `backend/alembic/` | 数据库迁移。 |
| `backend/.env.example` | 后端环境变量样例；不会自动加载。 |
| `scripts/`、`tests/`、`backend/tests/` | 检查、自动化、基准与测试。 |
| `docs/`、`results/` | 阶段说明与基准实验结果。 |

后端接口、数据存储及复盘说明见 [后端文档](backend/README.md)。
=======
# wumacursor
>>>>>>> b2428e73bce704755dda60b5fac64160029f748b
