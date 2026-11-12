# 尘客 · 一群人去哪玩

<p>
  <a href="https://github.com/Chenk44/chenke/actions/workflows/ci.yml"><img src="https://github.com/Chenk44/chenke/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab" alt="python 3.10+">
  <img src="https://img.shields.io/badge/tests-93%20passed-4dd4ac" alt="93 tests passed">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license">
  <img src="https://img.shields.io/badge/data-201%20POIs%20%C2%B7%2020%20areas-orange" alt="201 POIs">
</p>

> 同是尘客，同走一程。

**给一群人（而不是一个人）推荐去哪玩。** 建个局，把链接甩到群里，每个人各填各的口味，
系统输出 3 个「地点组合 + 动线」方案，每个方案都告诉你：大家的共识度多少、谁让步最多，
最后群里投票定案。

一个人做推荐，是"我喜欢什么"；一群人做决策，是"我们能接受什么"。
这中间的差别，就是这个项目存在的理由。

![首屏](docs/preview-home.png)

<details>
<summary>点开看方案的完整样子（真实运行截图，示例局 5 个人、下雨天）</summary>

![方案页](docs/preview-plans.png)

</details>

---

## 一、它解决的到底是什么问题

周五晚上，五个人的群：

> A：周末去哪？
> B：都行。
> C：别太远。
> D：别太贵。
> E：上次那家又不好吃。
> ……（四十分钟后）
> A：那还是去楼下商场吧。

这不是"找不到好地方"的问题。**是"五个人的偏好没法合成一个决定"的问题。**
点评、小红书、高德都能回答"哪里好"，但没有一个产品回答"**我们**去哪好"。

「尘客」只做这一件事，所以它能做得很深：

| 现有产品 | 回答的问题 | 输出 |
| --- | --- | --- |
| 大众点评 | 这个地方好不好 | 一个地点的评分 |
| 小红书 | 别人去哪玩了 | 一堆笔记 |
| 高德 | 怎么过去 | 一条路线 |
| **尘客** | **我们这群人去哪好** | **一组可执行的方案 + 谁让步了** |

## 二、30 秒看懂它怎么用

1. **建局**：起个名、选出发商圈、选天气（下雨 / 高温）、填人均预算 → 拿到 6 位邀请码。
2. **各填各的**：三个滑杆（安静↔热闹 / 省钱↔舍得 / 近↔远）+ 硬条件（想待室内 / 想出去走走、带娃、开车、忌口）
   + 一句话（"想吃火锅，晚上七点出发，最多三小时"——系统把它拆成 16 个结构化约束，
   连"想吃火锅"这种正向愿望和"不要玩桌游"这种排除都会进排序）。
3. **出方案**：点一下，得到 3 个方案，每个是 2~3 个地点连成的动线，带时刻表，例如
   `14:18 %Arabica 咖啡 → 15:20 诚品生活 → 16:52 迷之密室`，
   附一句人话解释和每个人的满意度。
4. **投票定案**：每个人投一票，票数最高的方案标记出来。

不想先编五个人的口味？打开页面点「**先看一个示例局**」（或直接访问 `/#demo`），
五秒钟看到产品最终形态——示例局里的五个人是真的口味冲突：要安静的、要热闹的、
带娃的、海鲜过敏的、开车的。

## 三、为什么不只是"加了个滤镜的推荐系统"

三条都是可验证、可答辩的技术点，不是文案：

**1）共识分：把"公平"变成可计算的数**

```
共识分 = 0.6 × 平均满意度 + 0.4 × 最低满意度
```

两个方案平均分都是 0.63，但一个让某个人只有 0.1 分，另一个人人 0.6 分以上——
前者看起来"还行"，实际上是有人被牺牲了。「尘客」会选后者，并且**明确告诉你是谁让步了**。
这是"一个人的推荐"和"一群人的决策"的分界线。

**2）两条独立的聚合规则交叉验证**

除了共识分，还同时算 Borda 计数（只看相对名次，抵抗"某人打分特别宽松"）
和 minimax regret（最小化最坏情况下的后悔）。三条路径的排序一致度高，说明结论稳，
不是调参调出来的；不一致度高，就提示"这组偏好分歧明显，建议投票"。

**3）枚举 2~3 个地点的组合与顺序，而不是只排单个地点**

先在共识分 Top24 的池子里枚举，`C(24,3)=2024` 种组合 × 最多 6 种顺序 ≈ 1.2 万种，
全部算一遍在毫秒级完成。**这个规模下穷举是全局最优的**，上遗传算法反而引入调参风险和不可复现性。
方案之间还做了 Jaccard 去重，保证三个方案真的不一样。

> 答辩时如果被问"为什么不用更高级的算法"：因为在这个问题规模上，聪明的算法不如把问题定义对。
> 我们花时间的地方是"公平怎么定义""距离该用步行还是地铁""没填偏好的人怎么处理"。

## 四、快速开始

### 需要

- Python 3.10+（开发和测试用的是 3.12）
- 不需要数据库服务：默认 SQLite，跑起来就是一个文件

### 三步启动

```bash
# 1. 装依赖（建议虚拟环境）
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. 把深圳地点表灌进数据库
python -m scripts.seed

# 3. 启动
python -m uvicorn app.main:app --app-dir backend --reload
```

打开 <http://127.0.0.1:8000> 就是产品页面，<http://127.0.0.1:8000/docs> 是自动生成的接口文档。
点页面上的「先看一个示例局」，五秒钟就能看到完整效果——不用先编五个人的口味。

不想开浏览器？命令行走一遍同样的流程，直接把方案打在终端里：

```bash
python -m scripts.demo
```

Windows 用户也可以直接双击/运行仓库根目录的 `run.ps1`，它会把上面三步做完。

### 跑测试

```bash
python -m pytest -q
```

93 个测试，覆盖效用函数、聚合规则、组合搜索、一句话解析和全部 API 端点。
每个测试都对应文档里的一句话，改坏了 CI 会红。

## 五、项目结构

四层：**纯算法包 → Web 壳 → 一张数据表 → 单页前端**。分层的唯一目的是——
让算法能脱离框架单独测试。下面的行数是 `Get-Content | Measure-Object -Line` 数出来的真实值。

```
.
├── algo/                      1 062 行  纯 Python，不 import 任何 Web / ORM 库
│   ├── types.py                 106     POI / Preference / Plan 三个数据结构
│   ├── geo.py                    62     球面距离 + 通行时间估算（地铁/驾车两套参数）
│   ├── utility.py               155     单人效用 U(地点, 偏好)：三根滑杆 → 一个分数
│   ├── aggregate.py             145     共识分、Borda 计数、minimax regret、排序一致度
│   ├── combine.py               250     组合与动线搜索、多样性去重、人话解释
│   ├── pipeline.py              155     把上面几步编排成一次 run()
│   └── loader.py                161     读 CSV 并逐列校验（脏数据启动即报错）
├── backend/app/               1 663 行  Web 层，只做三件事：校验、读写库、转格式
│   ├── main.py                  116     FastAPI 入口、CORS、静态挂载、422 文案、/api/netinfo
│   ├── config.py                 39     pydantic-settings 读 .env
│   ├── db.py                    113     引擎、建表、老库补列与布尔列迁移
│   ├── models.py                168     7 张表：局/成员/偏好/地点/方案/投票/评价
│   ├── schemas.py               188     请求响应模型（OpenAPI 文档就是它生成的）
│   ├── routers/groups.py        326     建局、加入、填偏好、一句话解析、示例局
│   ├── routers/plans.py         148     生成方案、拉方案、投票、计票
│   ├── routers/pois.py           83     地点列表、商圈列表、地点评价
│   ├── services/nlp.py          373     一句话 → 结构化约束（规则版，3 毫秒，可测）
│   └── services/recommender.py  104     ORM ↔ algo 的唯一翻译层
├── data/pois_shenzhen.csv      34 KB     201 个深圳地点 × 18 列（本项目最核心的资产）
├── web/index.html               738 行  单页前端，零构建、零依赖、不需要 npm
├── tests/                       926 行  93 个用例：算法、聚合、组合、接口、解析
│   ├── conftest.py               39     先设 DATABASE_URL 再 import app（顺序很关键）
│   ├── test_algo.py             423     效用、聚合、组合、时间线、加载器校验
│   ├── test_api.py              316     全部接口的端到端行为
│   └── test_nlp.py              148     一句话解析的边界（含否定与条件句）
├── scripts/                   1 230 行
│   ├── seed.py                   92     CSV → 数据库，可重复执行（--reset 清空重来）
│   ├── demo.py                  175     命令行端到端演示：不开浏览器也能看到算法在干什么
│   ├── fetch_amap.py            256     高德 POI 拉取（缓存、重试、直连兜底）
│   ├── shortlist.py             161     候选短名单：品牌去重 + 每商圈每品类限额
│   ├── draft_labels.py          371     草稿标注：把高德拿不到的 9 个字段先猜一版
│   ├── merge_pois.py             72     人工表 + 草稿表合并（同名同地点去重）
│   └── layout_probe.py          102     移动端布局体检（CDP 量宽度、找越界元素）
├── docs/
│   ├── ALGORITHM.md             334     算法说明书：从痛点推到公式
│   ├── API.md                   270     17 个接口 + 真实响应样例
│   ├── DATA.md                  106     数据来源、标注口径、合规说明
│   └── preview-*.png                    README 用的两张真实截图
├── .github/workflows/ci.yml      35     push 即跑：ruff → 灌数据 → 93 测试 → 真起服务 curl
├── run.ps1 / run.sh                     一键启动（Windows / macOS+Linux）
├── Dockerfile                    22     多阶段构建 + 非 root 用户
└── requirements.txt / pyproject.toml    依赖 7 个；pytest 与 ruff 配置
```

**一次「生成方案」怎么穿过这些文件**——这是理解整个项目最快的方式：

```
web/index.html          点「生成方案」
  → routers/plans.py            读局、读成员、读偏好
  → services/recommender.py     POIRecord→POI，PreferenceRecord→Preference
  → algo/pipeline.py            recommend()
        ├── utility.py          每人给每个地点打分
        ├── aggregate.py        合成共识分 + Borda + minimax regret
        ├── geo.py              算地点间通行时间
        └── combine.py          枚举组合与顺序，选出 3 个方案
  → models.py                   写进 PlanRecord（JSON 快照，投票要引用它）
  → web/index.html              渲染成带时间线的方案卡
```

三个刻意的分层决定，答辩时可以直接讲：

1. **`algo/` 不 import FastAPI，也不 import SQLAlchemy**。1 062 行算法被 47 个算法与解析测试直接覆盖，
   跑测试不需要起服务、不需要连着数据库、不需要网络。算法是这个项目的价值，它必须能单独被验证。
2. **`services/recommender.py` 是唯一同时认识两边的文件**。它导出 `record_to_poi` /
   `member_to_preference` / `run_recommendation` 三个函数；`algo` 反向完全不认识数据库。
   想换存储（比如从 SQLite 换到 Postgres），只改这一个文件。
3. **`web/index.html` 是单文件、零构建**。评委 clone 下来不用 `npm install` 就有完整界面，
   代价是可维护性——这个取舍在 10 天工期下是划算的，写在 `docs/ALGORITHM.md` 的取舍一节。

## 六、数据从哪来（合规性说明）

- **结构化字段来自高德开放平台 POI 检索**（名称、坐标、品类、人均、评分），
  属于官方开放接口的正常使用，不爬取、不绕过任何反爬措施。
- **剩下 9 个字段是人工标注的**：室内/室外、安静度（0~1）、适合人数的上下限、
  是否适合带娃、是否需预约、排队程度（0~1）、标签、一句话推荐理由。
  这部分是评委问"你的数据凭什么比点评好"时的答案：
  点评的标签是给"陌生人"看的，我们标的是"一群人决策需要知道的东西"——
  比如"这家 6 人起订"「下午三点后要排队 40 分钟」「展厅里说话要小声」。
- 完整字段说明见 [docs/DATA.md](docs/DATA.md)。

> 我们**没有**爬大众点评或小红书。理由写在 docs/DATA.md 里：
> 合规风险不可控、反爬策略一周一变、以及最关键的——陌生人的评分对"我们这群人"的解释力，
> 本来就不如"我们自己人玩完之后的评价"。所以产品里做了事后评价功能，
> 让这个局的数据在玩完之后沉淀下来。

## 七、主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/demo` | 一键生成填好的示例局（5 个人，进来就能看结果） |
| POST | `/api/groups` | 建局，返回 6 位邀请码 |
| GET | `/api/groups/{code}` | 局的信息 + 成员列表 |
| POST | `/api/groups/{code}/members` | 用昵称入局（重名幂等） |
| PUT | `/api/members/{id}/preference` | 填/改偏好，可带一句话自动解析 |
| GET | `/api/members/{id}/preference` | 读偏好 |
| POST | `/api/parse` | 只解析一句话、不保存（前端实时提示） |
| POST | `/api/groups/{code}/recommend` | 生成 3 个方案 |
| GET | `/api/groups/{code}/plans` | 读取上次生成的方案 |
| POST | `/api/plans/{id}/vote` | 投票（幂等） |
| GET | `/api/groups/{code}/votes` | 票数统计 |
| GET | `/api/pois` | 地点列表，支持商圈/品类/室内过滤 |
| GET | `/api/areas` | 商圈列表 |
| POST | `/api/reviews` | 玩完之后的评价 |
| GET | `/api/pois/{id}/reviews` | 某个地点的评价 |
| GET | `/api/health` | 健康检查（容器探针 / CI 用） |

完整定义见 `/docs`（OpenAPI），或 [docs/API.md](docs/API.md)。

## 八、部署

```bash
docker build -t chenke .
docker run -p 8000:8000 chenke
```

生产环境把 `DATABASE_URL` 换成 PostgreSQL 即可，代码里没有 SQLite 专有语句。
其余配置见 `.env.example`。

## 九、已知局限

1. **只做了深圳。** 换城市要重跑 `fetch_amap` → `shortlist` → `draft_labels`，再人工复核 2 天；
   这是刻意的取舍：十个城市各 20 条，不如一个城市 201 条标得准。
2. **通行时间是指数估算，不是实时路况。** 用球面距离 × 路网系数 + 地铁/驾车差异，
   误差在 20% 左右。接高德路径规划 API 只需替换 `algo/geo.py` 里一个函数，
   但免费配额会被枚举组合瞬间打爆，所以做了本地缓存策略（见 docs/ALGORITHM.md 第 6 节）。
3. **没有实时营业时间。** "周六晚上去"和"周二中午去"的差别暂时没建模，
   表里用"排队程度"和标签里的人工备注做了粗粒度替代。
4. **一句话解析是规则版，不是大模型。** 这是刻意的：规则可测、3 毫秒返回、断网可用、
   失败模式是"漏识别"而不是"胡说八道"。接大模型的正确做法是让它输出同样的结构化约束，
   规则版本做兜底，而不是让它直接决定推荐结果。
5. **文字里的约束是"软"的，不是硬过滤。** 品类偏好只在效用分里加 0.04–0.07，
   时长上限按超出比例每小时扣 0.20，出发时间只挪时间线起点。这样做是因为一句话解析有误差，
   硬过滤一次误判就把好地点全毙掉；代价是"我说了想吃火锅"偶尔仍会混进别的类型。
   想改成硬过滤，只需把 `algo/utility.py: wants_poi` 的加分支换成乘 `HARD_PENALTY`。
6. **201 条里有一半是"脚本先猜、人工复核"出来的。** 名字/坐标/评分/人均来自高德，
   室内外、安静度、适合人数这些是标出来的，个别地方会有误差（比如把一家日料店判成户外，
   我们已经在词表里修过一轮）。发现错标在 `data/pois_shenzhen.csv` 里改一行、重跑
   `python -m scripts.seed` 即可，不需要改代码。

## 十、许可

MIT，见 [LICENSE](LICENSE)。
