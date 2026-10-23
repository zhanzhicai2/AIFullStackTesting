---
description: 打版本 — 归档 CHANGELOG 的 [Unreleased] 段并创建 git tag
argument-hint: [可选: 显式指定 vX.Y.Z, 不传则按提交类型自动判定]
---

用户要打版本。按下面的流程执行，**不要**跳过任何一步。

## 1. 确定版本号

先找出上一个版本锚点：

```bash
git describe --tags --abbrev=0 2>/dev/null || echo "NO_TAG"
```

- **有上个 tag**：读 `git log <上个tag>..HEAD --oneline`，按第 4 步的规则判定 bump 位
- **无任何 tag**（首次）：基线取 `frontend/package.json` 里的 version（建仓脚手架值），bump 位按第 4 步判定
- **用户在 `$ARGUMENTS` 里显式给了版本号**：直接用它，跳过判定，但要在结尾说明它与自动判定结果的差异

## 2. 读取本次改动

```bash
git log <上个tag>..HEAD --format="%h %s%n%b"     # 或无 tag 时 git log 最近的 feat 起点到 HEAD
```

按 conventional commit 的 type 归类：`feat` / `fix` / `docs` / `chore` / `refactor` / `perf` / `test` / `build` / `ci` / `style`。

**重要**：`feat` 会触发 MINOR bump。一个功能被拆成多个 commit 时，它们应该合并成 CHANGELOG 里的**一条**，不要按 commit 数重复罗列。

## 3. 读 CHANGELOG 现状

读 `CHANGELOG.md`，确认 `[Unreleased]` 段的内容就是这次要归档的东西。

- 如果 `[Unreleased]` 是空的，直接告诉用户没有可归档的改动，结束，不要创建空 tag
- 如果本次改动**不在** `[Unreleased]` 里（比如忘了加），先补进去再继续

## 4. 判定 bump 类型

| 本次改动 | bump | 示例 |
|---|---|---|
| 只有 fix / docs / chore / refactor，没有新功能 | PATCH | `v2.1.0` → `v2.1.1` |
| 有 `feat` commit | MINOR | `v2.1.0` → `v2.2.0` |
| 不兼容改造（删字段、改接口语义、动表结构、改响应协议） | MAJOR | `v2.x.x` → `v3.0.0` |

判定为 MAJOR 时，**先向用户确认再动手** —— MAJOR 是不可逆的治理级变更。

## 5. 归档 CHANGELOG

在 `CHANGELOG.md` 里，把 `[Unreleased]` 整段移到 `[X.Y.Z] - YYYY-MM-DD` 标题下，日期取当天（`date "+%Y-%m-%d"`）。

- 归档后，顶部**重新留一个空的 `[Unreleased]`**，结构保持 `### Added` / `### Fixed` / `### Changed`（没有内容的分组可以省略）
- 归档段里的内容**原样保留**，不要为了凑格式重写
- 有跨版本的说明（如「v2.0.0 及之前无版本记录」）保留在原位，不要删

## 6. 打 tag

```bash
git add CHANGELOG.md
git commit -m "chore(release): vX.Y.Z"
git tag vX.Y.Z
```

**不要** 用 `git tag -a` 附注消息 —— 本项目的 tag 信息都在 CHANGELOG 里，避免两处重复。

## 7. 结尾交代

告诉用户：
- 新版本号与判定依据（哪个 type 导致的 bump）
- `git log <新tag> -1 --oneline` 确认 tag 打在了正确的 commit 上
- **不要自动 push** —— 让用户自己 `git push && git push --tags`

## 约束

- **MUST NOT** 自动 push（tag 是外发且难以撤回的）
- **MUST NOT** 改动 `CHANGELOG.md` 之外的任何文件
- **MUST NOT** 在没有实际改动时创建 tag
- 本命令只做版本归档，不要顺手改代码或文档
