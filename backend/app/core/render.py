"""
通过jinja2模板引擎解析上下文
"""
from functools import lru_cache

from jinja2 import Environment
from jinja2.sandbox import SandboxedEnvironment

from app.core.functions import PityFunction
from app.utils.logger import Log


def get_env(sandbox: bool = False):
    """
    构造模板环境。

    :param sandbox: True 时用 **SandboxedEnvironment** —— 挡住 Jinja2 SSTI
                    (`${cycler.__init__.__globals__.os.popen('id').read()}` 这类
                    能在服务器上执行命令的载荷)。未沙箱的 Environment 允许
                    通过 dunder 属性拿到 Python 内部对象。
    """
    my_env = SandboxedEnvironment() if sandbox else Environment()
    for func in dir(PityFunction):
        # 过滤掉内置方法
        if func.startswith("__"):
            continue
        my_env.globals[func] = getattr(PityFunction, func)
    my_env.variable_start_string = "${"
    my_env.variable_end_string = "}"
    return my_env


class Render(object):
    """
    渲染变量，用于上下文变量替换
    """
    _env = get_env()
    # 沙箱环境 —— 给「用户可控的模板文本」用(UI 用例的 base_url 与步骤字段)
    _safe_env = get_env(sandbox=True)

    @staticmethod
    @lru_cache(128)
    def load(source: str):
        """
        加载模板
        :param source:
        :return:
        """
        return Render._env.from_string(source)

    @staticmethod
    @lru_cache(128)
    def load_safe(source: str):
        """加载**沙箱**模板"""
        return Render._safe_env.from_string(source)

    @staticmethod
    def render(context: dict, source: str):
        """
        加载变量
        :param context:
        :param source:
        :return:
        """
        try:
            tmpl = Render.load(source)
            return tmpl.render(**context)
        except Exception as e:
            raise Exception(f"解析参数失败, 请检查变量是否获取到: {str(e)}")

    @staticmethod
    def render_safe(context: dict, source: str):
        """
        沙箱渲染。

        **给用户可控的文本用这个** —— 未沙箱的 Jinja2 能通过 dunder 属性
        拿到 Python 内部对象, 载荷形如
        `${cycler.__init__.__globals__.os.popen('id').read()}` 会在服务器上执行命令。
        沙箱环境禁止访问 dunder 属性, 同一批载荷只会渲染成原样文本。

        沙箱拒绝的属性访问**不抛错**, 而是按字面量返回 —— 载荷被挡住就够了,
        没必要让写错变量名的用户也吃一脸异常(未定义的普通变量本来就会被渲染成空串)。
        """
        try:
            tmpl = Render.load_safe(source)
            return tmpl.render(**context)
        except Exception as e:
            Log("Render").warning(f"沙箱渲染被拒绝, 按字面量返回: {str(e)[:120]}")
            return source
