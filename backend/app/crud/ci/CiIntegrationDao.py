"""
CI 接入凭据 DAO

**凭据只存 `sha256(明文)` 等值摘要**(research D1): 明文由 `secrets.token_hex(16)` 生成,
只在 `issue()` 的返回值里出现一次, 之后任何读路径都拿不到(spec FR-002 / SC-007)。

**为什么无盐 sha256 是安全的**: token 是 128 bit CSPRNG 熵, 穷举空间 2^128, 慢哈希
(bcrypt/argon2)没有收益却引入依赖与每次校验的 CPU 开销。而且服务端校验是
`sha256(入参) == 存储值` —— 攻击者拿到 DB 里的摘要后**无法直接当 token 用**
(提交摘要会得到 `sha256(摘要) ≠ 存储值`), 也无法反推明文。

**`token_prefix` 只做展示**: 校验**绝不使用它**, 防止「前缀命中即放行」的错误实现。

**项目作用域**: 所有查询按 `project_id` 隔离; 跨项目触发由路由层判定(403)。
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.enums.CiEnum import TOKEN_DEFAULT_EXPIRE_DAYS, TOKEN_PREFIX, TOKEN_PREFIX_LEN
from app.models import async_session
from app.models.ci import PityCiIntegration
from app.utils.logger import Log

log = Log("CiIntegrationDao")


@ModelWrapper(PityCiIntegration)
class CiIntegrationDao(Mapper):

    # ------------------------------------------------------------------
    # 纯函数部分(可无 DB 单测 —— scripts/ci_selftest.py 直接调用)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_hash(token: str) -> str:
        """凭据摘要 —— 与 `check_credential` 是同一套算法, 单一出处"""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_token() -> str:
        """
        生成接入凭据明文。

        **不可重放(constitution 原则 I 豁免条款)**: 走 `secrets`(CSPRNG, 128 bit 熵),
        **MUST NOT** 改成可 seed 的随机源 —— 可重放的凭据等于可预测的凭据。
        这是安全属性, 不是缺陷; 本字段是本特性唯一的随机源。
        """
        return f"{TOKEN_PREFIX}{secrets.token_hex(16)}"

    @staticmethod
    def check_credential(integration, token: str, now: datetime = None) -> str:
        """
        校验链(契约 `contracts/api.md` §1.3 第 1~5 步)。**纯函数, 不查库**。

        :param integration: 已按 `token_hash` 查出的记录(查不到即第 2 步失败)
        :return: `""` 表示通过; 否则返回拒绝文案(四种各不相同, 且都不回显凭据)
        """
        if integration is None:
            return "CI 凭据无效"
        if not token or not token.startswith(TOKEN_PREFIX):
            return "CI 凭据无效"
        # 摘要比对放最前 —— 先证明「这是个真凭据」, 再谈它的状态,
        # 避免把「凭据存在但已停用」泄露给没有有效凭据的调用方
        if integration.token_hash != CiIntegrationDao.compute_hash(token):
            return "CI 凭据无效"
        if getattr(integration, "deleted_at", 0) not in (0, None):
            return "CI 凭据无效"
        if not getattr(integration, "enabled", True):
            return "CI 凭据已停用"
        expires_at = getattr(integration, "expires_at", None)
        if expires_at is not None:
            if now is None:
                now = datetime.now()
            if expires_at <= now:
                return "CI 凭据已过期"
        return ""

    # ------------------------------------------------------------------
    # 校验(带库)
    # ------------------------------------------------------------------

    @classmethod
    async def validate_token(cls, token: str) -> Tuple[Optional[PityCiIntegration], str]:
        """
        按摘要等值查 + 走校验链。

        :return: `(记录, 错误文案)` —— 通过时错误文案为 `""`(与 MockRuleDao 的
                 `(rule, warn_msg)` 元组返回同款约定)
        """
        if not token or not token.startswith(TOKEN_PREFIX):
            return None, "CI 凭据无效"
        async with async_session() as session:
            sql = select(PityCiIntegration).where(
                PityCiIntegration.token_hash == cls.compute_hash(token))
            result = await session.execute(sql)
            integration = result.scalars().first()
        err = cls.check_credential(integration, token)
        if err:
            return None, err
        # 第 7 步: 更新最后使用时间。**尽力而为** —— 时间戳写失败不该把一次
        # 合法调用拒之门外
        try:
            now = datetime.now()
            await cls.touch_last_used(integration.id)
            # 另开会话更新不会回写到本对象上, 手动同步 —— 否则调用方读到的还是旧值
            integration.last_used_at = now
        except Exception as e:
            log.warning(f"更新 CI 凭据最后使用时间失败: id={integration.id} ({e})")
        return integration, ""

    @classmethod
    async def touch_last_used(cls, integration_id: int):
        async with async_session() as session:
            async with session.begin():
                sql = select(PityCiIntegration).where(PityCiIntegration.id == integration_id)
                data = (await session.execute(sql)).scalars().first()
                if data is None:
                    return
                data.last_used_at = datetime.now()
                await session.flush()

    # ------------------------------------------------------------------
    # 签发
    # ------------------------------------------------------------------

    @classmethod
    def default_expires_at(cls) -> datetime:
        """默认有效期 = now + 1 年(决定 Q4)。

        **「不传」与「传 null」的区分在路由层** —— pydantic v1 下两者都落成 `None`,
        路由用 `form.__fields_set__` 判定键是否被显式提供, 再决定调用本方法还是
        直接传 `None`(= 长期有效)。
        """
        return datetime.now() + timedelta(days=TOKEN_DEFAULT_EXPIRE_DAYS)

    @classmethod
    async def issue(cls, project_id: int, name: str, user_id: int, plan_id: int = None,
                    callback_url: str = None, expires_at: datetime = None
                    ) -> Tuple[PityCiIntegration, str]:
        """
        签发凭据。

        :param expires_at: 最终有效期。`None` = **长期有效**(永不过期);
            需要默认 1 年时由调用方先算 `default_expires_at()` 再传进来。
        :return: `(记录, 明文凭据)` —— **明文只在这里返回一次**
        """
        token = cls.generate_token()
        model = PityCiIntegration(
            project_id=project_id, name=name, token_hash=cls.compute_hash(token),
            token_prefix=token[:TOKEN_PREFIX_LEN], user=user_id, plan_id=plan_id,
            callback_url=callback_url, enabled=True, expires_at=expires_at)
        result = await cls.insert(model=model, log=True)
        # 日志只记前缀 —— 完整明文一个字都不落盘(spec FR-024 / SC-007)
        log.info(f"签发 CI 凭据: id={result.id} project={project_id} name={name} "
                 f"prefix={result.token_prefix}")
        return result, token

    # ------------------------------------------------------------------
    # 查询 / 编辑
    # ------------------------------------------------------------------

    @classmethod
    async def list_integrations(cls, project_id: int, page: int = 1, size: int = 20
                                ) -> Tuple[List[PityCiIntegration], int]:
        """项目下的凭据列表 —— 响应中不含 `token_hash`(契约 §2.1)"""
        async with async_session() as session:
            sql = select(PityCiIntegration).where(
                PityCiIntegration.project_id == project_id,
                PityCiIntegration.deleted_at == 0,
            ).order_by(PityCiIntegration.id.desc())
            total = len((await session.execute(sql)).scalars().all())
            sql = sql.offset((page - 1) * size).limit(size)
            return list((await session.execute(sql)).scalars().all()), total

    @classmethod
    async def query_integration(cls, integration_id: int, project_id: int
                                ) -> Optional[PityCiIntegration]:
        """按 id + 项目查 —— 跨项目视为不存在"""
        async with async_session() as session:
            sql = select(PityCiIntegration).where(
                PityCiIntegration.id == integration_id,
                PityCiIntegration.project_id == project_id,
                PityCiIntegration.deleted_at == 0)
            return (await session.execute(sql)).scalars().first()

    @classmethod
    async def update_integration(cls, integration_id: int, project_id: int, user_id: int,
                                 name: str = None, plan_id: int = None,
                                 callback_url: str = None) -> PityCiIntegration:
        """
        编辑集成配置。**不接受任何凭据字段** —— 凭据不可改, 只能删了重签(契约 §2.3)。
        `plan_id` 传 `None` 表示解绑默认计划。
        """
        async with async_session() as session:
            async with session.begin():
                sql = select(PityCiIntegration).where(
                    PityCiIntegration.id == integration_id, PityCiIntegration.deleted_at == 0)
                data = (await session.execute(sql)).scalars().first()
                if data is None:
                    raise Exception("集成配置不存在")
                if data.project_id != project_id:
                    raise Exception("集成配置不属于当前项目")
                if name is not None:
                    data.name = name
                if plan_id is not None:
                    data.plan_id = plan_id
                if callback_url is not None:
                    data.callback_url = callback_url
                data.update_user = user_id
                data.updated_at = datetime.now()
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def switch(cls, integration_id: int, project_id: int, user_id: int, enabled: bool
                     ) -> PityCiIntegration:
        """启停 —— 停用立即拒绝新调用(FR-003); 已在跑的执行不受影响(FR-030)"""
        async with async_session() as session:
            async with session.begin():
                sql = select(PityCiIntegration).where(
                    PityCiIntegration.id == integration_id, PityCiIntegration.deleted_at == 0)
                data = (await session.execute(sql)).scalars().first()
                if data is None:
                    raise Exception("集成配置不存在")
                if data.project_id != project_id:
                    raise Exception("集成配置不属于当前项目")
                data.enabled = enabled
                data.update_user = user_id
                data.updated_at = datetime.now()
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def delete(cls, integration_id: int, project_id: int, user_id: int) -> bool:
        """逻辑删除 —— **不物理删**, `pity_ci_run.integration_id` 还要能回溯(契约 §2.5)"""
        async with async_session() as session:
            async with session.begin():
                sql = select(PityCiIntegration).where(
                    PityCiIntegration.id == integration_id, PityCiIntegration.deleted_at == 0)
                data = (await session.execute(sql)).scalars().first()
                if data is None:
                    raise Exception("集成配置不存在")
                if data.project_id != project_id:
                    raise Exception("集成配置不属于当前项目")
                cls.delete_model(data, user_id)
                await session.flush()
                return True

    # ------------------------------------------------------------------
    # 供触发链路使用
    # ------------------------------------------------------------------

    @classmethod
    async def query_by_id(cls, integration_id: int) -> Optional[PityCiIntegration]:
        """按 id 查(不带项目过滤) —— 供 `ci_runner` 取 project_id / plan_id 做作用域判定"""
        async with async_session() as session:
            sql = select(PityCiIntegration).where(
                PityCiIntegration.id == integration_id, PityCiIntegration.deleted_at == 0)
            return (await session.execute(sql)).scalars().first()
