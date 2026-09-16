# Literature Monitor Pipeline

[![tests](https://github.com/wuyongxiang34/literature-monitor-pipeline/actions/workflows/tests.yml/badge.svg)](https://github.com/wuyongxiang34/literature-monitor-pipeline/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/wuyongxiang34/literature-monitor-pipeline/releases/tag/v0.1.0)

面向不同科研方向的 Windows 每日文献监测流水线。研究者可以通过中文命令行向导创建多个研究主题，按 Web of Science（WoS）规则生成或填写检索式，再从多个学术数据源检索、去重、筛选、评分和归档文献。

## 项目解决什么问题

科研文献分散在多个数据库中。人工重复检索容易遗漏新文献、积累重复记录，也难以维持稳定的筛选标准。不同科研者的概念、同义词、排除词和关注期刊又各不相同，固定检索式无法复用。

本项目将流程统一为：

```text
研究主题配置
  → WoS 风格检索式和多源查询
  → ScienceDirect / OpenAlex / Crossref / PubMed / Semantic Scholar / WoS
  → 标识符与标题去重
  → 概念组门控和六维评分
  → 只精选本次新增文献
  → SQLite / Markdown / JSON / Excel / 桌面卡片
  → 本地保存或可选消息投递
```

每个研究主题拥有独立数据库和输出目录，不会与其他课题交叉去重。SQLite 是唯一事实源；Excel 只是便于浏览的导出。

## 主要功能

- 交互式创建、更新、列出、查看和校验多个研究主题。
- Guided 模式根据概念组、同义词、排除词和通配符生成 WoS `TS=` 检索式。
- Advanced 模式接受完整 WoS 高级检索式，支持布尔、近邻、字段和年份条件。
- 为非 WoS 来源生成有上限、顺序稳定的可移植查询；复杂高级式要求显式提供替代查询，避免错误翻译。
- 默认接入 ScienceDirect、OpenAlex、Crossref、PubMed、Semantic Scholar 和 WoS；单一补充源失败不会阻断整个流程。
- ScienceDirect 摘要按 Article Retrieval → Scopus Abstract Retrieval → Metadata only 回退。
- DOI、WoS ID、arXiv ID、OpenAlex ID 和标准化标题多级去重并合并元数据。
- 概念组过滤以及主题、方法、期刊、网络、应用和归档六维 100 分评分。
- Markdown 日报、JSON 元数据、SQLite、Excel、归档笔记、日志和 Edge 桌面卡片。
- 本地、飞书 Webhook、Telegram 投递，以及按主题安装 Windows 每日计划任务。

## 安装

### 环境要求

- Windows 10/11
- Python 3.11 或更高版本，`py -3` 可用
- PowerShell
- 可访问所启用学术 API 的网络环境

在项目根目录执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

脚本会创建 `.venv`、安装依赖、创建本地 `.env` 并校验基础配置。

### API Key

先在相应官方入口申请密钥，再编辑根目录下由安装脚本创建的 `.env`：

| `.env` 变量 | 数据源 | 官方申请入口 | 说明 |
| --- | --- | --- | --- |
| `ELSEVIER_API_KEY` | ScienceDirect / Scopus | [Elsevier Developer Portal：创建 API Key](https://dev.elsevier.com/apikey/create) | 注册或登录 Elsevier 账号后创建。基础权限和配额取决于使用场景；完整内容访问通常还取决于所在机构的订阅。 |
| `OPENALEX_API_KEY` | OpenAlex | [OpenAlex：Settings → API key](https://openalex.org/settings/api) | 注册或登录后可取得密钥；官方提供免费用量，更多调用可能按其当前方案计费。 |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar | [Semantic Scholar：API Key 申请表](https://www.semanticscholar.org/product/api#api-key-form) | 提交申请后由官方通过邮件发放。项目未填写时会跳过该数据源。 |
| `WEBOFSCIENCE_API_KEY` | Web of Science | [Clarivate：Web of Science Starter API](https://developer.clarivate.com/apis/wos-starter) | 先注册 Clarivate Developer Portal，再注册应用并订阅 Starter API 方案；官方提供个人试用和机构方案。 |

`ELSEVIER_INST_TOKEN` 不是普通用户公开自助创建的 API Key，仅在 Elsevier API Support 或所在机构向你提供时填写。Crossref 与 PubMed 在当前项目中不要求 API Key。各平台的资格、配额和费用可能调整，请以链接中的官方说明为准。

按下面格式填写：

```dotenv
# 默认必需源
ELSEVIER_API_KEY=your_elsevier_api_key

# 可选来源或增强权限
ELSEVIER_INST_TOKEN=
OPENALEX_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
WEBOFSCIENCE_API_KEY=

# 默认绕过系统代理；仅在代理已验证可用时设为 true
LITERATURE_USE_SYSTEM_PROXY=false

# 仅在启用对应投递方式时填写
FEISHU_WEBHOOK_URL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

项目兼容历史拼写 `WEBOFSCIENDE_API_KEY`，新配置请使用 `WEBOFSCIENCE_API_KEY`。不要把真实密钥写入 YAML 或提交到 Git。

## 设置研究主题

### 命令行向导

```powershell
.\.venv\Scripts\python.exe run.py configure-search
```

向导会询问主题 ID、名称、描述、模式、概念组、同义词和排除词，并将配置写到不会提交 Git 的 `config/profiles/local/`。可选择把新主题设为活动主题。

主题 ID 只允许小写字母、数字、`-` 和 `_`，最长 48 个字符。

### 管理主题

```powershell
# 星号表示当前活动主题
.\.venv\Scripts\python.exe run.py profiles list

# 查看 YAML 和编译后的查询
.\.venv\Scripts\python.exe run.py profiles show climate_health

# 校验指定主题
.\.venv\Scripts\python.exe run.py profiles validate climate_health
```

主题选择优先级为：命令行 `--profile` → `LITERATURE_PROFILE` 环境变量 → 本地活动主题。没有可用主题时程序会停止并提示运行设置向导。

### YAML 示例

```yaml
schema_version: 1

profile:
  id: climate_health
  name: 气候变化与人类健康
  description: 监测气候变化对人类健康影响的研究

query:
  mode: guided
  groups:
    - name: 气候变化
      terms:
        - climate change
        - global warming
        - climat*
    - name: 人类健康
      terms:
        - human health
        - disease*
        - mortality
  exclude:
    - animal model
  advanced_wos: ""
  portable_queries: []
  max_generated_queries: 12

selection:
  final_selection_count: 5
  first_run_lookback_days: 30
  lookback_days: 14

scoring:
  topic_gate: 10
  method_terms: []
  applied_terms: []
  journal_tiers: {}
```

仓库提供 [ES–HWB 示例主题](config/profiles/examples/es_hwb.yaml)，可用于学习或复制，不会在没有选择时自动成为研究方向。

## WoS 检索规则

Guided 模式遵循以下规则：

- 同一概念组的同义词用 `OR`；不同必需概念组用 `AND`；排除词用 `NOT`。
- 多词术语自动加双引号成为精确短语。
- 保留 `*`、`?`、`$` 通配符，并检查 Topic/Title 截词的最少字符数。
- 中文和韩文查询显式写出 `AND`，不依赖隐式逻辑。

上面的 YAML 会生成：

```text
TS=(("climate change" OR "global warming" OR climat*) AND
    ("human health" OR disease* OR mortality))
NOT TS=("animal model")
```

WoS Topic 检索覆盖题名、摘要、作者关键词和 Keywords Plus。详细规则参见 Clarivate 官方的 [Core Collection Search Fields](https://webofscience.help.clarivate.com/en-us/Content/wos-core-collection/woscc-search-fields.htm)、[Search Rules](https://webofscience.help.clarivate.com/en-us/Content/search-rules.htm) 和 [Search Operators](https://webofscience.help.clarivate.com/Content/search-operators.html)。

Advanced 模式可填写完整 WoS 高级检索式。程序检查括号、引号、`NEAR/x`、通配符和明显不适用的 `SAME`，但最终语义仍以 WoS API 为准。若表达式包含非 `TS`/`PY` 字段或近邻运算，并且启用了其他来源，必须填写 `portable_queries`。

## 使用方法

### 安全试运行

```powershell
.\scripts\run_daily.ps1 -Profile climate_health -NoDelivery
```

省略 `-Profile` 时使用活动主题。确认输出后可移除 `-NoDelivery` 执行配置中的正式投递。

### 常用命令

```powershell
# 校验基础配置或指定主题
.\.venv\Scripts\python.exe run.py validate
.\.venv\Scripts\python.exe run.py --profile climate_health validate

# 直接运行
.\.venv\Scripts\python.exe run.py --profile climate_health run --no-delivery

# 重新导出该主题的 Excel
.\scripts\export_excel.ps1 -Profile climate_health

# 运行测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

### 计划任务和桌面卡片

```powershell
.\scripts\install_scheduled_task.ps1 -Profile climate_health -DailyAt "08:00"
.\scripts\install_desktop_widget.ps1 -Profile climate_health
.\scripts\show_daily_widget.ps1 -Profile climate_health
```

计划任务名按主题生成，例如 `Literature Monitor - climate_health`。桌面卡片依赖 Microsoft Edge。

### WoS 模式

`config/sources.yaml` 默认使用 Starter API：

```yaml
wos:
  enabled: true
  mode: api
  api_type: starter
```

也支持：

- `manual_import`：读取主题自己的 WoS inbox。导入命令：

  ```powershell
  .\scripts\import_wos_export.ps1 -Profile climate_health -Path "E:\path\to\savedrecs.txt" -RunAfterImport
  ```

- `playwright`：实验性浏览器模式。先运行：

  ```powershell
  .\scripts\initialize_wos_login.ps1 -Profile climate_health
  ```

浏览器模式不会自动处理 CAPTCHA/MFA。

## 输入输出示例

执行输入：

```powershell
.\scripts\run_daily.ps1 -Profile climate_health -NoDelivery
```

运行摘要结构：

```json
{
  "version": "0.1.0",
  "profile_id": "climate_health",
  "profile_name": "气候变化与人类健康",
  "status": "SUCCESS",
  "search_window": {
    "start": "2026-09-02",
    "end": "2026-09-15"
  },
  "retrieved": 166,
  "deduplicated": 131,
  "eligible": 22,
  "selected": 2,
  "new_records": 2,
  "source_status": {
    "sciencedirect": "ok: 15 records",
    "openalex": "ok: 56 records",
    "crossref": "ok: 60 records",
    "pubmed": "ok: 5 records",
    "semantic_scholar": "skipped: missing SEMANTIC_SCHOLAR_API_KEY",
    "wos": "ok: 30 WoS Core records (Starter API, 106 matched)"
  },
  "delivery": "skipped by --no-delivery"
}
```

默认输出位置：

```text
Literature_Monitor_Data/<profile_id>/
├── database/literature.db
├── papers/YYYY/MM/YYYY-MM-DD_<profile_id>/
│   ├── metadata/candidates.json
│   ├── metadata/selected.json
│   └── report/
│       ├── Daily_Report.md
│       └── run_summary.json
├── exports/<profile_id>_master.xlsx
├── archive/raw/<profile_id>/
├── desktop_widget/latest.html
└── logs/
```

Excel 包含 `Master_Literature`、`Candidates_Unverified`、`Manual_Review`、`Daily_Run_Summary` 和 `Download_Log`。如果 Excel 正被占用，会生成带 `_pending.xlsx` 后缀的导出。

## 数据可信度与边界

- WoS Starter API 记录标为已由 Web of Science Core Collection 确认，但仍是 `Metadata only`。
- ScienceDirect 收录明确标记为不等同于 SCI-EXPANDED 证据。
- 公开元数据来源标为 `Unverified`。
- 方法句和结果句只从已有摘要保守提取；缺少证据时明确提示人工核验。
- 尚未实现 PDF 自动下载、中文摘要翻译和 Word 简报。
- 不保存学校 SSO 或密码，不绕过付费墙，不自动处理 CAPTCHA/MFA。
- API Key、本地研究主题、数据库、WOS 导出、浏览器 Profile、日志和生成报告均被 Git 忽略。

## 开源与贡献

本项目采用 [MIT License](LICENSE)。贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题请按照 [SECURITY.md](SECURITY.md) 私下报告。

更详细的 Windows 部署说明见 [WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md)。
