# Windows 部署步骤

## 1. 前置条件

- Windows 10/11
- Python 3.11、3.12、3.13 或 3.14（建议 64 位）
- 所启用数据源需要的 API Key
- 每日任务触发时计算机处于开机状态

项目默认时区为 `Asia/Taipei`。Windows 计划任务使用系统时区，请按所在地修改 `config/settings.yaml`。

## 2. 安装环境

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

脚本创建 `.venv`、安装依赖、复制 `.env.example` 并校验基础 YAML。真实密钥只写入本地 `.env`。

安装脚本会优先使用 Python Launcher，并自动选择本机最高的受支持版本；没有 `py` Launcher 时会检查 PATH 中的 `python`。也可以明确指定版本：

```powershell
.\scripts\setup.ps1 -PythonVersion 3.12
```

如果已有 `.venv` 损坏、版本低于 3.11、高于 3.14，或与指定版本不一致，脚本会停止并显示修复命令。需要重建时：

```powershell
.\scripts\setup.ps1 -PythonVersion 3.12 -RecreateVenv
```

旧环境会被重命名为 `.venv_backup_时间戳_进程号`，不会被删除。安装仅使用预编译 wheel，不需要 Microsoft C++ Build Tools。

基础安装不包含 Playwright。只有启用实验性 WoS 浏览器模式时才安装：

```powershell
.\scripts\setup.ps1 -WithPlaywright
```

安装后可运行安全诊断；它只显示凭据是否配置，不显示密钥内容：

```powershell
.\.venv\Scripts\python.exe run.py doctor
```

## 3. 创建研究主题

```powershell
.\.venv\Scripts\python.exe run.py configure-search
```

建议先使用 Guided 模式：

1. 为主题设置稳定的英文 ID，例如 `climate_health`；
2. 为每个核心概念建立一组同义词，同组按 `OR`、不同组按 `AND` 组合；
3. 添加缩写歧义或明确无关的排除词；
4. 查看向导生成的 WoS 和非 WoS 查询；
5. 将主题设为当前活动主题。

例如“海岛种子性状”可建立“种子性状”和“海岛”两个概念组，并分别输入 `seed trait; seed functional trait` 与 `island; insular; archipelago`。每组术语用英文分号分隔。新主题首次默认回溯 90 天，日常默认 14 天，向导中可以调整。

本地主题位于 `config/profiles/local/`，不会上传 Git。可用以下命令检查：

```powershell
.\.venv\Scripts\python.exe run.py profiles list
.\.venv\Scripts\python.exe run.py profiles show climate_health
.\.venv\Scripts\python.exe run.py profiles validate climate_health
```

## 4. 配置数据源

在 `.env` 按需填写：

```dotenv
ELSEVIER_API_KEY=your_key
ELSEVIER_INST_TOKEN=
OPENALEX_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
WEBOFSCIENCE_API_KEY=
LITERATURE_USE_SYSTEM_PROXY=false
```

ScienceDirect 是默认必需源。OpenAlex、Semantic Scholar 和 WoS 缺少 Key 时会明确跳过；Crossref、Europe PMC/NCBI PubMed 不要求项目级 Key。

默认直连学术 API。只有代理已验证可以保留认证头并正常访问接口时，才设置 `LITERATURE_USE_SYSTEM_PROXY=true`。

## 5. 首次试运行

```powershell
.\scripts\run_daily.ps1 -Profile climate_health -NoDelivery
```

首次运行是否采用较长时间窗，以数据库中是否已经有文献为准；仅创建了空数据库仍会使用首次回溯天数。需要临时扩大范围时可覆盖本次运行，且不会改写主题 YAML：

```powershell
.\scripts\run_daily.ps1 -Profile climate_health -LookbackDays 365 -NoDelivery
.\.venv\Scripts\python.exe run.py --profile climate_health run --lookback-days 365 --no-delivery
```

检查主题独立目录中的：

```text
Literature_Monitor_Data/climate_health/database/literature.db
Literature_Monitor_Data/climate_health/exports/climate_health_master.xlsx
Literature_Monitor_Data/climate_health/papers/YYYY/MM/YYYY-MM-DD_climate_health/report/Daily_Report.md
Literature_Monitor_Data/climate_health/logs/
```

`run_summary.json` 中应包含正确的 `profile_id`、`profile_name`、数据源状态、`lookback_days`、`lookback_reason` 和筛选诊断。每次运行还会保存 `report/history/<run_id>.md` 与 `.json`，所以同日重复运行不会丢失早先结果。

## 6. 安装每日任务

```powershell
.\scripts\install_scheduled_task.ps1 -Profile climate_health -DailyAt "08:00"
```

任务名默认为 `Literature Monitor - climate_health`。不同主题可分别安装不同时间的任务。任务采用当前用户、受限权限、错过后尽快启动、禁止同一任务并发运行，并设置两小时上限。

## 7. 桌面文献卡片

```powershell
.\scripts\install_desktop_widget.ps1 -Profile climate_health
.\scripts\show_daily_widget.ps1 -Profile climate_health
```

卡片使用 Microsoft Edge app 模式，展示该主题最新日报及最近几期历史报告。窗口不会定时轮询；流水线会重建页面，已打开窗口可手工刷新。

## 8. WoS 可选模式

默认 `config/sources.yaml` 使用 `wos.mode: api` 和 Starter API。

手工导入模式：

1. 将 `wos.mode` 改为 `manual_import`；
2. 执行：

   ```powershell
   .\scripts\import_wos_export.ps1 -Profile climate_health -Path "E:\path\to\savedrecs.txt" -RunAfterImport
   ```

实验性浏览器模式：

1. Windows 11+ 执行 `.\scripts\setup.ps1 -WithPlaywright`；
2. 将 `wos.mode` 改为 `playwright`；
3. 执行 `.\scripts\initialize_wos_login.ps1 -Profile climate_health`；
4. 在专用 Chrome 窗口人工完成机构登录。

实验性浏览器模式按照 Playwright 当前官方要求标注为 Windows 11+。Windows 10 请使用 WoS API 或手工导入。项目不保存 SSO 密码，也不处理 CAPTCHA/MFA。

## 9. 消息投递

默认 `delivery.channel: local`。飞书和 Telegram 配置：

- 飞书：在 `.env` 设置 `FEISHU_WEBHOOK_URL`，将 channel 改为 `feishu`；
- Telegram：设置 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`，将 channel 改为 `telegram`。

先用 `-NoDelivery` 验证日报，再开启外部投递。

## 10. 维护与排错

```powershell
# 重新导出某主题 Excel
.\scripts\export_excel.ps1 -Profile climate_health

# 校验主题
.\.venv\Scripts\python.exe run.py profiles validate climate_health

# 检查 Python、依赖、主题、凭据状态和输出目录
.\.venv\Scripts\python.exe run.py doctor

# 完整测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

- `missing ELSEVIER_API_KEY`：检查根目录 `.env`；
- ScienceDirect 401/403：检查 Key、接口授权和机构 Token；
- `missing OPENALEX_API_KEY`：填写 OpenAlex Key 或从数据源列表禁用 OpenAlex；
- WoS 缺少 Key：填写标准变量 `WEBOFSCIENCE_API_KEY`；历史错误拼写仍兼容；
- Excel 被占用：关闭 Excel 后重新导出，或使用生成的 `_pending.xlsx`；
- 找不到主题：运行 `profiles list`，再指定 `-Profile` 或重新设置活动主题；
- 高级 WoS 式无法转换：为 `query.portable_queries` 添加供非 WoS 来源使用的查询。
- Python 3.14 安装时出现 `greenlet` 或 C++ 编译错误：确认使用最新版代码，然后重新运行基础安装；Playwright 已从核心依赖移出，需要时用 `-WithPlaywright` 安装；
- 日报显示有候选但“主题筛选后”为 0：这不是重复入库。检查 `run_summary.json` 的 `filter_summary.missing_concept_groups` 和同目录 `metadata/rejected.json`；概念组计数允许重叠，因此各组数量之和可能大于拒绝总数；
- 小众主题首次没有结果：先用 `-LookbackDays 365` 做单次历史验证，再根据 `rejected.json` 调整概念组或排除词。
