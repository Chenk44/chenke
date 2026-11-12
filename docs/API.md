# 接口说明

所有接口都在 `/api` 下，没有鉴权——这是个「拉群决定去哪」的工具，
权限模型本身就是「拿到 6 位邀请码的人才能进」。

自动生成的完整 OpenAPI 文档在 **`/docs`**（Swagger UI），可交互调试；
本文件只讲**怎么把一次决策从头跑到尾**。

## 约定

| 项 | 规则 |
| --- | --- |
| 基础路径 | `http://<host>:8000/api` |
| 数据格式 | `application/json`，UTF-8 |
| 错误 | 统一 `{"detail": "人话描述"}`；400=参数/前置条件不满足，404=找不到 |
| 时间 | `meet_date` 用 `YYYY-MM-DD`；时间线的偏移用「分钟」 |
| 一致性 | **同一个局、同样的偏好，两次推荐结果完全相同**（有测试守着，见 `test_recommend_is_deterministic_over_http`） |

## 端点一览

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/api/demo` | 一键生成填好的示例局（5 个人） |
| POST | `/api/groups` | 建局，拿邀请码 |
| GET | `/api/groups/{code}` | 局的信息 + 成员 |
| POST | `/api/groups/{code}/members` | 入局（同昵称幂等） |
| PUT | `/api/members/{id}/preference` | 填 / 改偏好（含一句话解析） |
| GET | `/api/members/{id}/preference` | 读偏好 |
| POST | `/api/parse` | 只解析一句话，不保存（前端实时提示用） |
| POST | `/api/groups/{code}/recommend` | **核心**：生成 3 个方案 |
| GET | `/api/groups/{code}/plans` | 读上次生成的方案快照 |
| POST | `/api/plans/{id}/vote` | 投票 |
| GET | `/api/groups/{code}/votes` | 票数统计 |
| GET | `/api/pois` | 地点列表（可按商圈 / 品类 / 室内过滤） |
| GET | `/api/areas` | 商圈列表 |
| POST | `/api/reviews` | 玩完之后评价一个地点 |
| GET | `/api/pois/{id}/reviews` | 某个地点的评价 |
| GET | `/api/health` | 健康检查（CI 和容器探针用） |

---

## 1. 建局

```http
POST /api/groups
Content-Type: application/json

{
  "name": "周六下午，五个人",
  "origin_area": "海岸城",
  "weather": "rain",
  "budget": 150,
  "window_minutes": 360
}
```

```json
{
  "id": 1,
  "code": "8BV6K7",
  "name": "周六下午，五个人",
  "city": "深圳",
  "meet_date": null,
  "budget": 150.0,
  "origin_area": "海岸城",
  "weather": "rain",
  "window_minutes": 360,
  "created_at": "2026-11-10T09:58:12",
  "members": []
}
```

- `code` 是 6 位邀请码，字母表去掉了 `0O1I`——**这个码是要被人在群里念出来的**。
- `origin_area` 决定出发坐标（取该商圈地点的质心）；写了不认识的商圈会退回深圳中心，不阻断建局。
- `weather` 取 `rain` / `hot` / 空。下雨会触发「优先室内」，这是深圳最高频的场景。

## 2. 入局

```http
POST /api/groups/8BV6K7/members
{"nickname": "小林"}
```

```json
{"id": 1, "nickname": "小林", "filled": false}
```

同一个昵称重复调用返回同一个人，**刷新页面不会多出一个成员**。

## 3. 填偏好（产品最核心的一屏）

```http
PUT /api/members/1/preference
{
  "quiet": 0.85,
  "price": 0.25,
  "near": 0.2,
  "max_price": 100,
  "exclude_tags": ["辣"],
  "indoor_pref": 0,
  "with_kids": false,
  "has_car": false,
  "prefer_categories": ["火锅"],
  "exclude_categories": ["桌游"],
  "prefer_tags": ["拍照"],
  "max_minutes": 240,
  "start_hour": 19,
  "free_text": "想吃火锅，不要玩桌游，晚上七点出发，最多三小时",
  "auto_parse": true
}
```

```json
{
  "quiet": 0.85,
  "price": 0.25,
  "near": 0.2,
  "max_price": 100.0,
  "exclude_tags": ["辣"],
  "indoor_pref": 1,
  "with_kids": false,
  "has_car": false,
  "prefer_categories": ["火锅"],
  "exclude_categories": ["桌游"],
  "prefer_tags": ["拍照"],
  "max_minutes": 180,
  "start_hour": 19,
  "free_text": "想吃火锅，不要玩桌游，晚上七点出发，最多三小时",
  "parsed_hints": ["想要「火锅」", "不要「桌游」", "晚上出发（19:00）", "最多玩 3 小时"]
}
```

这五个字段是后加的，含义各不一样：

| 字段 | 例子 | 进排序的方式 |
| --- | --- | --- |
| `prefer_categories` | `["火锅"]` | 命中加 0.07（`algo/utility.py: CATEGORY_BONUS`） |
| `exclude_categories` | `["桌游"]` | 命中的地点 `× 0.2`（只排除这一类，不连累同商圈的密室） |
| `prefer_tags` | `["拍照"]` | 命中加 0.04 |
| `max_minutes` | `180` | 动线超出上限时按比例扣分，不硬截断 |
| `start_hour` | `19` | 只挪时间线起点，不参与地点打分 |

三条约定：

1. **滑杆和一句话冲突时，以滑杆为准**——用户手拖过的值是他的最终意图，一句话只是补充。
2. `parsed_hints` 要回给前端显示。**用户必须看见 AI 理解成了什么**，否则「理解了」和「理解错了」在体验上没区别。
3. `auto_parse=false` 可以关掉解析，纯手工填。解析器是规则实现，不依赖外部服务，因此不会因为网络挂了就用不了。

实时预览（打字时调用，不落库）：

```http
POST /api/parse
{"text": "带娃，别吃辣，下雨就找室内的"}
```

响应结构和上面一样，但所有字段都是「解析建议值」。

## 4. 生成方案

```http
POST /api/groups/8BV6K7/recommend
```
（无请求体）

```json
{
  "plans": [
    {
      "id": 13,
      "items": [
        {"id": "xibei", "name": "西贝莜面村(海岸城)", "area": "海岸城", "category": "餐饮",
         "indoor": true, "hours": "11:00-22:00", "closed": false,
         "avg_price": 95.0, "blurb": "带长辈和小孩都安全的选择", "offset_minutes": 2.0},
        {"id": "boardgame", "name": "桌游吧(海岸城)", "area": "海岸城", "category": "玩乐",
         "indoor": true, "hours": "10:00-22:00", "closed": false,
         "avg_price": 60.0, "blurb": "下雨天最稳的备选", "offset_minutes": 94.0},
        {"id": "cgv-coastcity", "name": "CGV影城(海岸城)", "area": "海岸城", "category": "影院",
         "indoor": true, "hours": "10:00-23:00", "closed": false,
         "avg_price": 60.0, "blurb": "IMAX 厅够大 座椅也舒服", "offset_minutes": 186.0}
      ],
      "start_minute": 840,
      "consensus": 0.7131,
      "mean_score": 0.7725,
      "worst_score": 0.7052,
      "worst_member": "小林",
      "total_minutes": 306.0,
      "explanation": "西贝莜面村(海岸城) → 桌游吧(海岸城) → CGV影城(海岸城)；全员满意度 0.71~0.81，最让步的是 小林（0.71）；全程约 5.1 小时；全程室内，下雨也不怕；最贵一餐人均 95 元，不超预算。",
      "per_member": {"小林": 0.7052, "阿May": 0.7958, "老王": 0.8113, "Cici": 0.7587, "大熊": 0.7916}
    }
  ],
  "top_pois": [
    {"id": "xibei", "consensus": 0.7561, "mean": 0.7851, "worst": 0.7126,
     "worst_member": "小林", "borda": 1.0, "regret": 0.9897, "spread": 0.1261}
  ],
  "agreement": 0.9541,
  "notes": ["💧 检测到降雨，已自动优先室内地点"]
}
```

字段怎么读：

| 字段 | 含义 | 为什么要有它 |
| --- | --- | --- |
| `consensus` | 共识分，**0.6×平均 + 0.4×最低**，再扣除绕路/超时长 | 平均分高但有人很难受的方案，不该排在前面 |
| `worst_member` / `worst_score` | 谁让步最多、他有多难受 | 「谁牺牲了」是群体决策里最容易被忽视的信息 |
| `per_member` | 每个人对这套方案的满意度 | 有争议时拿去群里对质，比"我觉得挺好"有说服力 |
| `total_minutes` | 含路程的总耗时 | 超过 `window_minutes` 会扣分，不是硬砍 |
| `offset_minutes` | 从出发算起第几分钟到这个点 | 前端据此渲染 `14:02 · 16:04` 的时间线 |
| `hours` / `closed` | 这个点的营业区间，以及「按这个时间线到的时候是否已打烊」 | 排到 22:43 的书店不是好方案，前端把打烊的点标红 |
| `start_minute` | 全组定下的出发时刻（分钟数，840 = 14:00） | 有人「七点才下班」时，时间线要整体后移，而不是写死 14:00 |
| `top_pois` | 单个地点的排名（不是组合） | 用来回答"如果只去一个地方，去哪" |
| `agreement` | Borda 与共识分两种排序的一致度 | 两种规则结论一致才敢说"这个结果稳" |
| `notes` | 这次计算做了什么修正 | 天气降权这类隐性操作必须告诉用户 |

> `recommend` 会**覆盖上一次的方案**（连带旧投票），因为方案是基于当前偏好算出来的；
> 偏好改了还留着旧票，票数就对不上了。

## 5. 投票

```http
POST /api/plans/13/vote
{"member_id": 1}
```

```json
{"plan_id": 13, "votes": 3, "voters": ["小林", "阿May", "老王"], "winner": false}
```

同一人重复投同一个方案是幂等的。统计时**票数并列都算 winner**——
平票就交给群里自己拍板，产品不替他们做独裁决定。

```http
GET /api/groups/8BV6K7/votes
```
```json
[
  {"plan_id": 13, "votes": 3, "voters": ["小林", "阿May", "老王"], "winner": true},
  {"plan_id": 14, "votes": 1, "voters": ["Cici"], "winner": false},
  {"plan_id": 15, "votes": 1, "voters": ["大熊"], "winner": false}
]
```

## 6. 地点与评价

```http
GET /api/pois?area=海岸城&indoor=true
```

```json
[{"id": "xibei", "name": "西贝莜面村(海岸城)", "area": "海岸城", "district": "南山区",
  "category": "餐饮", "avg_price": 95.0, "rating": 4.5, "indoor": true,
  "open_hour": 11.0, "close_hour": 22.0,
  "kid_friendly": true, "tags": ["西北菜", "面食"], "blurb": "带长辈和小孩都安全的选择"}]
```

```http
POST /api/reviews
{"member_id": 1, "poi_id": "xibei", "rating": 4, "comment": "包间安静，适合聊天"}
```

同一个人对同一地点**只保留最后一次**评价（upsert），避免刷分。

## 7. 示例局（给第一次打开的人）

```http
POST /api/demo
```

```json
{"code": "8BV6K7", "member_id": 26, "nickname": "小林", "members": 5}
```

返回一个**已经填好 5 个人偏好**的局。前端拿到后直接调 `recommend` 就能展示完整效果——
评委或第一次点进来的人不用先花三分钟编五个人的口味。

浏览器里直接访问 `/#demo` 也会走这条路径。

---

## 一条命令跑通全流程（PowerShell）

```powershell
$b = "http://127.0.0.1:8000/api"
$demo = Invoke-RestMethod "$b/demo" -Method Post
$plan = Invoke-RestMethod "$b/groups/$($demo.code)/recommend" -Method Post
$plan.plans | ForEach-Object {
  "{0:P0}  {1}" -f $_.consensus, ($_.items.name -join " → ")
}
```

期望输出类似：

```
71%  西贝莜面村(海岸城) → 桌游吧(海岸城) → CGV影城(海岸城)
63%  海岸城购物中心 → 喜茶(海岸城店)
57%  %Arabica(万象天地) → 诚品生活(万象天地) → 迷之密室(万象天地)
```
