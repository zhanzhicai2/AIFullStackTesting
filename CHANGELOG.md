# Changelog

本项目的版本变更记录。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

- **`[Unreleased]`** — 日常改动累积在这里，不需要每次都动本文件
- **打版本时** — 由 Claude 把 `[Unreleased]` 归档成 `vX.Y.Z` 并 `git tag`，过程见 `/release`
- **v2.0.0 及之前** — 无版本记录。`frontend/package.json` 的 `2.0.0` 是建仓时的脚手架值，从未随功能变更

---

## [Unreleased]

### Added

- **数据工厂（造数工厂）** — 字段规则 → 批量生成 → 导出 / 写库 / 绑定用例
  - 11 种生成方式（`fixed` / `random` / `enum` / `sequence` / `uuid` / `template` / `regex` / `reference` / `faker` / `func` / `date`），自研轻量正则生成器
  - AI 仅做「自然语言 → 字段规则」翻译，生成内核走带种子随机源，同 seed 可重放
  - 复用既有 `pity_testcase_data` 数据驱动链路，不改动该表结构
  - 设计细节与已知缺口见 `backend/docs/data-factory-design.md`
- 项目 **constitution v1.0.0** — 5 条核心原则（确定性优先 / 复用既有机制 / 跨端契约单一出处 / 交互自成闭环 / 落地前必须过回归）+ 安全要求 + 文档分层，见 `.specify/memory/constitution.md`
- 回归脚本 `backend/scripts/datafactory_selftest.py`（49 断言）、`datafactory_e2e.py`（51 断言，含数据驱动端到端）

### Fixed

- `DbConfigDao.execute` 在 `ResourceClosedError` 分支返回 `list` 而非 `(rows, elapsed)` 元组，导致在线 SQL 执行 `CREATE` / `UPDATE` 报 `not enough values to unpack`
- 数据工厂 `unique` 约束曾作用在 `${}` 未解析的字面量上，导致引用了其他字段的派生列无法去重
- `writer.list_tables` 的 `MetaData` 未绑定连接，表名列表接口必然失败
- `column.autoincrement` 三态判定错误（`'auto'` 被当成"是自增"），从表结构导入时误排除业务列

### Changed

- **Stop hook 增加代码审查步骤** — 实质代码改动（非纯文档/配置且 ≥ 20 行）在 commit 前跑一次 `code-review`
- 前端 TypeScript 检查现状已在 `frontend/CLAUDE.md` 标注失效，并给出可用命令
  `npx -y -p typescript@5.9.2 tsc -p tsconfig.json --noEmit`

---

## 版本类型判定

打版本时按下面判断 bump 哪一位：

| 本次改动 | bump | tag |
|---|---|---|
| 只有 fix / docs / chore，没有新功能 | PATCH | `v2.1.0` → `v2.1.1` |
| 有新功能（`feat` commit） | MINOR | `v2.1.0` → `v2.2.0` |
| 不兼容的改造（删字段、改接口语义、动表结构） | MAJOR | `v2.x.x` → `v3.0.0` |
