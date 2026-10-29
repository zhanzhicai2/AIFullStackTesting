"""
数据工厂路由

- 数据集 CRUD
- 生成 / 导出 / 写库 / 绑定用例
- 自然语言 -> 字段规则(AI 只翻译规则, 不生成数据)
- 目标库表结构查询(用于自动推导字段)
"""
from fastapi import APIRouter, Depends

from app.core.ai_client import ChatError, complete_chat
from app.core import ai_service
from app.core.data_factory import ai_parser, exporter, writer
from app.core.data_factory.generator import DataFactoryError, DataGenerator
from app.crud.data_factory.DataFactoryDao import DataFactoryDao
from app.handler.fatcory import PityResponse
from app.routers import Permission, get_session
from app.schema.data_factory import (AiParseForm, BindCaseForm, ExportForm, GenerateForm,
                                     PityDataFactoryForm, WriteDbForm)
from config import Config

router = APIRouter(prefix="/datafactory")


async def _resolve_rows(form: GenerateForm, dataset=None):
    """
    统一的「取数据」入口:

    1. 前端直传 rows(用户在预览表格里手动改过数据) -> 原样使用
    2. 否则按 dataset_id / columns 规则生成, seed 可重放,
       所以导出/写库/绑定重新生成一次就能拿到与预览完全一致的数据
    """
    if form.rows:
        return form.rows
    if dataset is None:
        columns = form.columns
        seed = form.seed
        count = form.count or 10
    else:
        columns = dataset.columns
        seed = form.seed if form.seed is not None else dataset.seed
        count = form.count if form.count is not None else dataset.count
    if not columns:
        raise DataFactoryError("没有可用的字段规则, 请先选择数据集或传入规则")
    generator = DataGenerator(columns, seed=seed if seed else None)
    return generator.generate(count)


@router.get("/dataset/list", description="数据集列表")
async def list_dataset(page: int = 1, size: int = 10, env: int = None, name: str = "",
                       project_id: int = None, user_info=Depends(Permission())):
    try:
        data, total = await DataFactoryDao.list_dataset(page, size, env=env, name=name,
                                                        project_id=project_id)
        return PityResponse.success_with_size(data=PityResponse.model_to_list(data), total=total)
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/dataset/detail", description="数据集详情")
async def query_dataset(id: int, user_info=Depends(Permission())):
    try:
        data = await DataFactoryDao.query_dataset(id)
        if data is None:
            return PityResponse.failed("数据集不存在")
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/dataset/insert", description="新增数据集")
async def insert_dataset(form: PityDataFactoryForm, user_info=Depends(Permission())):
    try:
        data = await DataFactoryDao.insert_dataset(form, user_info['id'])
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/dataset/update", description="编辑数据集")
async def update_dataset(form: PityDataFactoryForm, user_info=Depends(Permission())):
    try:
        data = await DataFactoryDao.update_dataset(form, user_info['id'])
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/dataset/delete", description="删除数据集")
async def delete_dataset(id: int, user_info=Depends(Permission()), session=Depends(get_session)):
    try:
        await DataFactoryDao.delete_dataset(session, id, user_info['id'])
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/generate", description="按规则生成数据")
async def generate(form: GenerateForm, user_info=Depends(Permission())):
    try:
        dataset = None
        if form.dataset_id:
            dataset = await DataFactoryDao.query_dataset(form.dataset_id)
            if dataset is None:
                return PityResponse.failed("数据集不存在")
        rows = await _resolve_rows(form, dataset)
        return PityResponse.success(rows)
    except DataFactoryError as e:
        return PityResponse.failed(str(e))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/export", description="导出 JSON / SQL 文件")
async def export(form: ExportForm, user_info=Depends(Permission())):
    try:
        dataset = None
        if form.dataset_id:
            dataset = await DataFactoryDao.query_dataset(form.dataset_id)
            if dataset is None:
                return PityResponse.failed("数据集不存在")
        rows = await _resolve_rows(form, dataset)
        table_name = form.table_name or (dataset.table_name if dataset else "data")
        if form.file_type == 'sql':
            content = exporter.build_sql(rows, table_name)
        else:
            content = exporter.build_json(rows)
        suffix = f".{form.file_type}"
        path, filename = exporter.write_temp(content, suffix)
        return PityResponse.file(path, filename)
    except DataFactoryError as e:
        return PityResponse.failed(str(e))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/write-db", description="写入目标数据库")
async def write_db(form: WriteDbForm, user_info=Depends(Permission(Config.MANAGER))):
    try:
        dataset = None
        if form.dataset_id:
            dataset = await DataFactoryDao.query_dataset(form.dataset_id)
            if dataset is None:
                return PityResponse.failed("数据集不存在")
        rows = await _resolve_rows(form, dataset)
        count, skipped = await writer.write_to_table(form.database_id, form.table_name, rows)
        msg = f"成功写入 {count} 条数据"
        if skipped:
            msg += f", 以下字段在目标表中不存在已跳过: {', '.join(skipped)}"
        return PityResponse.success(dict(count=count, skipped=skipped), msg=msg)
    except DataFactoryError as e:
        return PityResponse.failed(str(e))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/bind-case", description="绑定到用例, 接入数据驱动")
async def bind_case(form: BindCaseForm, user_info=Depends(Permission())):
    try:
        dataset = None
        if form.dataset_id:
            dataset = await DataFactoryDao.query_dataset(form.dataset_id)
            if dataset is None:
                return PityResponse.failed("数据集不存在")
        rows = await _resolve_rows(form, dataset)
        # 前缀带上数据集标识, replace 清理时才能精确匹配本数据集绑的旧数据
        prefix = form.name_prefix
        if dataset is not None:
            prefix = f"{prefix}-{dataset.id}"
        seed = form.seed if form.seed is not None else (dataset.seed if dataset else 0)
        count = await DataFactoryDao.bind_case(form.env, form.case_id, prefix, seed,
                                               rows, user_info['id'], form.replace)
        return PityResponse.success(dict(count=count), msg=f"成功绑定 {count} 条测试数据")
    except DataFactoryError as e:
        return PityResponse.failed(str(e))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/ai/parse", description="自然语言转字段规则")
async def ai_parse(form: AiParseForm, user_info=Depends(Permission())):
    try:
        # 厂商/模型的解析与校验统一走公共层(research.md §3.2)——
        # 原本这段逻辑在 datafactory 与 ai/chat 两处各写了一份, 改一次要改两处
        ref = await ai_service.resolve_model(form.vendor_id, form.model_id)
        content = await complete_chat(ref.base_url, ref.api_key, ref.model_name,
                                      ai_parser.build_messages(form.prompt), ref.params)
        rules, warnings = ai_parser.parse_rules(content)
        return PityResponse.success(dict(rules=rules, warnings=warnings))
    except ChatError as e:
        return PityResponse.failed(str(e))
    except DataFactoryError as e:
        return PityResponse.failed(str(e))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/table/list", description="目标库的表名列表")
async def list_tables(database_id: int, user_info=Depends(Permission())):
    try:
        engine, _ = await writer.get_connection(database_id)
        tables = await writer.list_tables(engine)
        return PityResponse.success(tables)
    except DataFactoryError as e:
        return PityResponse.failed(str(e))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/table/columns", description="目标表的列结构")
async def list_table_columns(database_id: int, table: str, user_info=Depends(Permission())):
    try:
        engine, _ = await writer.get_connection(database_id)
        columns = await writer.list_columns(engine, table)
        return PityResponse.success(columns)
    except DataFactoryError as e:
        return PityResponse.failed(str(e))
    except Exception as e:
        return PityResponse.failed(e)
