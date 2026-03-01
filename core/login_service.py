"""
Gemini Business 登录刷新服务
用于刷新即将过期的账户配置

艹，这个SB模块需要 Chrome 环境才能跑，别在没 Chrome 的容器里调用
"""
import asyncio
import json
import os
import time
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

from core.config import config
from util.gemini_auth_utils import GeminiAuthConfig, GeminiAuthHelper, GeminiAuthFlow

# 加载环境变量
load_dotenv()

logger = logging.getLogger("gemini.login")


class LoginStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class LoginTask:
    """登录刷新任务"""
    id: str
    account_ids: List[str]  # 需要刷新的账户ID列表
    status: LoginStatus = LoginStatus.PENDING
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
            "account_ids": self.account_ids,
            "status": self.status.value,
            "progress": self.progress,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "finished_at": datetime.fromtimestamp(self.finished_at).isoformat() if self.finished_at else None,
            "results": self.results,
            "error": self.error
        }


class LoginService:
    """登录刷新服务 - 管理账户刷新任务"""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._tasks: Dict[str, LoginTask] = {}
        self._current_task_id: Optional[str] = None
        # 数据目录配置（与 main.py 保持一致）
        if os.path.exists("/data"):
            self.output_dir = Path("/data")
        else:
            self.output_dir = Path("./data")
        self._polling_task: Optional[asyncio.Task] = None
        self._is_polling = False

        # 注意：不再在这里缓存 auth_config，改用 property 动态获取最新配置
        # 这样前端修改邮箱配置后热更新能立即生效
        pass

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
            logger.info(f"[LOGIN] 已裁剪历史任务 {removed} 条，当前保留 {len(self._tasks)} 条")

    @property
    def auth_config(self) -> GeminiAuthConfig:
        """每次访问时动态获取最新配置，支持热更新"""
        return GeminiAuthConfig()

    @property
    def auth_helper(self) -> GeminiAuthHelper:
        """每次访问时动态获取最新配置，支持热更新"""
        return GeminiAuthHelper(self.auth_config)

    def _update_account_config(self, email: str, data: dict) -> Optional[dict]:
        """更新账户配置到 accounts.json"""
        accounts_file = self.output_dir / "accounts.json"

        # 读取现有配置
        accounts = []
        if accounts_file.exists():
            try:
                with open(accounts_file, 'r') as f:
                    accounts = json.load(f)
            except:
                accounts = []

        # 查找并更新对应账户
        updated = False
        for account in accounts:
            if account.get("id") == email:
                account["csesidx"] = data["csesidx"]
                account["config_id"] = data["config_id"]
                account["secure_c_ses"] = data["secure_c_ses"]
                account["host_c_oses"] = data["host_c_oses"]
                account["expires_at"] = data.get("expires_at")
                updated = True
                break

        if not updated:
            logger.warning(f"[LOGIN] 账户 {email} 不存在于 accounts.json，跳过更新")
            return None

        # 保存配置
        with open(accounts_file, 'w') as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ 配置已更新: {email}")
        return data

    def _login_one_sync(self, email: str) -> Dict[str, Any]:
        """
        同步执行单次登录刷新 (在线程池中运行)
        返回: {"email": str, "success": bool, "config": dict|None, "error": str|None}

        艹，现在用统一的 GeminiAuthFlow 了，代码简洁多了！
        """
        try:
            # 创建统一认证流程
            auth_flow = GeminiAuthFlow(self.auth_config, self.auth_helper)

            # 从配置读取重试次数（艹，不能写死参数！）
            max_retries = config.retry.max_verification_retries if config.retry.verification_retry_enabled else 1
            retry_interval = config.retry.verification_retry_interval_seconds

            # 代理重试配置（使用代理健康检查配置）
            proxy_retry_enabled = config.basic.proxy_health_check
            proxy_retry_count = config.basic.proxy_check_retry_count

            # 执行登录流程（带智能重试）
            result = auth_flow.execute(
                mode="login",
                email=email,
                max_retries=max_retries,  # 验证码重试次数
                retry_interval=retry_interval,  # 重试间隔
                proxy_retry_enabled=proxy_retry_enabled,  # 代理错误重试开关
                proxy_retry_count=proxy_retry_count  # 代理错误重试次数
            )

            if not result["success"]:
                return {
                    "email": email,
                    "success": False,
                    "config": None,
                    "error": result.get("error")
                }

            # 更新配置
            config_data = result["config"]
            updated_config = self._update_account_config(email, config_data)

            logger.info(f"✅ 登录刷新成功: {email}")
            return {"email": email, "success": True, "config": updated_config, "error": None}

        except Exception as e:
            logger.error(f"❌ 登录刷新异常 [{email}]: {e}")
            return {"email": email, "success": False, "config": None, "error": str(e)}

    async def start_login(self, account_ids: List[str]) -> LoginTask:
        """启动登录刷新任务"""
        if self._current_task_id:
            current_task = self._tasks.get(self._current_task_id)
            if current_task and current_task.status == LoginStatus.RUNNING:
                raise ValueError("已有登录刷新任务在运行中")

        task = LoginTask(
            id=str(uuid.uuid4()),
            account_ids=account_ids
        )
        self._tasks[task.id] = task
        self._current_task_id = task.id
        self._trim_task_history()

        # 在后台线程执行登录刷新
        asyncio.create_task(self._run_login_async(task))

        return task

    async def _run_login_async(self, task: LoginTask):
        """异步执行登录刷新任务"""
        task.status = LoginStatus.RUNNING
        loop = asyncio.get_event_loop()

        try:
            for i, account_id in enumerate(task.account_ids):
                task.progress = i + 1
                result = await loop.run_in_executor(self._executor, self._login_one_sync, account_id)
                task.results.append(result)

                if result["success"]:
                    task.success_count += 1
                else:
                    task.fail_count += 1

                # 每次刷新间隔
                if i < len(task.account_ids) - 1:
                    await asyncio.sleep(2)

            task.status = LoginStatus.SUCCESS if task.success_count > 0 else LoginStatus.FAILED
        except Exception as e:
            task.status = LoginStatus.FAILED
            task.error = str(e)
        finally:
            task.finished_at = time.time()
            self._current_task_id = None
            self._trim_task_history()

    def get_task(self, task_id: str) -> Optional[LoginTask]:
        """获取任务状态"""
        return self._tasks.get(task_id)

    def get_current_task(self) -> Optional[LoginTask]:
        """获取当前运行的任务"""
        if self._current_task_id:
            return self._tasks.get(self._current_task_id)
        return None

    def _get_expiring_accounts(self) -> List[str]:
        """获取1小时内即将过期的账户ID列表"""
        accounts_file = self.output_dir / "accounts.json"

        if not accounts_file.exists():
            return []

        try:
            with open(accounts_file, 'r') as f:
                accounts = json.load(f)
        except:
            return []

        expiring = []
        beijing_tz = timezone(timedelta(hours=8))
        now = datetime.now(beijing_tz)

        for account in accounts:
            expires_at = account.get("expires_at")
            if not expires_at:
                continue

            try:
                expire_time = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                expire_time = expire_time.replace(tzinfo=beijing_tz)
                remaining = (expire_time - now).total_seconds() / 3600

                # 1小时内即将过期
                if 0 < remaining <= 1:
                    expiring.append(account.get("id"))
            except:
                continue

        return expiring

    async def check_and_refresh(self):
        """检查并刷新即将过期的账户"""
        expiring_accounts = self._get_expiring_accounts()

        if not expiring_accounts:
            logger.debug("[LOGIN] 没有需要刷新的账户")
            return

        logger.info(f"[LOGIN] 发现 {len(expiring_accounts)} 个账户即将过期，开始刷新")

        try:
            task = await self.start_login(expiring_accounts)
            logger.info(f"[LOGIN] 刷新任务已创建: {task.id}")
        except ValueError as e:
            logger.warning(f"[LOGIN] {e}")

    async def start_polling(self):
        """启动轮询任务（每30分钟检查一次）"""
        if self._is_polling:
            logger.warning("[LOGIN] 轮询任务已在运行中")
            return

        self._is_polling = True
        logger.info("[LOGIN] 账户过期检查轮询已启动（间隔: 30分钟）")

        try:
            while self._is_polling:
                await self.check_and_refresh()
                await asyncio.sleep(1800)  # 30分钟
        except asyncio.CancelledError:
            logger.info("[LOGIN] 轮询任务已停止")
        except Exception as e:
            logger.error(f"[LOGIN] 轮询任务异常: {e}")
        finally:
            self._is_polling = False

    def stop_polling(self):
        """停止轮询任务"""
        self._is_polling = False
        logger.info("[LOGIN] 正在停止轮询任务...")


# 全局登录服务实例
_login_service: Optional[LoginService] = None


def get_login_service() -> LoginService:
    """获取全局登录服务"""
    global _login_service
    if _login_service is None:
        _login_service = LoginService()
    return _login_service
