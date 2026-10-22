# 智能回归筛选 · 技术设计

> 状态：设计稿（未实现）
> 目标平台：AIFullStackTesting backend（FastAPI + SQLAlchemy + APScheduler）
> 模块代号：**Impact**（变更影响分析与用例自动筛选）

---

## 0. 一句话

给定一次代码变更或接口定义变更，自动筛选出**必须重跑**的测试用例集，并给出**可解释的传播路径**，在保证高召回（不漏）的前提下把回归耗时压到全量的 30% 以内。

## 1. 为什么要做

测试计划全量执行的成本随用例数线性增长，而绝大多数变更只影响少数接口。人工判断"这次改动要重跑哪些用例"依赖经验，容易漏，且新人无法接手。

本模块解决两件事：

1. **筛选** —— 变更进来后自动算出候选用例集
2. **质量门禁** —— 覆盖率不足的 PR 在 CI 阶段被直接拦下

Pity 上游与 N-Tester2.0 均无此能力（已核实：无依赖图、无增量回归、无覆盖率统计、无 CI 门禁）。

---

## 2. 现状调研：可复用的数据

### 2.1 `pity_testcase` — 用例定义

| 字段 | 类型 | 说明 | 在本模块中的作用 |
|---|---|---|---|
| `id` | INT PK | | 节点标识 |
| `url` | TEXT | 被测接口地址 | **建图主键**（E2 边） |
| `request_method` | String(12) | | |
| `request_headers` | TEXT | | **变量扫描字段** |
| `body` | TEXT | | **变量扫描字段** |
| `base_path` | String(24) | 网关引用，执行时替换 | 建图时需解析 |
| `priority` | String(3) | P0-P4 | **召回兜底 + 排序权重** |
| `status` | INT | 1调试中 / 2暂时关闭 / 3正常 | 过滤停用用例 |
| `case_type` | SMALLINT | 0普通 / 1前置 / 2数据工厂 | **E1 显式依赖 + 兜底全选** |
| `directory_id` | INT | 所属目录 | 项目内分区 |

### 2.2 `pity_out_parameters` — 用例出参声明

| 字段 | 说明 |
|---|---|
| `case_id` | 产出方 |
| `name` | 变量名 |
| `source` | 0 Body(TEXT) / 1 Body(JSON) / 2 Header / 3 Cookie / 4 HTTP状态码 |
| `expression` | 提取表达式 |
| `match_index` | 索引，可为 random / all / 数字 |

**这是数据流依赖的原生载体**：`case_id` 是生产者，`name` 是变量名。

### 2.3 `pity_test_result` — 执行历史

`case_id` / `report_id` / `url` / `status`(0成功 1失败 2出错 3跳过) / `cost` / `asserts` / `start_at` / `finished_at`

**动态层权重的数据来源。**

### 2.4 `pity_test_plan`

`case_list` 为逗号分隔字符串，`ordered` 为有序执行标志（见 §3.1）。

---

## 3. 依赖图设计

### 3.1 前置约束：执行语义

`Executor.run_multiple` 中：

```python
if not ordered:
    await asyncio.gather(*(Executor.run_single(env, result_data, report_id, c, ...) for c in case_list))
else:
    for c in case_list:
        await Executor.run_single(env, result_data, report_id, c, ...)
```

**默认是并发执行**。而出参依赖（`case_params.update(out_dict)`）只有在 `ordered=True` 的串行语义下才成立。

> **设计决策**：Impact 模块输出的筛选结果，**强制以有序方式执行**。筛选 API 返回的用例列表附带 `ordered: true` 标记，调用方（测试计划 runner）据此走串行分支。
>
> 顺带修正：并发模式下出参传递本来就不可靠，这是 Pity 的既有隐患，本模块不依赖它。

### 3.2 变量引用语法（静态解析的依据）

`core/render.py` 中 Jinja2 Environment 被定制：

```python
my_env.variable_start_string = "${"
my_env.variable_end_string = "}"
```

`Executor.fields = ['body', 'url', 'request_headers']` —— 变量替换只扫描这三个字段。

**因此引用语法为 `${变量名}`，仅出现在 body / url / request_headers 三个字段中。**

解析规则：

| 形式 | 例子 | 处理 |
|---|---|---|
| 简单变量 | `${token}` | 提取 `token` |
| 属性/下标访问 | `${data.id}` / `${data['id']}` | 提取根名 `data` |
| 带过滤器 | `${token \| upper}` | 取管道左侧根名 |
| 表达式/函数 | `${rand()}` | **无外部依赖，忽略**（`PityFunction` 注入的全局函数） |
| 字面量 | `${1}` `${'a'}` | 忽略 |

> 实现注意：`Render.load` 用了 `@lru_cache(128)`，且 `Render` 是静态渲染。解析器**不要复用 Render 实例**，而应独立用 `jinja2.meta.find_undeclared_variables` 或正则 + AST 提取，避免污染缓存。

### 3.3 边的类型

| 边 | 语义 | 构造方式 | 强度 |
|---|---|---|---|
| **E1 数据流** | B 引用了 A 的出参 | B 的扫描字段含 `${n}`，且存在 A 的 `out_parameters.name == n` | 强，必选 |
| **E2 接口前缀** | B 的 URL 在 A 的 URL 前缀下 | 规范化后 `A.url` 是 `B.url` 的路径前缀 | 弱，选 |
| **E3 断言耦合** | B 的断言读取 A 的出参 | `testcase_asserts` 中引用了 A 的出参名 | 强，必选 |
| **E4 前置构造** | B 使用 A 的 constructor | `case_type=1` 且 constructor 关联 | 强，必选 |

图的方向统一为 **`dependent → dependency`**（B 依赖 A），传播时从变更点沿反向走。

### 3.4 数据结构（不落库）

**设计决策：依赖图不持久化。**

理由：图是从用例定义（url / body / headers / out_parameters / asserts）**纯函数派生**的。落库会带来同步问题——改了一条用例的 body，图就过期了，而过期比重算更危险。

```python
@dataclass(frozen=True)
class Node:
    case_id: int
    url: str            # 规范化后
    priority: str       # P0..P4
    case_type: int
    status: int

@dataclass(frozen=True)
class Edge:
    src: int            # 依赖方
    dst: int            # 被依赖方
    kind: str           # E1 | E2 | E3 | E4
    via: str            # 传播依据，如 "out_param:token" / "prefix:/api/user"

class ImpactGraph:
    nodes: dict[int, Node]
    out_edges: dict[int, list[Edge]]   # node -> 它依赖谁
    in_edges:  dict[int, list[Edge]]   # node -> 谁依赖它
    var_producer: dict[tuple[int, str], int]  # (env, var_name) -> case_id
```

图构建是一次全量扫描 + 内存构建，单项目数百到数千用例应在 **百毫秒级**完成。构建结果按 `(project_id, 用例定义版本哈希)` 缓存。

**注意 `var_producer` 必须按 env 分区** —— 全局变量（`pity_gconfig`）在不同环境下同名不同值，同名变量在两个项目里也可能由不同用例产出。查生产者时若命中多个，取"最近一次执行成功"的产出方，并记为弱边。

### 3.5 变更输入 → 命中节点

三种变更源，优先级从高到低：

1. **接口定义变更**（OpenAPI diff）→ 直接按 URL 精确命中 —— 最可靠
2. **代码 diff** → 路径映射到 URL 前缀。例如变更 `app/api/user.py` → 映射到 `/api/user/**`
3. **手工指定** → 测试人员直接勾选 URL 或用例

路径到 URL 的映射规则需要在项目级配置（新增 `pity_project_impact_rule` 表，或先复用项目描述字段）。**第一版可以只做 1 和 3，2 留作扩展**——因为 2 需要额外的路径治理，边际收益有限。

---

## 4. 影响传播算法

### 4.1 静态层（BFS）

```
输入: seeds（直接命中的用例集合）, graph, config
输出: selected（候选用例集）, paths（传播路径）

queue = deque(seeds)
selected = set(seeds)
paths = {c: [变更点] for c in seeds}

while queue:
    cur = queue.popleft()
    for edge in graph.in_edges[cur]:        # 谁依赖 cur
        dependent = edge.src
        if dependent not in selected:
            selected.add(dependent)
            paths[dependent] = paths[cur] + [f"{edge.kind}:{edge.via}"]
            queue.append(dependent)

return selected, paths
```

**复杂度**：O(V + E)，线性。

**弱边处理**：E2（接口前缀）是弱证据，传播时**不因为弱边而跳过**，但记录下来供 UI 区分"强证据选中"和"弱证据选中"。弱证据导致的误选可以在 UI 上一键排除，形成人工反馈闭环。

### 4.2 召回兜底规则（保证不漏）

三道保险，任一触发则该用例无条件入选：

1. **P0 用例全选** —— 不论是否被传播命中
2. **静态分析覆盖不到的用例全选** —— 包括 `case_type=2`（数据工厂）、URL 为空或无法规范化的用例。它们无法参与建图，静态层对它们无发言权
3. **降级** —— 若图构建失败（解析异常、循环依赖等），整体退化为全量执行并告警

> **设计哲学：宁可多选，不可漏选。** 漏一条用例 = 线上事故；多跑几条 = 多花几分钟。这个不对称性决定了所有阈值都往召回侧倾斜。

### 4.3 动态层（权重与排序）

静态层决定**选不选**，动态层决定**先跑哪个**以及**并行度**。

```
score(case) = w1 · fail_score
            + w2 · priority_weight
            + w3 · staleness
            + w4 · cost_penalty
```

**fail_score —— 用 Wilson 下界修正失败率**

直接用 `失败次数 / 总次数` 会被小样本骗：一个只跑过 1 次且失败的用例得分 1.0，会被顶到最前面。用 Wilson 置信下界：

```
p̂ = k / n
z = 1.96
wilson = (p̂ + z²/(2n) − z·sqrt((p̂(1−p̂) + z²/(4n)) / n)) / (1 + z²/n)
```

n 小时自动收缩到 0 附近。可用最近 N 次执行（N=50）或最近 T 天（T=30 天，取先满足的）。

**priority_weight**：P0=5, P1=4, P2=3, P3=2, P4=1

**staleness**：距上次执行天数，归一化 `min(days / 30, 1.0)`。很久没跑的用例优先——它最可能在回归中暴露问题（久未执行意味着可能已经腐坏）。

**cost_penalty**：平均耗时，用于**并行装箱**。不是越小越优先，而是让高风险用例先启动，耗时长的提前调度，减少尾部等待。

初值 `w1=0.5, w2=0.3, w3=0.1, w4=0.1`，后续用评测集调。

### 4.4 是否启用筛选的决策

```python
ratio = len(selected) / len(active_cases)
if ratio > 0.6:
    # 筛选省不下多少，直接全量跑，避免"筛了半天跑了八成"的伪优化
    return all_cases, "fallback:ratio_too_high"
return selected, "filtered"
```

---

## 5. 可解释性（设计重点）

筛选结果**必须携带传播路径**，不能只返回用例 ID 列表。

```json
{
  "seed": ["/api/user/profile"],
  "selected": [1024, 1025, 1031],
  "evidence": {
    "1024": {
      "level": "strong",
      "path": ["/api/user/profile", "E2:prefix:/api/user/profile", "E1:out_param:uid", "1024"],
      "hops": 3
    },
    "1031": {
      "level": "weak",
      "path": ["/api/user/profile", "E2:prefix:/api/user", "1031"],
      "hops": 2,
      "note": "仅前缀匹配，若确认无关可一键标记忽略"
    }
  },
  "coverage": {"selected": 3, "total": 412, "ratio": 0.0073},
  "fallback_rules_fired": ["p0_all_selected"]
}
```

理由：测试人员不信任黑盒筛选。每条用例"为什么被选中"必须可回溯，否则这个功能用不起来——**人不会执行自己看不懂的命令**。

UI 上同时提供**一键排除**，排除记录回写为反馈，用于后续调权重。

---

## 6. 新增数据模型

只新增一张表，依赖图不落库。

```python
class PityCaseMetric(PityBase):
    """用例执行指标（动态层数据源，由执行引擎回写）"""
    __tablename__ = 'pity_case_metric'
    __unique_args__ = (UniqueConstraint('case_id', 'deleted_at'),)

    case_id       = Column(INT, nullable=False, index=True)
    env           = Column(INT, nullable=False, index=True)   # 指标按环境隔离
    total_count   = Column(INT, default=0)
    fail_count    = Column(INT, default=0)
    error_count   = Column(INT, default=0)
    avg_cost      = Column(FLOAT, default=0)                  # 秒
    last_run_at   = Column(TIMESTAMP)
    recent_results = Column(TEXT)   # 最近 N 次 "010110" 状态串，用于算 Wilson 与趋势
```

回写点：`Executor.run_multiple` 的 step5 回写报告处，顺带 `upsert` 一行。

告警/日志类数据复用既有的 `pity_operation_log`。

---

## 7. API 设计

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/impact/analyze` | 入参 `project_id, env, seeds{urls[]}\|diff_refs[]\|case_ids[]}`，返回筛选结果 + 传播路径 + 覆盖率 |
| `GET` | `/api/v1/impact/graph` | 查看依赖图（用于可视化与调试），支持按节点展开 |
| `POST` | `/api/v1/impact/exclude` | 人工标记误选，回流为权重反馈 |
| `GET` | `/api/v1/impact/coverage` | 需求/接口维度的覆盖率反查（供质量门禁使用） |

新增模块目录：`backend/app/api/v1/impact/`，遵循现有的 controller / service / model / schema 四文件分层。

---

## 8. 质量门禁（第二阶段）

CI 流程：

```
PR 提交 → 拿 git diff
       → Impact.analyze(project, diff)
       → 检查「被改接口」是否有用例覆盖
       → 覆盖率 < 阈值 → exit 1，PR 打回
       → 否则输出「本次必须执行的用例清单」
```

门禁阈值不设死，建议：

- **硬门禁**：变更接口覆盖率 100%（有改动的接口必须有对应用例）
- **软告警**：变更相关用例的历史失败率 > 30% → 提醒关注但不拦

第一版只做硬门禁。软告警需要历史数据，冷启动阶段噪声太大。

---

## 9. 评测方案

### 9.1 指标定义

| 指标 | 公式 | 含义 | 目标 |
|---|---|---|---|
| **Recall** | 选中的 ground-truth 用例 / 全部 ground-truth 用例 | **不漏**（最重要） | ≥ 0.98 |
| **Precision** | 选中的且确实受影响 / 全部选中 | 少跑 | ≥ 0.85 |
| **Selection Ratio** | 选中数 / 全量用例数 | 节省幅度 | ≤ 0.30 |
| **时间节省** | 1 − (筛选耗时 × 放大系数) / 全量耗时 | 实际收益 | ≥ 60% |

Recall 是第一优先级。一个 Precision 0.7 / Recall 1.0 的模块，比 Precision 0.95 / Recall 0.9 的模块**更有用**。

### 9.2 Ground truth 怎么来

三种来源，成本递增：

1. **合成依赖** —— 构造 N 条已知依赖链（如 A→B→C 已知），直接作为 ground truth。成本最低，可快速回归。
2. **历史 commit 回放** —— 取项目历史上 N 个真实 commit，人工标注"这次改动应该重跑哪些用例"。**这是最接近真实的一份**，也是面试时最该拿出来的。
3. **专家标注** —— 找资深测试人员对同一批变更出 ground truth，用于校验第 2 步的标注质量。

> **注意标注偏差**：标注者也会漏。缓解办法是让 2 人独立标注，测 Cohen's Kappa 一致性，Kappa < 0.6 说明标准不清，ground truth 不可信。

### 9.3 样本量估算

Recall 的 95% 置信区间半宽 ≈ `1.96 × sqrt(p(1−p)/n)`。

| 样本量 n | p=0.95 | p=0.98 | p=0.99 |
|---|---|---|---|
| 30 | ±7.8% | ±3.9% | ±2.6% |
| 50 | ±6.0% | ±3.0% | ±2.0% |
| 100 | ±4.3% | ±2.1% | ±1.4% |
| 200 | ±3.0% | ±1.5% | ±0.9% |

**结论：**

- 想证明 Recall ≥ 0.98 且区间够窄，需要 **≥ 200 个变更样本**——真实项目拿不到
- **退而求其次：n = 50 个样本**，Recall 0.95 的区间是 ±6%，可以支撑"接近 1"的结论
- 合成依赖（第 1 种）可以轻松生成 500+ 样本，用来**回归算法的正确性**（不漏边、不错连）
- 历史 commit 回放（第 2 种）做 **n = 50**，用来证明**真实场景下的有效性**

两者分工明确：**合成集证明算法对，回放集证明场景对。**

### 9.4 基线对照

必须有一个对照实验，否则"节省 70%"没有意义：

- **Baseline A**：随机选 30% 用例 → 算 Recall
- **Baseline B**：全量执行 → Recall = 1.0，耗时 100%
- **Impact**：算 Recall 与 Selection Ratio

预期：Baseline A 的 Recall 大约 30-50%，Impact ≥ 95%。这个对比图是面试里最有说服力的一张。

---

## 10. 里程碑（6-8 周）

| 周 | 交付物 | 完成标准 |
|---|---|---|
| **W1** | 依赖图构建器：变量解析器 + URL 规范化 + E1/E4 边 | 单元测试覆盖解析边界（嵌套、过滤器、异常表达式）；能在真实用例集上建图 |
| **W2** | 影响传播 BFS + 三道召回兜底规则 | 合成依赖集上 Recall = 1.0；图构建失败时正确降级 |
| **W3** | `/impact/analyze` API + 前端影响分析页 | **能展示传播路径**；弱证据可视化区分；一键排除可用 |
| **W4** | 动态层：`pity_case_metric` 表 + 执行引擎回写 + Wilson 评分 | 执行一次测试计划后指标正确累积；排序结果符合预期 |
| **W5** | 评测集构造：合成集 500 + 历史回放 50 | ground truth 标注完成，Cohen's Kappa ≥ 0.6 |
| **W6** | 首轮评测 + 基线对照 + 权重调优 | 拿到第一版 precision / recall / ratio 数据 |
| **W7** | 质量门禁接入 CI（硬门禁：变更接口覆盖率） | 在真实 PR 上拦住一次覆盖不足的提交 |
| **W8** | 文档 + 架构决策记录 + 面试材料整理 | 一篇技术文档 + 一组实测数据 |

**风险与预案：**

| 风险 | 预案 |
|---|---|
| 历史用例数据太少，建图效果差 | W1 先造 200 条合成用例验证算法，不依赖真实数据 |
| ground truth 标注耗时超预期 | 砍到 n=30，接受区间较宽；优先保证合成集 |
| 前端影响分析页工作量超预期 | 先只做后端 API + 简版表格，图形化留到最后 |
| Recall 上不去 | 检查兜底规则是否触发过度；宁可调低 Precision 换 Recall |

---

## 11. 与面试的关系

这个模块的存在意义不只是功能，而是**它是目前唯一一个能证明"我独立设计并落地了一个东西"的载体**。

它能撑住 20 分钟追问的问题：

- 为什么依赖图不落库？（派生数据，落库会腐化）
- 冷启动怎么办？（静态层保证召回，动态层随数据积累逐步启用）
- 为什么宁可多选不可漏选？（漏 = 事故，多跑 = 几分钟，不对称）
- Wilson 下界解决什么问题？（小样本失败率虚高）
- Recall 和 Precision 你怎么权衡？为什么先保 Recall？
- 评测集怎么造的？ground truth 可信吗？Kappa 多少？
- 弱边误选怎么办？（可解释性 + 人工反馈回流）
- 和 N-Tester2.0 / Pity 上游的区别？（它们没有，可现场 grep 验证）

---

## 12. 已知约束

1. **依赖分析仅覆盖 Pity 内用例间的数据流**。跨系统的依赖（用例 → 被测服务 → 下游服务）不在范围内。
2. **E2 前缀匹配是弱证据**，无接口文档时只能靠 URL 猜测。接了 OpenAPI 会显著改善。
3. **不做用例自动改写**。接口变更导致断言失效时，模块只负责**标记**，不负责修复。
4. **单项目内建图**，跨项目依赖不处理。