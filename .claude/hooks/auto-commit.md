# Stop Hook: 自动 commit

供 `.claude/settings.json` 中 `Stop` hook 的 `prompt` 字段读取。本文件由 Claude Code 触发 Stop 事件时被加载;文件内所有路径都是相对于仓库根 `/Users/zhanzhicai/Desktop/py/AIFullStackTesting/`。

## 执行步骤

每轮对话结束前,按下列步骤执行:

1. 跑 `git status --porcelain` 看工作区状态。
2. 如果输出为空(无未提交改动),直接回复 `__DONE__`,不 commit、不 push。
3. 提取输出里的所有改动文件路径,排除以下路径(个人/本地状态,不该入库):
   - `.claude/memory/` 下的所有文件
   - `.claude/settings.local.json`
   - `.claude/agents/local/` 下的所有文件
4. 排除后如果路径列表为空,直接回复 `__DONE__`,不 commit。
5. 跑 `git diff -- <文件列表>` 看每个文件的实际改动内容。
6. 基于改动内容生成 conventional commit message(格式:`type(scope): subject`,type 取 `feat`/`fix`/`chore`/`refactor`/`docs`/`test`/`build`/`ci`/`perf`/`style` 之一,scope 是受影响模块如 `backend`/`frontend`/`claude`/`spec`/`ci`)。
7. **逐个** 执行 `git add <具体文件路径>`(例如 `git add backend/foo.py CLAUDE.md`),**不要** `git add .`、**不要** `git add -A`、**不要** 通配符 `git add *`。
8. 跑 `git commit -m "<message>"`(直接用 step 6 生成的 message,**不要** 等用户 ack — message + commit 都自动执行)。
9. **push 兜底** — 跑 `date "+%H:%M"` 取当前本地时间,然后:
   - **如果时间在 20:30–21:30(晚 9 点 ±30 分钟,自动 push 兜底窗口)内**:**自动** `git push`(有未 push 的 commit 才推,没有就 no-op 提示 Everything up-to-date),**失败重试 4 次**(每次间隔 30 秒,网络抽风容错):
     ```bash
     for i in 1 2 3 4; do
       git push && break
       [ $i -lt 4 ] && sleep 30
     done
     ```
     4 次都失败(非零退出),在 turn 末尾告诉用户"push 兜底重试 4 次均失败,请手动 `git push`"
   - **其他时间**:**不** 自动 push,在 turn 末尾告诉用户"push 由你手动执行 `git push`"
10. 全部完成后回复 `__DONE__`。
