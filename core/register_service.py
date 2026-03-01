"""
Gemini Business 注册服务
将 gemini_register.py 的 Selenium 注册逻辑封装为异步服务

艹，这个SB模块需要 Chrome 环境才能跑，别在没 Chrome 的容器里调用
"""
import asyncio
import json
import os
import time
import random
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from string import ascii_letters, digits
from typing import Optional, List, Dict, Any, Callable, Awaitable

import requests
from dotenv import load_dotenv

from core.config import config
from util.gemini_auth_utils import GeminiAuthConfig, GeminiAuthHelper, GeminiAuthFlow

# 加载环境变量
load_dotenv()

logger = logging.getLogger("gemini.register")

_CRON_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}
_CRON_DAYS = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6
}


def _normalize_cron_expr(expr: str) -> str:
    return " ".join(expr.strip().split())


def _parse_cron_value(value: str, names: Optional[Dict[str, int]] = None) -> int:
    if names:
        name_value = names.get(value.lower())
        if name_value is not None:
            return name_value
    return int(value)


def _parse_cron_field(
    field: str,
    min_value: int,
    max_value: int,
    names: Optional[Dict[str, int]] = None,
    allow_7_to_0: bool = False
) -> set:
    if field == "?":
        field = "*"

    values = set()
    parts = field.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            raise ValueError("Cron 字段为空")

        step = 1
        base = part
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if step <= 0:
                raise ValueError("Cron 步长必须大于 0")

        if base in ["*", "?"]:
            start, end = min_value, max_value
        elif "-" in base:
            start_str, end_str = base.split("-", 1)
            start = _parse_cron_value(start_str, names)
            end = _parse_cron_value(end_str, names)
        else:
            start = end = _parse_cron_value(base, names)

        if start > end:
            raise ValueError("Cron 范围起止值错误")

        for val in range(start, end + 1, step):
            values.add(val)

    if allow_7_to_0 and 7 in values:
        values.remove(7)
        values.add(0)

    out_of_range = [v for v in values if v < min_value or v > max_value]
    if out_of_range:
        raise ValueError("Cron 字段超出有效范围")

    return values


def _parse_cron_expression(expr: str) -> Dict[str, Any]:
    normalized = _normalize_cron_expr(expr)
    parts = normalized.split(" ")
    if len(parts) != 5:
        raise ValueError("Cron 表达式需 5 段")

    minute_field, hour_field, dom_field, month_field, dow_field = parts

    return {
        "minute": _parse_cron_field(minute_field, 0, 59),
        "hour": _parse_cron_field(hour_field, 0, 23),
        "dom": _parse_cron_field(dom_field, 1, 31),
        "month": _parse_cron_field(month_field, 1, 12, names=_CRON_MONTHS),
        "dow": _parse_cron_field(dow_field, 0, 7, names=_CRON_DAYS, allow_7_to_0=True),
        "dom_any": dom_field.strip() == "*",
        "dow_any": dow_field.strip() == "*",
    }


def _cron_matches(schedule: Dict[str, Any], now: datetime) -> bool:
    if now.minute not in schedule["minute"]:
        return False
    if now.hour not in schedule["hour"]:
        return False
    if now.month not in schedule["month"]:
        return False

    dom_match = now.day in schedule["dom"]
    cron_dow = (now.weekday() + 1) % 7
    dow_match = cron_dow in schedule["dow"]

    if schedule["dom_any"] and schedule["dow_any"]:
        return True
    if schedule["dom_any"]:
        return dow_match
    if schedule["dow_any"]:
        return dom_match
    return dom_match or dow_match


class RegisterStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class RegisterTask:
    """注册任务"""
    id: str
    count: int
    status: RegisterStatus = RegisterStatus.PENDING
    progress: int = 0
    success_count: int = 0
    fail_count: int = 0
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "count": self.count,
            "status": self.status.value,
            "progress": self.progress,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "finished_at": datetime.fromtimestamp(self.finished_at).isoformat() if self.finished_at else None,
            "results": self.results,
            "error": self.error
        }


class RegisterService:
    """注册服务 - 管理注册任务（艹，整合后简洁多了）"""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._tasks: Dict[str, RegisterTask] = {}
        self._current_task_id: Optional[str] = None
        self._email_queue: List[str] = []
        self._cron_task: Optional[asyncio.Task] = None
        self._is_cron_polling = False
        self._last_cron_run_key: Optional[str] = None
        self._cron_cache_expr: Optional[str] = None
        self._cron_cache: Optional[Dict[str, Any]] = None
        self._stop_requested = False  # 停止标志
        self._on_task_finished: Optional[Callable[[RegisterTask], Awaitable[None]]] = None
        self._on_before_auto_register: Optional[Callable[[], Awaitable[None]]] = None
        # 数据目录配置（与 main.py 保持一致）
        if os.path.exists("/data"):
            self.output_dir = Path("/data")
        else:
            self.output_dir = Path("./data")

        # 注意：不再在这里缓存 auth_config，改用 property 动态获取最新配置
        # 这样前端修改邮箱配置后热更新能立即生效
        pass

        # 指定的域名（用于批量注册时指定域名）
        self._specified_domain: Optional[str] = None

    def set_on_task_finished(self, callback: Optional[Callable[[RegisterTask], Awaitable[None]]]):
        """设置注册任务完成回调（用于触发热更新）"""
        self._on_task_finished = callback

    def set_on_before_auto_register(self, callback: Optional[Callable[[], Awaitable[None]]]):
        """设置自动注册触发前回调（用于执行清理等预处理）。"""
        self._on_before_auto_register = callback

    def _get_task_history_limit(self) -> int:
        """读取任务历史保留上限，异常时回退默认值。"""
        try:
            limit = int(getattr(config.auto_register, "task_history_limit", 10))
            return max(limit, 1)
        except Exception:
            return 10

    def _trim_task_history(self):
        """裁剪历史任务，避免长期运行时任务记录无限增长。"""
        limit = self._get_task_history_limit()
        if len(self._tasks) <= limit:
            return

        sorted_task_ids = sorted(self._tasks.keys(), key=lambda tid: self._tasks[tid].created_at)
        removed = 0
        for task_id in sorted_task_ids:
            if len(self._tasks) <= limit:
                break
            if task_id == self._current_task_id:
                continue
            if self._tasks.pop(task_id, None) is not None:
                removed += 1

        if removed:
            logger.info(f"[REGISTER] 已裁剪历史任务 {removed} 条，当前保留 {len(self._tasks)} 条")

    @property
    def auth_config(self) -> GeminiAuthConfig:
        """每次访问时动态获取最新配置，支持热更新"""
        return GeminiAuthConfig()

    @property
    def auth_helper(self) -> GeminiAuthHelper:
        """每次访问时动态获取最新配置，支持热更新"""
        return GeminiAuthHelper(self.auth_config)
    
    @staticmethod
    def _random_str(n: int = 10) -> str:
        """生成随机字符串（艹，用 sample 就行，choices 在某些环境会报错）"""
        return "".join(random.sample(ascii_letters + digits, n))
    
    def _create_email(self, domain: Optional[str] = None) -> Optional[str]:
        """
        创建临时邮箱

        Args:
            domain: 指定域名，如果为 None 则从配置的域名数组随机选择
        """
        if not self.auth_config.mail_api or not self.auth_config.admin_key:
            logger.error("❌ 邮箱 API 未配置")
            return None

        if not self.auth_config.email_domains:
            logger.error("❌ 邮箱域名未配置")
            return None

        try:
            # 如果未指定域名，从域名数组中随机选择一个
            if not domain:
                domain = random.choice(self.auth_config.email_domains)

            json_data = {
                "enablePrefix": False,
                "name": self._random_str(10),
                "domain": domain
            }
            r = requests.post(
                f"{self.auth_config.mail_api}/admin/new_address",
                headers={"x-admin-auth": self.auth_config.admin_key},
                json=json_data,
                timeout=30,
                verify=False
            )
            if r.status_code == 200:
                return r.json()['address']
        except Exception as e:
            logger.error(f"❌ 创建邮箱失败: {e}")
        return None

    def _get_email(self) -> Optional[str]:
        """获取邮箱（优先从队列取，否则创建新邮箱）"""
        if self._email_queue:
            return self._email_queue.pop(0)
        return self._create_email(self._specified_domain)
    
    def _save_config(self, email: str, data: dict) -> Optional[dict]:
        """保存账户配置到 accounts.json"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        accounts_file = self.output_dir / "accounts.json"

        config = {
            "id": email,
            "csesidx": data["csesidx"],
            "config_id": data["config_id"],
            "secure_c_ses": data["secure_c_ses"],
            "host_c_oses": data["host_c_oses"],
            "expires_at": data.get("expires_at")
        }

        # 读取现有配置
        accounts = []
        if accounts_file.exists():
            try:
                with open(accounts_file, 'r') as f:
                    accounts = json.load(f)
            except:
                accounts = []

        # 追加新账户配置
        accounts.append(config)

        # 保存配置
        with open(accounts_file, 'w') as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ 配置已保存到 accounts.json: {email}")
        return config
    
    def _register_one_sync(self) -> Dict[str, Any]:
        """
        同步执行单次注册 (在线程池中运行)
        """
        try:
            # 创建统一认证流程
            auth_flow = GeminiAuthFlow(self.auth_config, self.auth_helper)

            # 从配置读取重试次数
            from core.config import config
            max_retries = config.retry.max_verification_retries if config.retry.verification_retry_enabled else 1
            retry_interval = config.retry.verification_retry_interval_seconds

            # 代理重试配置（使用代理健康检查配置）
            proxy_retry_enabled = config.basic.proxy_health_check
            proxy_retry_count = config.basic.proxy_check_retry_count

            # 执行注册流程（带智能重试）
            result = auth_flow.execute(
                mode="register",
                email_creator=self._get_email,  # 传入邮箱创建函数
                max_retries=max_retries,  # 验证码重试次数
                retry_interval=retry_interval,  # 重试间隔
                proxy_retry_enabled=proxy_retry_enabled,  # 代理错误重试开关
                proxy_retry_count=proxy_retry_count  # 代理错误重试次数
            )

            if not result["success"]:
                return {
                    "email": result.get("email"),
                    "success": False,
                    "config": None,
                    "error": result.get("error")
                }

            # 保存配置
            email = result["email"]
            config_data = result["config"]
            config = self._save_config(email, config_data)

            logger.info(f"✅ 注册成功: {email}")
            return {"email": email, "success": True, "config": config, "error": None}

        except Exception as e:
            logger.error(f"❌ 注册异常: {e}")
            return {"email": None, "success": False, "config": None, "error": str(e)}
    
    async def start_register(self, count: int, domain: Optional[str] = None) -> RegisterTask:
        """
        启动注册任务

        Args:
            count: 注册数量
            domain: 指定域名，为 None 则随机选择
        """
        if self._current_task_id:
            current_task = self._tasks.get(self._current_task_id)
            if current_task and current_task.status == RegisterStatus.RUNNING:
                raise ValueError("已有注册任务在运行中")

        # 设置指定的域名
        self._specified_domain = domain

        task = RegisterTask(
            id=str(uuid.uuid4()),
            count=count
        )
        self._tasks[task.id] = task
        self._current_task_id = task.id
        self._trim_task_history()
        
        # 在后台线程执行注册
        asyncio.create_task(self._run_register_async(task))
        
        return task
    
    async def _run_register_async(self, task: RegisterTask):
        """异步执行注册任务"""
        task.status = RegisterStatus.RUNNING
        loop = asyncio.get_event_loop()
        
        try:
            for i in range(task.count):
                # 检查是否请求停止
                if self._stop_requested:
                    logger.warning(f"[REGISTER] 收到停止信号，中止注册任务")
                    task.status = RegisterStatus.FAILED
                    task.error = "用户中止"
                    break
                
                task.progress = i + 1
                result = await loop.run_in_executor(self._executor, self._register_one_sync)
                task.results.append(result)
                
                if result["success"]:
                    task.success_count += 1
                else:
                    task.fail_count += 1
                
                # 每次注册间隔
                if i < task.count - 1:
                    await asyncio.sleep(random.randint(2, 5))
            
            # 只有未被中止才设置为成功/失败状态
            if task.status == RegisterStatus.RUNNING:
                task.status = RegisterStatus.SUCCESS if task.success_count > 0 else RegisterStatus.FAILED
        except Exception as e:
            task.status = RegisterStatus.FAILED
            task.error = str(e)
        finally:
            task.finished_at = time.time()
            self._current_task_id = None
            self._stop_requested = False  # 重置停止标志
            self._trim_task_history()
            if self._on_task_finished:
                try:
                    await self._on_task_finished(task)
                except Exception as e:
                    logger.error(f"[REGISTER] 注册完成后回调失败: {e}")
    
    def get_task(self, task_id: str) -> Optional[RegisterTask]:
        """获取任务状态"""
        return self._tasks.get(task_id)
    
    def get_current_task(self) -> Optional[RegisterTask]:
        """获取当前运行的任务"""
        if self._current_task_id:
            return self._tasks.get(self._current_task_id)
        return None

    async def _start_auto_register(self):
        """按配置启动一次自动注册任务"""
        if self._on_before_auto_register:
            try:
                await self._on_before_auto_register()
            except Exception as e:
                logger.error(f"[REGISTER] 自动注册预处理失败: {e}")

        count = config.basic.register_number
        if count < 1:
            return

        try:
            task = await self.start_register(count, None)
            logger.info(f"[REGISTER] 自动注册任务已启动: {task.id} | count={count}")
        except ValueError as e:
            logger.info(f"[REGISTER] 自动注册跳过: {e}")
        except Exception as e:
            logger.error(f"[REGISTER] 自动注册启动失败: {e}")

    async def start_cron_polling(self):
        """启动自动注册 Cron 轮询"""
        if self._is_cron_polling:
            logger.warning("[REGISTER] 自动注册 Cron 轮询已在运行中")
            return

        self._is_cron_polling = True
        logger.info("[REGISTER] 自动注册 Cron 轮询已启动")

        try:
            while self._is_cron_polling:
                enabled = config.auto_register.enabled
                cron_expr = (config.auto_register.cron or "").strip()

                if not enabled or not cron_expr:
                    await asyncio.sleep(30)
                    continue

                if cron_expr != self._cron_cache_expr:
                    try:
                        self._cron_cache = _parse_cron_expression(cron_expr)
                        self._cron_cache_expr = cron_expr
                        logger.info(f"[REGISTER] 自动注册 Cron 已更新: {cron_expr}")
                    except Exception as e:
                        logger.error(f"[REGISTER] Cron 表达式错误: {e}")
                        self._cron_cache = None
                        self._cron_cache_expr = cron_expr
                        await asyncio.sleep(60)
                        continue

                if not self._cron_cache:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now()
                run_key = now.strftime("%Y-%m-%d %H:%M")
                if run_key != self._last_cron_run_key and _cron_matches(self._cron_cache, now):
                    self._last_cron_run_key = run_key
                    await self._start_auto_register()

                await asyncio.sleep(20)
        except asyncio.CancelledError:
            logger.info("[REGISTER] 自动注册 Cron 轮询已停止")
        except Exception as e:
            logger.error(f"[REGISTER] 自动注册 Cron 轮询异常: {e}")
        finally:
            self._is_cron_polling = False

    def stop_current_task(self):
        """停止当前注册任务"""
        if self._current_task_id:
            self._stop_requested = True
            logger.info(f"[REGISTER] 请求停止当前注册任务: {self._current_task_id}")
            return True
        return False
    
    def stop_cron_polling(self):
        """停止自动注册 Cron 轮询"""
        self._is_cron_polling = False
        logger.info("[REGISTER] 正在停止自动注册 Cron 轮询...")


# 全局注册服务实例
_register_service: Optional[RegisterService] = None


def get_register_service() -> RegisterService:
    """获取全局注册服务"""
    global _register_service
    if _register_service is None:
        _register_service = RegisterService()
    return _register_service
