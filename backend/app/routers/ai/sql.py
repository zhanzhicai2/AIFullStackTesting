"""
SQL 分析路由 —— AI 工作台的 US4

前缀 `/ai`。契约见 `specs/001-ai-workbench/contracts/api.md` §4.3 / §4.5。

**只读保证(FR-031)**:
- 执行计划只采集不执行 —— 只发普通 `EXPLAIN`
- `EXPLAIN ANALYZE`(及其变体)在 **SQL 解析层硬拦**, 不发给数据库
- 对 `UPDATE` / `DELETE` 也只做计划采集, 绝不执行目标 SQL

慢查询排行复用既有的 `pity_sql_history`, **不新建表**。
"""
import json

from fastapi import APIRouter, Depends
from sqlalchemy import select, text

from app.core import ai_service
from app.core.ai_client import ChatError
from app.core.ai_prompts import sql as sql_prompt
from app.core.data_factory import writer
from app.crud.ai.AIAnalysisDao import AIAnalysisDao
from app.crud.config.DbConfigDao import DbConfigDao, PitySQLHistoryDao
from app.handler.fatcory import PityResponse
from app.models import async_session
from app.models.database import PityDatabase
from app.models.environment import Environment
from app.models.sql_log import PitySQLHistory
from app.routers import Permission
from app.routers.ai.base import router
from app.schema.ai_workbench import SqlAnalyzeForm
from app.utils.sql_guard import (SqlGuardError, build_explain, ensure_explain_safe,
                                extract_table_refs, split_table_ref)


async def _collect_indexes(engine, schema: str, tables: list) -> str:
    """
    采集涉及表的索引 —— `information_schema.STATISTICS`。

    复用既有的数据库连接通道, 不新建。
    """
    if not tables:
        return "(无涉及表)"
    names = [split_table_ref(item)[1] for item in tables]
    placeholders = ", ".join(f":name{index}" for index in range(len(names)))
    params = {"schema": schema}
    for index, name in enumerate(names):
        params[f"name{index}"] = name
    sql = (f"SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX, NON_UNIQUE "
           f"FROM information_schema.STATISTICS "
           f"WHERE TABLE_SCHEMA = :schema AND TABLE_NAME IN ({placeholders}) "
           f"ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            rows = result.mappings().all()
    except Exception as e:  # noqa: BLE001 —— 采集不到索引不该让整个分析失败
        return f"(索引信息采集失败: {e})"
    if not rows:
        return "(涉及表上没有索引信息)"
    lines = []
    for row in rows:
        lines.append(f"{row['TABLE_NAME']}.{row['INDEX_NAME']} (第 {row['SEQ_IN_INDEX']} 列: "
                     f"{row['COLUMN_NAME']}, unique={not row['NON_UNIQUE']})")
    return "\n".join(lines)


async def _collect_columns(engine, tables: list) -> str:
    """采集涉及表的列结构 —— 复用数据工厂的 `list_table_columns`"""
    if not tables:
        return "(无涉及表)"
    blocks = []
    for table_ref in tables:
        table = split_table_ref(table_ref)[1]
        try:
            columns = await writer.list_columns(engine, table)
        except Exception as e:  # noqa: BLE001
            blocks.append(f"表 {table}: 读取列结构失败({e})")
            continue
        if not columns:
            blocks.append(f"表 {table}: 没有列信息")
            continue
        detail = ", ".join(f"{item['name']} {item['type']}" for item in columns)
        blocks.append(f"表 {table}: {detail}")
    return "\n".join(blocks)


@router.post("/sql/analyze", description="SQL 性能分析")
async def analyze_sql(form: SqlAnalyzeForm, user_info=Depends(Permission())):
    """
    分析一条 SQL —— 采集执行计划、表结构与索引, 再让模型解读。

    **只读保证**: 只发普通 `EXPLAIN`, 绝不执行目标 SQL;
    `EXPLAIN ANALYZE` 在解析层就被拦下。
    """
    user_id = user_info['id']
    try:
        sql_text = form.sql
        history_id = form.sql_history_id
        if not sql_text and history_id:
            history = await _query_history(history_id)
            if history is None:
                return PityResponse.failed("SQL 历史记录不存在")
            sql_text = history.sql
        if not sql_text or not sql_text.strip():
            return PityResponse.failed("请提供要分析的 SQL")

        # ★ 硬拦 —— 必须在发给数据库之前
        ensure_explain_safe(sql_text)

        engine, database = await writer.get_connection(form.database_id)
        tables = extract_table_refs(sql_text)

        # 只采集计划 —— 只发普通 EXPLAIN
        explain_sql = build_explain(sql_text)
        rows, elapsed = await DbConfigDao.online_sql(form.database_id, explain_sql)
        plan = [dict(row) for row in rows]

        columns_text = await _collect_columns(engine, tables)
        indexes_text = await _collect_indexes(engine, database.database, tables)
        plan_text = "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in plan)

        messages = sql_prompt.build_messages(sql_text, plan_text, columns_text, indexes_text)

        def parser(content: str):
            return sql_prompt.parse_result(content)

        result = await ai_service.invoke(messages, form.vendor_id, form.model_id,
                                         scene="sql", parser=parser, user_id=user_id)
        conclusion = result.data or {}

        analysis = await AIAnalysisDao.insert_analysis(
            title=(sql_text or "")[:120], user_id=user_id, scene="sql",
            result=json.dumps(conclusion, ensure_ascii=False),
            ref_type="sql_history" if history_id else "manual",
            ref_id=history_id or 0, vendor_id=result.vendor_id,
            model_name=result.model_name, tokens=result.tokens)

        payload = dict(conclusion)
        payload["analysis_id"] = analysis.id
        payload["elapsed_ms"] = elapsed
        payload["plan"] = plan
        payload["table_refs"] = tables
        payload["sql"] = sql_text
        return PityResponse.success(payload, msg="分析完成")
    except SqlGuardError as e:
        return PityResponse.failed(str(e))
    except ChatError as e:
        return PityResponse.failed(str(e))
    except ai_service.AIJsonError as e:
        return PityResponse.failed(f"模型返回的内容无法解析为合法结构: {e}, 请重试")
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/sql/slow", description="慢查询排行")
async def list_slow_sql(page: int = 1, size: int = 10, database_id: int = None,
                         min_elapsed: int = None, user_info=Depends(Permission())):
    """
    慢查询排行 —— 复用既有的 `pity_sql_history`, **不新建表**。
    """
    try:
        condition = []
        if database_id is not None:
            condition.append(PitySQLHistory.database_id == database_id)
        if min_elapsed is not None:
            condition.append(PitySQLHistory.elapsed >= min_elapsed)
        data, total = await PitySQLHistoryDao.list_with_pagination(
            page, size, condition=condition,
            _sort=[PitySQLHistory.elapsed.desc(), PitySQLHistory.id.desc()],
            _select=[PityDatabase, Environment],
            _join=[(PityDatabase, PityDatabase.id == PitySQLHistory.database_id),
                   (Environment, Environment.id == PityDatabase.env)])
        result = []
        for history, database, env in data:
            item = PityResponse.model_to_dict(history)
            item["database_name"] = database.name if database else None
            item["database_env"] = env.name if env else None
            item["create_user"] = history.create_user
            result.append(item)
        return PityResponse.success_with_size(data=result, total=total)
    except Exception as e:
        return PityResponse.failed(e)


async def _query_history(history_id: int):
    async with async_session() as session:
        sql = select(PitySQLHistory).where(PitySQLHistory.id == history_id,
                                           PitySQLHistory.deleted_at == 0)
        result = await session.execute(sql)
        return result.scalars().first()
