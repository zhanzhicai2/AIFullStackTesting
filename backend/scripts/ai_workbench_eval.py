"""
AI 工作台 · 抽样评测脚本(需要数据库)

**为什么要有它**(quickstart.md §6.2): SC-002 / SC-004 / SC-007 / SC-008 判的是
"AI 产出的方向对不对", 没有可靠的自动判据 —— 折中是**把人工判定固化成有口径、
可复现、可对比的记录**, 而不是假装它能自动测。

抽样口径(quickstart.md §6.2):
- 每个场景至少 10 个样本; 不足 10 个全量判定并注明样本量
- 取**最近 3 次**生成/分析任务的结果, 各随机抽若干条, **不得挑选表现好的样本**
- 至少 2 人独立判定, 不一致由第三人裁定
- 只判"方向是否正确", 边界样本一律计为"不正确"(保守)

用法:
    cd backend
    .venv/bin/python scripts/ai_workbench_eval.py sample --scene case_gen --count 10
    .venv/bin/python scripts/ai_workbench_eval.py record --scene case_gen --sample 12 --judge 张三 --verdict correct --note "..."
    .venv/bin/python scripts/ai_workbench_eval.py report

JSONL 记录文件: `scripts/ai_workbench_eval_record.jsonl`(不入库)。
"""
import argparse
import asyncio
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import async_session  # noqa: E402
from app.models.ai_draft import PityAIAnalysis, PityAICaseDraft, PityAIDraftBatch  # noqa: E402
from app.models.test_case import TestCase  # noqa: E402
from sqlalchemy import desc, select  # noqa: E402

RECORD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "ai_workbench_eval_record.jsonl")

SCENES = ["case_gen", "bug", "log", "sql"]


async def _sample_case_gen(count: int) -> list:
    """最近 3 个批次里各随机抽若干条草稿"""
    async with async_session() as session:
        sql = select(PityAIDraftBatch).where(PityAIDraftBatch.deleted_at == 0) \
            .order_by(desc(PityAIDraftBatch.id)).limit(3)
        batches = list((await session.execute(sql)).scalars().all())
        samples = []
        per_batch = max(1, count // max(1, len(batches)))
        for batch in batches:
            sql = select(PityAICaseDraft).where(PityAICaseDraft.batch_id == batch.id,
                                                 PityAICaseDraft.deleted_at == 0)
            drafts = list((await session.execute(sql)).scalars().all())
            chosen = random.sample(drafts, min(per_batch, len(drafts)))
            for draft in chosen:
                samples.append({
                    "scene": "case_gen",
                    "id": draft.id,
                    "title": draft.title,
                    "batch": batch.id,
                    "model": batch.model_name or "-",
                })
        return samples


async def _sample_analyses(scene: str, count: int) -> list:
    """最近 3 天/最近 3 个 ref 的分析结论里各随机抽若干条"""
    async with async_session() as session:
        sql = select(PityAIAnalysis).where(PityAIAnalysis.scene == scene,
                                            PityAIAnalysis.deleted_at == 0) \
            .order_by(desc(PityAIAnalysis.id)).limit(count * 3)
        rows = list((await session.execute(sql)).scalars().all())
        chosen = random.sample(rows, min(count, len(rows)))
        samples = []
        for row in chosen:
            samples.append({
                "scene": scene,
                "id": row.id,
                "title": row.title,
                "model": row.model_name or "-",
            })
        return samples


async def _load_records() -> list:
    if not os.path.exists(RECORD_PATH):
        return []
    records = []
    with open(RECORD_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _verdicts(records: list, sample_id: int, scene: str) -> list:
    return [r for r in records if r.get("sample_id") == sample_id and r.get("scene") == scene]


async def main(argv=None):
    parser = argparse.ArgumentParser(description="AI 工作台抽样评测")
    sub = parser.add_subparsers(dest="command", required=True)

    sample_p = sub.add_parser("sample", help="按场景抽样本")
    sample_p.add_argument("--scene", choices=SCENES, required=True)
    sample_p.add_argument("--count", type=int, default=10)
    sample_p.add_argument("--seed", type=int, default=None, help="随机种子(可复现抽样)")

    record_p = sub.add_parser("record", help="录入一条人工判定")
    record_p.add_argument("--scene", choices=SCENES, required=True)
    record_p.add_argument("--sample", type=int, required=True)
    record_p.add_argument("--judge", required=True)
    record_p.add_argument("--verdict", choices=["correct", "incorrect"], required=True)
    record_p.add_argument("--note", default="")

    sub.add_parser("report", help="按场景与模型聚合统计")

    args = parser.parse_args(argv)

    if args.command == "sample":
        if args.seed is not None:
            random.seed(args.seed)
        if args.scene == "case_gen":
            samples = await _sample_case_gen(args.count)
        else:
            samples = await _sample_analyses(args.scene, args.count)
        print(f"场景 {args.scene} 抽样 {len(samples)} 条(不足 10 条时全量判定):")
        for item in samples:
            print(f"  {item['scene']} #{item['id']} [{item['model']}] {item['title']}")
        return

    if args.command == "record":
        records = await _load_records()
        records.append({
            "scene": args.scene,
            "sample_id": args.sample,
            "judge": args.judge,
            "verdict": args.verdict,
            "note": args.note,
            "judged_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        with open(RECORD_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(records[-1], ensure_ascii=False) + "\n")
        print(f"已记录: {args.scene} #{args.sample} by {args.judge} -> {args.verdict}")
        return

    if args.command == "report":
        records = await _load_records()
        if not records:
            print("还没有判定记录, 先跑 sample + record")
            return
        grouped = defaultdict(list)
        for record in records:
            grouped[(record["scene"], record["judge"])].append(record)
        print("== 按判定人 ==")
        for (scene, judge), items in sorted(grouped.items()):
            correct = sum(1 for r in items if r["verdict"] == "correct")
            print(f"  {scene} / {judge}: {correct}/{len(items)} 正确 ({correct / len(items):.0%})")
        by_sample = defaultdict(list)
        for record in records:
            by_sample[(record["scene"], record["sample_id"])].append(record)
        # 至少 2 人判定; 不一致的样本单独标出来(需要第三人裁定)
        disputed = []
        for (scene, sample_id), items in by_sample.items():
            verdicts = {r["verdict"] for r in items}
            if len(items) >= 2 and len(verdicts) > 1:
                disputed.append((scene, sample_id))
        print(f"== 汇总 ==")
        print(f"  总判定 {len(records)} 条, 覆盖样本 {len(by_sample)} 个")
        print(f"  不一致样本(需第三人裁定): {disputed if disputed else '无'}")
        return


if __name__ == "__main__":
    asyncio.run(main())
