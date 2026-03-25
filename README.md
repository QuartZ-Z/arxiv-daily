# Arxiv Daily 科研动态收集系统（OpenClaw执行规范）

本工作流用于每日自动抓取、筛选并整理 Arxiv 上 AI for Science（尤其是 AI for Materials）方向的论文，并生成中文报告上传至飞书。

---

## 总体执行流程

每日执行以下步骤：

1. 读取配置文件
2. 构造 arXiv 查询语句
3. 抓取论文元数据（增量 + 时间窗口）
4. 数据清洗与去重
5. 规则过滤（初筛）
6. LLM评分（精筛）
7. 选出Top论文
8. 生成中文报告
9. 上传飞书文档
10. 更新状态文件

---

## 目录结构（必须严格遵守）

所有持久化文件必须写入 workspace/arxiv_daily/
临时文件（如中间缓存）可以使用 /tmp/

```plain
arxiv_daily/
├── config.yaml # 配置文件
├── config_private.yaml # 隐私信息配置文件
├── main.py # 主流程入口
├── fetch.py # 抓取模块
├── filter.py # 规则过滤
├── rank.py # LLM评分
├── report.py # 报告生成
├── feishu.py # 飞书上传
├── data/
│ ├── raw/ # 原始抓取数据
│ ├── processed/ # 清洗后数据
│ └── state.json # 状态记录（非常重要）
├── logs/
│ ├── run.log
│ └── error.log
└── outputs/
│ └── report_YYYYMMDD.md
```

---

## 配置文件（config.yaml）

```yaml
keywords:
  - "AI for science"
  - "scientific machine learning"
  - "machine learning for materials"
  - "materials discovery"
  - "inverse design"
  - "physics-informed neural networks"
  - "foundation model for science"
  - "computational materials"
  - "molecular modeling machine learning"

categories:
  - cs.LG
  - cs.AI
  - stat.ML
  - cond-mat
  - physics.comp-ph
  - math.NA

query_max_results: 500

time_window_days: 30

filters:
  - materials
  - material
  - molecule
  - protein
  - physics
  - simulation
  - PDE
  - quantum
  - science

llm:
  temperature: 0

top_k: 3
```

## Arxiv 查询策略（必须严格执行）

### 查询构造规则

构造统一查询表达式（使用配置文件中```keywords```和```categories```项）：

((ti:"keyword1" OR abs:"keyword1") OR (ti:"keyword2" OR abs:"keyword2") OR ...) AND (cat:cs.LG OR cat:cs.AI OR ...)

使用```http://export.arxiv.org/api/query?search_query=...``` api 格式进行搜索。

### 时间范围

必须满足：

submittedDate \in [today - time_window_days, today]（使用配置文件中的```time_window_days```项）

### 排序方式

+ sortBy=submittedDate
+ sortOrder=descending

## 抓取模块（fetch.py）

编写```fetch.py```脚本爬取论文，爬取数量根据配置文件中```query_max_results```项决定。

### API要求

使用 arXiv Query API 并添加 User-Agent：

```OpenClaw-Arxiv-Agent (quzz21@mails.tsinghua.edu.cn)```

### 限流策略（必须遵守）

+ 请求间隔 ≥ 3秒
+ 分页获取
+ 单次 max_results ≤ 100

### 失败重试机制

+ 最大重试次数：3
+ 间隔：指数退避（1s, 3s, 9s）
+ 失败写入 logs/error.log

### 增量抓取机制

state.json 结构：

```json
{
  "last_fetch_time": "...", # 上一次成功抓取论文的时间
  "last_success_time": "...", # 上一次成功生成报告的时间
  "last_processed_papers": "...", # 上一次LLM筛选前通过数据清洗的论文列表，对应的json文件路径
  "top_paper_ids": [], # 时间窗口内被筛选出的优秀论文id
  "last_removed_ids": [], # 超过时间窗口被删除的旧论文id
}
```

执行逻辑：

+ 读取 last_success_time
+ 抓取时间 > last_success_time 的论文
+ 读取 last_processed_papers 对应文件，将历史论文信息与本次抓取结果进行合并
+ 删除超过时间窗口的旧论文（避免待评价论文无限膨胀）
+ 得到本次待数据清洗论文列表

## 数据清洗

每篇论文必须包含：

+ arxiv_id
+ title
+ authors
+ abstract（必须完整，不允许截断）
+ submittedDate
+ categories

去重规则：

+ 唯一键 = arxiv_id
+ 重复论文只保留一份

## 规则过滤（filter.py）

保留满足以下条件的论文：

### 关键词过滤（至少满足一条）

标题或摘要包含配置文件中```filter```项的关键词

### 长度过滤

abstract长度 ≥ 200字符

### 胜者过滤

排除已经出现在历史top k中的优秀论文

历史Top论文ID存储在：

data/state.json → top_paper_ids

每次选出Top K后更新该列表（仅保留时间窗口内的论文）

## LLM评分机制（rank.py）

### 调用方式

逐篇评分（禁止批量评分）

### 评分维度（必须严格使用）

每个维度 0-10 分：

#### Relevance（相关性）

定义：是否属于 AI for Science

评分标准：

+ 0-3：无关
+ 部分相关
+ 明显相关
+ 核心领域

#### Novelty（创新性）

定义：是否提出新方法/新问题

评分标准：

+ 0-3：已有方法应用
+ 4-6：小改进
+ 7-8：明显创新
+ 9-10：新范式

#### Technical Depth（技术深度）

定义：方法复杂性、理论深度

评分标准：

+ 0-3：浅层应用
+ 4-6：中等
+ 7-8：较深
+ 9-10：高深理论/系统

#### Potential Impact（潜在影响力）

定义：对科研/工业潜在价值

评分标准：

+ 0-3：有限
+ 4-6：一般
+ 7-8：较大
+ 9-10：可能重要突破

#### LLM Prompt模板

```markdown
请根据以下论文信息进行评分：

标题：
{title}

摘要：
{abstract}

请按照以下标准评分（0-10分）：
1. Relevance：

定义：是否属于 AI for Science

评分标准：

+ 0-3：无关
+ 部分相关
+ 明显相关
+ 核心领域

2. Novelty

定义：是否提出新方法/新问题

评分标准：

+ 0-3：已有方法应用
+ 4-6：小改进
+ 7-8：明显创新
+ 9-10：新范式

3. Technical Depth

定义：方法复杂性、理论深度

评分标准：

+ 0-3：浅层应用
+ 4-6：中等
+ 7-8：较深
+ 9-10：高深理论/系统

4. Potential Impact

定义：对科研/工业潜在价值

评分标准：

+ 0-3：有限
+ 4-6：一般
+ 7-8：较大
+ 9-10：可能重要突破

请严格输出JSON，不要包含任何额外内容：

{
  "relevance": int,
  "novelty": int,
  "technical_depth": int,
  "impact": int,
  "reason": "不超过100字"
}
```

#### 总分计算

```final_score = 0.3*relevance + 0.3*novelty + 0.2*technical_depth + 0.2*impact```

#### LLM API失败备案

若LLM失败：

+ 重试 2 次
+ 仍失败 → 使用默认分数：

```json
{
  "relevance": 5,
  "novelty": 5,
  "technical_depth": 5,
  "impact": 5,
  "reason": "LLM Error. 使用默认分数"
}
```

### Top k 论文筛选

按 final_score 排序

取前 top_k（从配置文件中读取数量）

### 报告生成（report.py）

输出 Markdown 文件：

outputs/report_YYYYMMDD.md

报告结构（必须严格遵守）：

```markdown
# Arxiv Daily Report (YYYY-MM-DD)

## 1. 今日概览
- 抓取论文数：
- 过滤后：
- 评分后：
- 推荐论文数：

---

## 2. 推荐论文

### 1. 标题

- Authors:
- Date:
- Link: https://arxiv.org/abs/{id}

#### 英文摘要

#### 中文摘要
（完整翻译）

#### 评价
（根据评分reason得到）

#### 评分
- Relevance:
- Novelty:
- Technical Depth:
- Impact:
- Final Score:
```

其中从英文翻译得到的中文摘要可以调用LLM工具进行翻译，Prompt模板：

```markdown
请将以下标题为《$Title》的英文论文摘要翻译成中文：
$Abstract
```

## 飞书上传（feishu.py）

在执行前：复习 create_doc 工具使用方法

要求：

+ 存放在飞书云盘 arxiv_daily 文件夹中（如果不存在新建一个）
+ 文档标题：Arxiv Daily YYYY-MM-DD

内容：Markdown全文

上传成功后记录日志

## 定时任务

使用 openclaw 定时任务在北京时间 08:00 执行

## 日志规范

### run.log

记录：

+ 每一步开始/结束
+ 处理论文数量

### error.log

记录：

+ API失败
+ LLM失败
+ 上传失败

#### 失败处理

任一模块失败：

+ 写 error.log
+ 不中断整体流程（尽可能继续）

## 重要约束（必须遵守）

+ 禁止硬编码关键词和分类（必须来自config.yaml）
+ 禁止超过 arXiv API 限速
+ 禁止截断 abstract
+ LLM调用必须结构化输出JSON
+ 所有文件必须写入 arxiv_daily 目录
+ 每次执行必须更新 state.json

## 最终目标

+ 生成高质量论文推荐
+ 中文科研报告
+ 自动上传飞书
+ 可持续每日运行
