"""
数据工厂写库通道

复用平台已有的数据库配置(pity_database_info)与连接池(app.models.db_helper),
底层用 SQLAlchemy Core 的参数化 insert, 不做 SQL 字符串拼接。

注意: AsyncEngine 不能直接做 reflection, 必须走 run_sync 绿桥拿同步连接,
这与 DbConfigDao.load_table 的做法一致。
"""
from typing import Any, Dict, List, Tuple

from sqlalchemy import Integer, MetaData, Table

from app.core.data_factory.generator import DataFactoryError
from app.crud.config.DbConfigDao import DbConfigDao
from app.models import db_helper

# 单批写入行数, 避免一条超长 SQL
BATCH_SIZE = 500


def is_autoincrement(column) -> bool:
    """
    判断列是否为自增列。

    SQLAlchemy 的 column.autoincrement 是三态, 不能直接当布尔用:
        True    显式自增
        False   显式非自增
        'auto'  "交给 SQLAlchemy 自己判" —— 不是"是自增"的意思
    反射出来的表, 字符串/时间等列大多是 'auto', 直接 `in (True, 'auto')` 判
    会把 username/created_at 这种全当成自增列, 导入时被误排除。
    实际判定按 'auto' 的官方语义: 单列整数主键。
    """
    if column.autoincrement is True:
        return True
    if column.autoincrement is False:
        return False
    # 'auto': 单列整数主键才算自增
    return (
        bool(column.primary_key)
        and len(column.table.primary_key.columns) == 1
        and isinstance(column.type, Integer)
    )


async def get_connection(database_id: int):
    """
    按数据库配置id取连接, 返回 (engine, 数据库配置)
    """
    database = await DbConfigDao.query_database(database_id)
    if database is None:
        raise DataFactoryError("目标数据库配置不存在")
    conn = await db_helper.get_connection(database.sql_type, database.host, database.port,
                                          database.username, database.password, database.database)
    return conn['engine'], database


async def list_tables(engine) -> List[str]:
    """列出该库下的所有表名"""
    async with engine.connect() as conn:
        def _reflect(sync_conn, meta):
            # 必须显式把连接传给 reflect: 用 run_sync 拿到的 meta 并没有绑定 Engine,
            # 不传 bind 会抛 "MetaData object is not bound to an Engine or Connection"
            meta.reflect(bind=sync_conn)
            return [t.name for t in meta.sorted_tables]
        try:
            return await conn.run_sync(_reflect, MetaData())
        except Exception as e:
            raise DataFactoryError(f"读取数据库表结构失败: {e}")


async def reflect_table(engine, table_name: str) -> Table:
    """反射出目标表的结构(真实列名/类型/主键/默认值)"""
    async with engine.connect() as conn:
        def _reflect(sync_conn, meta):
            return Table(table_name, meta, autoload_with=sync_conn)
        try:
            return await conn.run_sync(_reflect, MetaData())
        except Exception as e:
            raise DataFactoryError(f"读取表 {table_name} 结构失败, 请确认表是否存在: {e}")


async def list_columns(engine, table_name: str) -> List[Dict[str, Any]]:
    """目标表的列清单, 供前端自动推导字段规则"""
    table = await reflect_table(engine, table_name)
    columns = []
    for column in table.columns:
        default = None
        if column.default is not None:
            default = getattr(column.default, 'arg', None)
            if callable(default):
                default = None
        columns.append({
            'name': column.name,
            'type': str(column.type),
            'nullable': bool(column.nullable),
            'default': default,
            'primary_key': bool(column.primary_key),
            'autoincrement': is_autoincrement(column),
        })
    return columns


def _match_columns(table: Table, rows: List[dict]) -> List[dict]:
    """
    把规则里的字段名对齐到数据库真实列名(不区分大小写),
    规则里有但表里没有的字段直接跳过
    """
    column_map = {c.name.lower(): c.name for c in table.columns}
    result = []
    for row in rows:
        item = {}
        for key, value in row.items():
            real_name = column_map.get(str(key).lower())
            if real_name is None:
                continue
            item[real_name] = value
        result.append(item)
    return result


async def write_rows(engine, table: Table, rows: List[dict]) -> int:
    """
    批量写入, 一个事务提交
    """
    if not rows:
        return 0
    payload = _match_columns(table, rows)
    if not payload:
        raise DataFactoryError("生成的字段与目标表完全不匹配, 没有可写入的列")
    async with engine.begin() as conn:
        for index in range(0, len(payload), BATCH_SIZE):
            await conn.execute(table.insert(), payload[index:index + BATCH_SIZE])
    return len(payload)


async def write_to_table(database_id: int, table_name: str, rows: List[dict]) -> Tuple[int, List[str]]:
    """
    写库主入口, 返回 (写入行数, 被跳过的字段名)
    """
    engine, _ = await get_connection(database_id)
    table = await reflect_table(engine, table_name)
    column_names = {c.name.lower() for c in table.columns}
    skipped = sorted({str(k) for row in rows for k in row.keys() if str(k).lower() not in column_names})
    count = await write_rows(engine, table, rows)
    return count, skipped
