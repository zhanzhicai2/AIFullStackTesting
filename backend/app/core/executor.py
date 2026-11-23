import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime
from typing import List, Callable

from app.core.constructor.case_constructor import TestcaseConstructor
from app.core.constructor.http_constructor import HttpConstructor
from app.core.constructor.python_constructor import PythonConstructor
from app.core.constructor.redis_constructor import RedisConstructor
from app.core.constructor.sql_constructor import SqlConstructor
from app.core.msg.dingtalk import DingTalk
from app.core.msg.mail import Email
from app.core.paramters import parameters_parser
from app.core.render import Render
from app.core.ws_connection_manager import ws_manage
from app.crud.auth.UserDao import UserDao
from app.crud.config.AddressDao import PityGatewayDao
from app.crud.config.EnvironmentDao import EnvironmentDao
from app.crud.config.GConfigDao import GConfigDao
from app.crud.project.ProjectDao import ProjectDao
from app.crud.test_case.TestCaseAssertsDao import TestCaseAssertsDao
from app.crud.test_case.TestCaseDao import TestCaseDao
from app.crud.test_case.TestCaseOutParametersDao import PityTestCaseOutParametersDao
from app.crud.test_case.TestPlan import PityTestPlanDao
from app.crud.test_case.TestReport import TestReportDao
from app.crud.test_case.TestResult import TestResultDao
from app.crud.test_case.TestcaseDataDao import PityTestcaseDataDao
from app.enums.ConstructorEnum import ConstructorType
from app.enums.GconfigEnum import GConfigParserEnum, GconfigType
from app.enums.NoticeEnum import NoticeType
from app.enums.RequestBodyEnum import BodyType
from app.enums.RequestTypeEnum import RequestType
from app.middleware.AsyncHttpClient import AsyncRequest
from app.models.constructor import Constructor
from app.models.out_parameters import PityTestCaseOutParameters
from app.models.project import Project
from app.models.test_plan import PityTestPlan
from app.utils.case_logger import CaseLog
from app.utils.decorator import case_log, lock
from app.utils.gconfig_parser import StringGConfigParser, JSONGConfigParser, YamlGConfigParser
from app.utils.json_compare import JsonCompare
from app.utils.logger import Log
from config import Config

# construct method mapping
construct_type = {
    ConstructorType.testcase: TestcaseConstructor,
    ConstructorType.sql: SqlConstructor,
    ConstructorType.redis: RedisConstructor,
    ConstructorType.py_script: PythonConstructor,
    ConstructorType.http: HttpConstructor,
}

# gconfig parser mapping
gconfig_parser = {
    GConfigParserEnum.string: StringGConfigParser.get_data,
    GConfigParserEnum.json: JSONGConfigParser.get_data,
    GConfigParserEnum.yaml: YamlGConfigParser.get_data,
}


class Executor(object):
    log = Log("Executor")
    # 需要替换全局变量的字段
    fields = ['body', 'url', 'request_headers']

    def __init__(self, log: CaseLog = None):
        # 这里是一个彩蛋, 奔驰大G LB（括弧1.3T）
        self.glb = None
        if log is None:
            self._logger = CaseLog()
            self._main = True
        else:
            self._logger = log
            self._main = False

    @property
    def logger(self):
        return self._logger

    @staticmethod
    def get_constructor_type(c: Constructor):
        return construct_type.get(c.type)

    def append(self, content, end=False):
        if end:
            self.logger.append(content, end)
        else:
            self.logger.append(content, end)

    async def load_testcase_variables(self, data, type_, params, *fields):
        """load_testcase_variables, include global variables"""
        for f in fields:
            self.append("解析{}: [{}]中的变量".format(GconfigType.text(type_), data, f))
            origin_field = getattr(data, f)
            # if not None or ""
            if origin_field:
                rendered = Render.render(params, origin_field)
                if rendered != origin_field:
                    self.append("替换变量成功, [{}]:\n\n[{}] -> [{}]\n".format(f, origin_field, rendered))
                    setattr(data, f, rendered)

    @case_log
    async def query_gconfig(self, env: int):
        """加载全局变量"""
        gconfig_list = await GConfigDao.list_gconfig(env)
        gconfig_map = dict()
        for g in gconfig_list:
            parser = Executor.get_parser(g.key_type)
            gconfig_map[g.key] = parser(g.value)
        self.glb = gconfig_map

    @staticmethod
    def get_parser(key_type) -> Callable:
        """获取变量解析器
        """
        parser = gconfig_parser.get(key_type)
        if parser is None:
            raise Exception(f"全局变量类型: {key_type}不合法, 请检查!")
        return parser

    @case_log
    async def get_constructor(self, case_id):
        """获取构造数据"""
        return await TestCaseDao.async_select_constructor(case_id)

    async def execute_constructors(self, env: int, path, params, constructors: List[Constructor], suffix=False):
        """开始构造数据"""
        if len(constructors) == 0:
            self.append("前后置条件为空, 跳出该环节")
            return
        current = 0
        for i, c in enumerate(constructors):
            if c.suffix == suffix:
                await self.execute_constructor(env, current, path, params, c)
                current += 1

    async def execute_constructor(self, env, index, path, params, constructor: Constructor):
        if not constructor.enable:
            self.append(f"当前路径: {path}, 构造方法: {constructor.name} 已关闭, 不继续执行")
            return False
        construct = Executor.get_constructor_type(constructor)
        if construct is None:
            self.append(f"构造方法类型: {constructor.type} 不合法, 请检查")
            return
        # 加载变量
        constructor.constructor_json = Render.render(params, constructor.constructor_json)
        resp = await construct.run(self, env, index, path, params, constructor, executor_class=Executor)
        if constructor.value and resp:
            params[constructor.value] = resp

    def add_header(self, case_info, headers):
        """
        @ desperate
        :param case_info:
        :param headers:
        :return:
        """
        if case_info.body_type == BodyType.none:
            return
        if case_info.body_type == BodyType.json:
            if "Content-Type" not in headers:
                headers['Content-Type'] = "application/json; charset=UTF-8"

    @case_log
    def extract_out_parameters(self, response_info, data: List[PityTestCaseOutParameters]):
        """提取出参数据"""
        result = dict()
        for d in data:
            p = parameters_parser(d.source)
            result[d.name] = p(response_info, d.expression, idx=d.match_index)
        return result

    async def run(self, env: int, case_id: int, params_pool: dict = None, request_param: dict = None, path="主case"):
        """
        开始执行测试用例
        """
        response_info = dict()

        # 初始化case全局变量, 只存在于case生命周期 注意 它与全局变量不是一套逻辑
        case_params = params_pool or dict()

        req_params = request_param or dict()

        # 加载全局变量
        await self.query_gconfig(env)

        # 挂载全局变量, 合并请求变量
        case_params.update(self.glb)
        case_params.update(req_params)

        try:
            case_info = await TestCaseDao.async_query_test_case(case_id)
            response_info['case_id'] = case_info.id
            response_info["case_name"] = case_info.name

            # UI 用例分派 —— 在 HTTP 请求之前。
            # UI 用例也是 pity_testcase 的一种(request_type = 4), 走既有的用例库、
            # 目录树与执行记录, 只是执行体换成浏览器。
            if case_info.request_type == RequestType.web_ui:
                return await self.run_ui(env, case_info, case_params, path)

            method = case_info.request_method.upper()
            response_info["request_method"] = method

            # Step1: 获取构造数据
            constructors = await self.get_constructor(case_id)

            # Step2: 获取断言
            asserts = await TestCaseAssertsDao.async_list_test_case_asserts(case_id)

            # Step3: 获取出参信息
            out_parameters = await PityTestCaseOutParametersDao.select_list(case_id=case_id)

            # Step4: 执行前置条件
            await self.execute_constructors(env, path, case_params, constructors)

            # Step5: 更新body url headers中的变量
            await self.load_testcase_variables(case_info, GconfigType.case, case_params, *Executor.fields)

            if case_info.request_headers and case_info.request_headers != "":
                headers = json.loads(case_info.request_headers)
            else:
                headers = dict()

            body = case_info.body if case_info.body != '' else None

            # Step6: 替换base_path
            if case_info.base_path:
                base_path = await PityGatewayDao.query_gateway(env, case_info.base_path)
                case_info.url = f"{base_path}{case_info.url}"

            response_info["url"] = case_info.url
            response_info["request_data"] = body

            # Step7: 完成http请求
            request_obj = await AsyncRequest.client(url=case_info.url, body_type=case_info.body_type, headers=headers,
                                                    body=body)
            res = await request_obj.invoke(method)
            self.append(f"http请求过程\n\nRequest Method: {case_info.request_method}\n\n"
                        f"Request Headers:\n{headers}\n\nUrl: {case_info.url}"
                        f"\n\nBody:\n{body}\n\nResponse:\n{res.get('response', '未获取到返回值')}")
            response_info.update(res)

            # 提取出参
            out_dict = self.extract_out_parameters(response_info, out_parameters)

            # 替换主变量
            case_params.update(out_dict)

            # Step8: 执行后置条件
            await self.execute_constructors(env, path, case_params, constructors, True)

            # Step9: 断言
            asserts, ok = self.my_assert(case_params, asserts)
            response_info["status"] = ok
            response_info["asserts"] = asserts
            # 日志输出, 如果不是主用例则不记录
            if self._main:
                response_info["logs"] = self.logger.join()
            return response_info, None
        except Exception as e:
            # 带上 case_id 与 path —— 只写「执行用例失败」根本不知道是哪条
            Executor.log.exception(f"执行用例失败: case_id={case_id} path={path}: {e}")
            self.append(f"执行用例失败: {str(e)}")
            if self._main:
                response_info["logs"] = self.logger.join()
            return response_info, f"执行用例失败: {str(e)}"

    @staticmethod
    def get_dict(json_data: str):
        return json.loads(json_data)

    async def run_ui(self, env: int, case_info, case_params: dict, path: str):
        """
        UI 用例的执行分支(request_type = 4)。

        **复用既有的前置 / 后置构造器** —— UI 用例也能配前置(准备数据)与后置(清理),
        不另起一套。结果照写 `pity_test_result`, 报告链路零改造。
        """
        from app.core.ui_executor import run_ui_case

        response_info = dict()
        response_info['case_id'] = case_info.id
        response_info["case_name"] = case_info.name
        # 前置条件
        constructors = await self.get_constructor(case_info.id)
        await self.execute_constructors(env, path, case_params, constructors)
        # 浏览器执行
        result = await run_ui_case(case_info.id, env, params=case_params, logger=self.logger)
        # 后置条件
        await self.execute_constructors(env, path, case_params, constructors, True)
        status = result.get("status", 2)
        response_info["url"] = result.get("url")
        response_info["request_data"] = ""
        response_info["request_headers"] = ""
        response_info["asserts"] = result.get("asserts") or "{}"
        response_info["steps"] = result.get("steps") or []
        response_info["response"] = result.get("error") or json.dumps(result.get("steps") or [],
                                                                        ensure_ascii=False)
        self.append(f"UI 用例执行结果: {status}")
        if status == 2:
            # 出错(不是断言失败)—— 交给外层的异常处理, 记为 status 2
            raise Exception(result.get("error") or "UI 用例执行出错")
        response_info["status"] = status == 0
        if self._main:
            response_info["logs"] = self.logger.join()
        return response_info, None

    @staticmethod
    async def run_with_test_data(env, data, report_id, case_id, params_pool: dict = None, request_param: dict = None,
                                 path='主case', name: str = "", data_id: int = None, retry_minutes: int = 0):
        retry_times = Config.RETRY_TIMES if retry_minutes > 0 else 0
        times = 0
        for i in range(retry_times + 1):
            start_at = datetime.now()
            executor = Executor()
            result, err = await executor.run(env, case_id, params_pool, request_param, path)
            finished_at = datetime.now()
            cost = "{}s".format((finished_at - start_at).seconds)
            if err is not None:
                status = 2
            else:
                status = 0 if result.get("status") else 1
            status_text = {0: "成功", 1: "断言失败", 2: "执行异常"}.get(status, status)
            # 若status不为0，代表case执行失败，走重试逻辑
            if status != 0 and i < retry_times:
                # 重试前必须留痕 —— 之前静默 sleep, 报告里看不出「这条用例其实跑了 3 遍」
                Executor.log.warning(f"用例执行失败, 准备重试(第 {i + 2}/{retry_times + 1} 次): "
                                     f"case_id={case_id} status={status} 等待 {retry_minutes} 分钟")
                await asyncio.sleep(60 * retry_minutes)
                times += 1
                continue
            asserts = result.get("asserts")
            url = result.get("url")
            case_logs = result.get("logs")
            body = result.get("request_data")
            status_code = result.get("status_code")
            request_method = result.get("request_method")
            request_headers = result.get("request_headers")
            response = result.get("response")
            if not isinstance(response, str):
                # dumps ensure response is str
                response = json.dumps(response, ensure_ascii=False)
            case_name = result.get("case_name")
            response_headers = result.get("response_headers")
            cookies = result.get("cookies")
            req = json.dumps(request_param, ensure_ascii=False)
            data[case_id].append(status)
            await TestResultDao.insert_report(report_id, case_id, case_name, status,
                                              case_logs, start_at, finished_at,
                                              url, body, request_method, request_headers, cost,
                                              asserts, response_headers, response,
                                              status_code, cookies, times, req, name, data_id)
            # 结果落盘后留一条汇总 —— 不用翻报告页也能从日志看到每条用例的结局
            Executor.log.info(f"用例执行完成: case_id={case_id} name={case_name} "
                              f"status={status_text} cost={cost} 重试={times} 数据组={name}")
            break

    @staticmethod
    async def run_single(env: int, data, report_id, case_id, params_pool: dict = None, path="主case", retry_minutes=0):
        test_data = await PityTestcaseDataDao.list_testcase_data_by_env(env, case_id)
        if not test_data:
            await Executor.run_with_test_data(env, data, report_id, case_id, params_pool, dict(), path,
                                              "默认数据", retry_minutes=retry_minutes)
        else:
            await asyncio.gather(
                *(Executor.run_with_test_data(env, data, report_id, case_id, params_pool,
                                              Executor.get_dict(x.json_data),
                                              path, x.name, x.id, retry_minutes=retry_minutes)
                  for x in test_data))

    @staticmethod
    def get_time():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @case_log
    def my_assert(self, params, asserts: List) -> [str, bool]:
        """
        断言验证
        """
        result = dict()
        ok = True
        if len(asserts) == 0:
            self.append("未设置断言, 用例结束")
            return json.dumps(result, ensure_ascii=False), ok
        for item in asserts:
            try:
                # 解析预期/实际结果
                exp = Render.render(params, item.expected)
                act = Render.render(params, item.actually)
                expected = self.translate(exp)
                # 判断请求返回是否是json格式，如果不是则不进行loads操作
                actually = self.translate(act)
                status, err = self.ops(item.assert_type, expected, actually)
                if not status:
                    ok = False
                result[item.id] = {"status": status, "msg": err}
            except Exception as e:
                ok = False
                self.append(f"预期结果: {item.expected}\n实际结果: {item.actually}\n")
                result[item.id] = {"status": False, "msg": f"断言取值失败, 请检查断言语句: {e}"}
        return json.dumps(result, ensure_ascii=False), ok

    @case_log
    def ops(self, assert_type: str, exp, act) -> (bool, str):
        """
        通过断言类型进行校验
        """
        if assert_type == "equal":
            if exp == act:
                return True, f"预期结果: {exp} 等于 实际结果: {act}【✔】"
            return False, f"预期结果: {exp} 不等于 实际结果: {act}【❌】"
        if assert_type == "not_equal":
            if exp != act:
                return True, f"预期结果: {exp} 不等于 实际结果: {act}【✔】"
            return False, f"预期结果: {exp} 等于 实际结果: {act}【❌】"
        if assert_type == "in":
            if exp in act:
                return True, f"预期结果: {exp} 包含于 实际结果: {act}【✔】"
            return False, f"预期结果: {exp} 不包含于 实际结果: {act}【❌】"
        if assert_type == "not_in":
            if exp not in act:
                return True, f"预期结果: {exp} 不包含于 实际结果: {act}【✔】"
            return False, f"预期结果: {exp} 包含于 实际结果: {act}【❌】"
        if assert_type == "contain":
            if act in exp:
                return True, f"预期结果: {exp} 包含 实际结果: {act}【✔】"
            return False, f"预期结果: {exp} 不包含 实际结果: {act}【❌】"
        if assert_type == "not_contain":
            if act not in exp:
                return True, f"预期结果: {exp} 不包含 实际结果: {act}【✔】"
            return False, f"预期结果: {exp} 包含 实际结果: {act}【❌】"
        if assert_type == "length_eq":
            if exp == len(act):
                return True, f"预期数量: {exp} 等于 实际数量: {len(act)}【✔】"
            return False, f"预期数量: {exp} 不等于 实际数量: {len(act)}【❌】"
        if assert_type == "length_gt":
            if exp > len(act):
                return True, f"预期数量: {exp} 大于 实际数量: {len(act)}【✔】"
            return False, f"预期数量: {exp} 不大于 实际数量: {len(act)}【❌】"
        if assert_type == "length_ge":
            if exp >= len(act):
                return True, f"预期数量: {exp} 大于等于 实际数量: {len(act)}【✔】"
            return False, f"预期数量: {exp} 小于 实际数量: {len(act)}【❌】"
        if assert_type == "length_le":
            if exp <= len(act):
                return True, f"预期数量: {exp} 小于等于 实际数量: {len(act)}【✔】"
            return False, f"预期数量: {exp} 大于 实际数量: {len(act)}【❌】"
        if assert_type == "length_lt":
            if exp < len(act):
                return True, f"预期数量: {exp} 小于 实际数量: {len(act)}【✔】"
            return False, f"预期数量: {exp} 不小于 实际数量: {len(act)}【❌】"
        if assert_type == "json_equal":
            data = JsonCompare().compare(exp, act)
            if len(data) == 0:
                return True, "预期JSON 等于 实际JSON【✔】"
            return False, data
        if assert_type == "text_in":
            if isinstance(act, str):
                # 如果b是string，则不转换
                if exp in act:
                    return True, f"预期结果: {exp} 文本包含于 实际结果: {act}【✔】"
                return False, f"预期结果: {exp} 文本不包含于 实际结果: {act}【❌】"
            temp = json.dumps(act, ensure_ascii=False)
            if exp in temp:
                return True, f"预期结果: {exp} 文本包含于 实际结果: {act}【✔】"
            return False, f"预期结果: {exp} 文本不包含于 实际结果: {act}【❌】"
        if assert_type == "text_not_in":
            if isinstance(act, str):
                if exp in act:
                    return True, f"预期结果: {exp} 文本包含于 实际结果: {act}【❌】"
                return False, f"预期结果: {exp} 文本不包含于 实际结果: {act}【✔】"
            temp = json.dumps(act, ensure_ascii=False)
            if exp in temp:
                return True, f"预期结果: {exp} 文本包含于 实际结果: {act}【❌】"
            return False, f"预期结果: {exp} 文本不包含于 实际结果: {act}【✔】"
        return False, "不支持的断言方式💔"

    @case_log
    def translate(self, result):
        """
        尝试反序列化为Python对象
        """

        if isinstance(result, bytes):
            return result.decode()

        # 优先判断是否是时间
        try:
            return datetime.strptime(result, "%Y-%m-%d %H:%M:%S")
        except:
            pass

        try:
            return datetime.strptime(result, "%Y-%m-%d %H:%M:%S.%f")
        except:
            pass

        if result == '':
            return None
        try:
            return json.loads(result)
        except:
            return result

    @staticmethod
    async def notice(env: list, plan: PityTestPlan, project: Project, report_dict: dict, users: list):
        """
        消息通知方法
        :param env:
        :param plan:
        :param project:
        :param report_dict:
        :param users:
        :return:
        """
        for e in env:
            msg_types = plan.msg_type.split(",")
            if msg_types and users:
                for m in msg_types:
                    if int(m) == NoticeType.EMAIL:
                        render_html = Email.render_html(plan_name=plan.name, **report_dict[e])
                        await Email.send_msg(
                            f"【{report_dict[e].get('env')}】测试计划【{plan.name}】执行完毕（{report_dict[e].get('plan_result')}）",
                            render_html, None, *[r.get("email") for r in users])
                    if int(m) == NoticeType.DINGDING:
                        report_dict[e]['result_color'] = '#67C23A' if report_dict[e]['plan_result'] == '通过' \
                            else '#E6A23C'
                        # 批量获取用户手机号
                        ding_users = [r.get("phone") for r in users]
                        report_dict[e]['notification_user'] = " ".join(map(lambda x: f"@{x}", ding_users))
                        render_markdown = DingTalk.render_markdown(**report_dict[e], plan_name=plan.name)
                        if not project.dingtalk_url:
                            Executor.log.debug("项目未配置钉钉通知机器人")
                            continue
                        ding = DingTalk(project.dingtalk_url)
                        await ding.send_msg("pity测试报告", render_markdown, None, ding_users,
                                            link=report_dict[e]['report_url'])

    @staticmethod
    @lock("test_plan")
    async def run_test_plan(plan_id: int, executor: int = 0):
        """
        通过测试计划id执行测试计划
        :param plan_id:
        :param executor:
        :return:
        """
        plan = await PityTestPlanDao.query_test_plan(plan_id)
        if plan is None:
            # 计划不存在是异常(可能被删了但 cron 还在), 不该用 debug 淹没
            Executor.log.warning(f"测试计划: [{plan_id}]不存在, 跳过本次调度")
            return
        try:
            # 设置为running
            await PityTestPlanDao.update_test_plan_state(plan.id, 1)
            project, _ = await ProjectDao.query_project(plan.project_id)
            env = list(map(int, plan.env.split(",")))
            case_list = list(map(int, plan.case_list.split(",")))
            receiver = list(map(int, plan.receiver.split(",") if plan.receiver else []))
            # 聚合报告dict
            report_dict = dict()
            await asyncio.gather(
                *(Executor.run_multiple(executor, int(e), case_list, mode=1, retry_minutes=plan.retry_minutes,
                                        plan_id=plan.id, ordered=plan.ordered, report_dict=report_dict) for e in env))
            await PityTestPlanDao.update_test_plan_state(plan.id, 0)
            users = await UserDao.list_user_touch(*receiver)
            await Executor.notice(env, plan, project, report_dict, users)
            if executor != 0:
                await ws_manage.notify(executor, title="测试计划执行完毕", content=f"请前往测试报告页面查看细节")
        except Exception as e:
            # exception 已带完整堆栈, 不再补一条重复的 error
            Executor.log.exception(f"执行测试计划: 【{plan.name}】失败: {str(e)}")

    @staticmethod
    async def run_multiple(executor: int, env: int, case_list: List[int], mode=0, plan_id: int = None, ordered=False,
                           report_dict: dict = None, retry_minutes: int = 0):
        try:
            current_env = await EnvironmentDao.query_env(env)
            if executor != 0:
                # 说明不是系统执行
                user = await UserDao.query_user(executor)
                name = user.name if user is not None else "未知"
            else:
                name = "pity机器人"
            st = time.perf_counter()
            # step1: 新增测试报告数据
            report_id = await TestReportDao.start(executor, env, mode, plan_id=plan_id)
            # step2: 开始执行用例
            result_data = defaultdict(list)
            # step3: 将报告改为 running状态
            await TestReportDao.update(report_id, 1)
            # step4: 执行用例并搜集数据
            if not ordered:
                await asyncio.gather(
                    *(Executor.run_single(env, result_data, report_id, c, retry_minutes=retry_minutes) for c in
                      case_list))
            else:
                # 顺序执行
                for c in case_list:
                    await Executor.run_single(env, result_data, report_id, c, retry_minutes=retry_minutes)
            ok, fail, skip, error = 0, 0, 0, 0
            for case_id, status in result_data.items():
                for s in status:
                    if s == 0:
                        ok += 1
                    elif s == 1:
                        fail += 1
                    elif s == 2:
                        error += 1
                    else:
                        skip += 1
            cost = time.perf_counter() - st
            cost = "%.2f" % cost
            # step5: 回写数据到报告
            report = await TestReportDao.end(report_id, ok, fail, error, skip, 3, cost)
            if report_dict is not None:
                report_dict[env] = {
                    "report_url": f"{Config.SERVER_REPORT}{report_id}",
                    "start_time": report.start_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_time": report.finished_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "success": ok,
                    "failed": fail,
                    "total": ok + fail + error + skip,
                    "error": error,
                    "skip": skip,
                    "executor": name,
                    "cost": cost,
                    "plan_result": "通过" if ok + fail + error + skip > 0 and fail + error == 0 else '未通过',
                    "env": current_env.name,
                }
            return report_id
        except Exception as e:
            raise Exception(f"批量执行用例失败: {e}")
