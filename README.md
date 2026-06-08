# Sub2 Monitor

用于监控为 `sub2api` 提供密钥的各个中转平台信息。项目是单体部署形态：一个 Python/FastAPI 服务同时提供后端 API 和 Vue3 + Element Plus 前端页面。

## 技术栈

- 后端：FastAPI、SQLAlchemy、SQLite、Argon2 密码哈希
- 前端：Vue3、Vite、TypeScript、Element Plus、Pinia、Vue Router
- 鉴权：服务端会话、HttpOnly Cookie、CSRF Token、登录后才能访问所有业务 API 和前端页面
- Python 管理：uv

## 初始化

```powershell
cd E:\study\Sub2\sub2-monitor
Copy-Item .env.example .env
# 编辑 .env，至少修改 SUB2_MONITOR_SECRET_KEY 和 SUB2_MONITOR_BOOTSTRAP_PASSWORD
uv sync
cd frontend
npm install
```

首次启动时，如果数据库里没有用户，会自动创建 `.env` 中的 `SUB2_MONITOR_BOOTSTRAP_USERNAME` 用户。

## 开发运行

后端：

```powershell
cd E:\study\Sub2\sub2-monitor
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端开发服务器：

```powershell
cd E:\study\Sub2\sub2-monitor\frontend
npm run dev
```

访问 `http://localhost:5173`。Vite 会把 `/api` 请求代理到后端。

## 单体部署运行

```powershell
cd E:\study\Sub2\sub2-monitor\frontend
npm run build
cd ..
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问 `http://服务器IP:8000`，FastAPI 会直接托管 `frontend/dist`。

## Docker 外挂配置

Docker 部署会读取容器内 `/app/config/config.yaml`。在服务器部署目录中，对应宿主机路径是：

```bash
/app/sub-monitor/config/config.yaml
```

`/app/sub-monitor/update.sh` 会在首次执行时创建 `config/` 目录，并在缺少配置文件时从
`config.example.yaml` 复制模板。已有 `config/config.yaml` 不会被覆盖。

当前外挂配置先预留 Sub2API PostgreSQL 连接，供后续数据修改功能复用：

```yaml
sub2api:
  database:
    host: "sub2api-postgres"
    port: 5432
    user: "newapi"
    password: "change-this-database-password"
    dbname: "newapi"
    sslmode: "disable"
    connect_timeout_seconds: 5
```

服务启动后，登录 monitor 后可用只读接口检查配置和连通性：

```bash
GET /api/sub2api/database/status
GET /api/sub2api/database/status?test=false
```

接口会脱敏返回 DSN；`test=true` 只执行 `select current_database(), current_user, version()`。

## 当前已实现

- 登录、退出、获取当前用户
- 所有业务 API 需要登录
- CSRF 防护用于登录、退出、写操作
- 平台基础信息 CRUD
- 平台监控快照接口预留
- 仪表盘统计接口
- Sub2API PostgreSQL 外挂配置和只读连通性检查接口

## Sub2API 监控配置

新增平台时选择 `Sub2API`，在“站点地址”填目标 Sub2API 的 base URL，例如
`https://example.com`、`https://example.com/sub2` 或 `https://example.com/api/v1`。
监控服务会自动归一化到 `/api/v1`。

添加账号余额监控时，“登录账号”填写 Sub2API 用户邮箱，“登录密码”填写用户密码；
“平台账号 ID”可填 `me` 或邮箱。采集时会调用：

- `POST /api/v1/auth/login`，请求体为 `email`、`password`
- `GET /api/v1/usage/dashboard/stats` 获取总消耗
- `GET /api/v1/keys?page=1&page_size=100` 作为 API Key 配额兜底
- `GET /api/v1/groups/available` 获取可用分组
- `GET /api/v1/groups/rates` 获取用户专属分组倍率覆盖

如果目标账号启用了 TOTP 2FA，当前自动采集不支持二次验证码。

## GitHub Actions

仓库包含 `.github/workflows/ci.yml`，在推送到 `main` / `master` 或提交 Pull Request 时会自动执行：

- 后端 `uv run ruff check app`
- 前端 `npm ci`
- 前端 `npm run build`
