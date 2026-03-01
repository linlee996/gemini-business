"""
Gemini Business 认证工具类
抽取注册和登录服务的公共逻辑，遵循 DRY 原则
"""
import json
import os
import re
import shutil
import subprocess
import time
import logging
import random
import signal
import tempfile
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs
from datetime import datetime

import requests
import urllib3
from selenium.webdriver import ActionChains

from core.config import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("gemini.auth_utils")


def _safe_quit_driver(driver) -> None:
    """尽量安全关闭 Selenium driver，避免残留进程。"""
    if not driver:
        return

    try:
        driver.quit()
    except Exception as e:
        logger.warning(f"[AUTH] driver.quit() 异常: {e}")


def _kill_chrome_processes_by_profile(profile_dir: Optional[str]) -> None:
    """按 user-data-dir 定位并清理残留 Chrome/ChromeDriver 进程（Linux）。"""
    if not profile_dir or os.name != "posix":
        return

    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return

    profile_dir = os.path.realpath(profile_dir)
    target_pids: List[int] = []

    for entry in os.scandir(proc_root):
        if not entry.name.isdigit():
            continue

        cmdline_path = os.path.join(proc_root, entry.name, "cmdline")
        try:
            with open(cmdline_path, "rb") as f:
                cmdline = f.read().decode("utf-8", errors="ignore")
        except Exception:
            continue

        if profile_dir in cmdline:
            target_pids.append(int(entry.name))

    if not target_pids:
        return

    for sig in (signal.SIGTERM, signal.SIGKILL):
        remaining: List[int] = []
        for pid in target_pids:
            try:
                os.kill(pid, sig)
                remaining.append(pid)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue

        if not remaining:
            break

        time.sleep(0.3)
        target_pids = [pid for pid in remaining if os.path.exists(f"/proc/{pid}")]
        if not target_pids:
            break


def _cleanup_profile_dir(profile_dir: Optional[str]) -> None:
    """删除临时 Chrome 用户目录，避免缓存长期堆积。"""
    if not profile_dir:
        return

    try:
        shutil.rmtree(profile_dir, ignore_errors=True)
    except Exception as e:
        logger.warning(f"[AUTH] 清理临时 profile 失败: {e}")


# ==================== 拟人化工具函数 ====================

def human_delay(min_sec: float, max_sec: float, reason: str = "") -> None:
    """
    拟人化的随机延迟（艹，固定延迟太假了）

    Args:
        min_sec: 最小延迟（秒）
        max_sec: 最大延迟（秒）
        reason: 延迟原因（用于日志）
    """
    # 基础随机延迟
    delay = random.uniform(min_sec, max_sec)

    # 添加微小的"不规则性"（模拟神经反应波动）
    jitter = random.gauss(0, 0.05)  # 正态分布的抖动
    delay += jitter

    # 确保不小于最小值
    delay = max(delay, min_sec)

    if reason and logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"⏳ 人性化延迟 {delay:.3f}s ({reason})")

    time.sleep(delay)


def human_like_typing(element, text: str) -> None:
    """
    模拟真人打字节奏

    Args:
        element: Selenium WebElement
        text: 要输入的文本
    """
    for i, c in enumerate(text):
        # 1. 基础打字速度：人类平均 80-150ms/字符
        base_delay = random.uniform(0.08, 0.15)

        # 2. 特殊字符延迟（@、.、-等需要思考位置）
        if c in ['@', '.', '_', '-', '+']:
            base_delay += random.uniform(0.05, 0.12)

        # 3. 模拟连续字符的加速（肌肉记忆）
        if i > 0 and text[i-1].isalpha() and c.isalpha():
            base_delay *= random.uniform(0.7, 0.9)  # 连续打字会加速

        # 4. 偶尔有"思考"停顿（10% 概率）
        if random.random() < 0.1:
            base_delay += random.uniform(0.2, 0.5)

        # 5. 偶尔有"快速连击"（模拟熟练区域，15% 概率）
        if random.random() < 0.15:
            base_delay *= random.uniform(0.4, 0.6)

        element.send_keys(c)
        time.sleep(base_delay)


def human_like_click(driver, element) -> None:
    """
    模拟真人的鼠标移动和点击（艹，直接点击太假了）

    Args:
        driver: Selenium WebDriver
        element: 要点击的元素
    """
    from selenium.webdriver.common.action_chains import ActionChains

    actions = ActionChains(driver)

    # 1. 随机偏移（真人不会精准点击中心点）
    offset_x = random.randint(-5, 5)
    offset_y = random.randint(-5, 5)

    # 2. 缓慢移动到元素（模拟人眼定位 + 鼠标移动）
    actions.move_to_element_with_offset(element, offset_x, offset_y)
    actions.pause(random.uniform(0.1, 0.3))  # 移动后停顿

    # 3. 点击前的微小延迟（手指按下前的反应时间）
    actions.pause(random.uniform(0.05, 0.15))
    actions.click()
    actions.perform()


def human_like_button_click(driver, element) -> None:
    """
    模拟真人点击按钮（包含寻找、悬停、点击完整流程）
    艹，这个比简单点击更拟人！

    Args:
        driver: Selenium WebDriver
        element: 按钮元素
    """
    from selenium.webdriver.common.action_chains import ActionChains

    actions = ActionChains(driver)

    # 1. 模拟"寻找按钮"的过程（移动路径不是直线）
    # 先移动到按钮附近的随机位置
    actions.move_to_element_with_offset(element, random.randint(-20, -10), random.randint(-10, 10))
    actions.pause(random.uniform(0.1, 0.2))
    actions.perform()

    # 2. 再修正到按钮上（模拟视觉定位）
    actions = ActionChains(driver)
    actions.move_to_element_with_offset(element, random.randint(-3, 3), random.randint(-3, 3))
    actions.pause(random.uniform(0.2, 0.4))  # 鼠标悬停（hover）效果
    actions.perform()

    # 3. 点击前的决策延迟
    human_delay(0.2, 0.5, "点击前思考")

    # 4. 点击（使用自然事件，不用 JS）
    actions = ActionChains(driver)
    actions.click()
    actions.perform()

    # 5. 点击后的微小延迟（手指抬起时间）
    time.sleep(random.uniform(0.05, 0.15))


def human_like_focus(driver, element) -> None:
    """
    模拟真人的焦点获取行为（艹，直接 clear() 太粗暴了）

    Args:
        driver: Selenium WebDriver
        element: 输入框元素
    """
    from selenium.webdriver.common.keys import Keys

    # 1. 点击输入框
    human_like_click(driver, element)

    # 2. 检查是否有预填充内容（真人会先看）
    current_value = element.get_attribute('value')
    if current_value:
        # 模拟"全选 + 删除"（真人的习惯动作）
        human_delay(0.1, 0.3, "发现预填充内容")
        element.send_keys(Keys.CONTROL + 'a')  # 全选
        time.sleep(random.uniform(0.05, 0.15))
        element.send_keys(Keys.BACKSPACE)  # 删除
    else:
        # 没有内容，轻微停顿后开始输入
        human_delay(0.1, 0.2, "输入框为空，准备输入")


def human_like_email_check(driver, element, email: str) -> None:
    """
    模拟真人输入邮箱后的检查行为（艹，真人会回看邮箱的）

    Args:
        driver: Selenium WebDriver
        element: 邮箱输入框元素
        email: 输入的邮箱
    """
    from selenium.webdriver.common.keys import Keys

    # 1. 输入完成后的"视觉检查"延迟
    human_delay(0.3, 0.7, "检查邮箱格式")

    # 2. 模拟光标移动检查（20% 概率）
    if random.random() < 0.2:
        element.send_keys(Keys.HOME)  # 光标移到开头
        time.sleep(random.uniform(0.2, 0.4))
        element.send_keys(Keys.END)  # 光标移到末尾
        time.sleep(random.uniform(0.1, 0.3))

    # 3. 模拟"失焦检查"（点击输入框外，触发校验，30% 概率）
    if random.random() < 0.3:
        from selenium.webdriver.common.by import By
        try:
            # 点击页面空白区域
            body = driver.find_element(By.TAG_NAME, 'body')
            actions = ActionChains(driver)
            actions.move_to_element_with_offset(body, 100, 100)
            actions.click()
            actions.perform()
            human_delay(0.2, 0.5, "失焦后检查校验")
            # 再次点击输入框
            human_like_click(driver, element)
            human_delay(0.1, 0.3, "重新聚焦")
        except:
            pass  # 失焦检查失败也没关系

    # 4. 最终确认延迟（思考"确定要用这个邮箱吗"）
    human_delay(0.5, 1.2, "最终确认")


def human_like_scroll_into_view(driver, element) -> None:
    """
    模拟真人滚动页面到元素可见（艹，瞬移太假了）

    Args:
        driver: Selenium WebDriver
        element: 目标元素
    """
    # 1. 检查元素是否在视口内
    is_in_viewport = driver.execute_script("""
        var elem = arguments[0];
        var rect = elem.getBoundingClientRect();
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= window.innerHeight &&
            rect.right <= window.innerWidth
        );
    """, element)

    if not is_in_viewport:
        # 2. 模拟滚轮滚动（不是瞬移）
        element_y = driver.execute_script("return arguments[0].getBoundingClientRect().top;", element)
        scroll_distance = element_y - 200  # 滚动到元素上方留白

        # 分段滚动（模拟滚轮的多次滚动）
        scroll_steps = random.randint(3, 6)
        for step in range(scroll_steps):
            step_distance = scroll_distance / scroll_steps
            driver.execute_script(f"window.scrollBy(0, {step_distance});")
            time.sleep(random.uniform(0.05, 0.15))  # 滚动间隔

        # 3. 滚动后的停顿（视觉定位时间）
        human_delay(0.3, 0.6, "滚动后定位元素")

def get_chrome_path_and_major():
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.driver_finder import DriverFinder
    from selenium.webdriver.chrome.options import Options as SeleniumChromeOptions
    # 用 Selenium 的定位逻辑找到浏览器路径（browser_path）
    detect_opts = SeleniumChromeOptions()
    detect_opts.set_capability("browserName", "chrome")

    finder = DriverFinder(ChromeService(), detect_opts)  # ✅ 不能用 common.service.Service()
    chrome_path = finder.get_browser_path()              # 返回 browser_path :contentReference[oaicite:1]{index=1}

    # 用这个路径跑 --version 解析主版本号
    out = subprocess.check_output([chrome_path, "--version"], text=True).strip()
    major = int(re.search(r"(\d+)\.", out).group(1))
    logger.info(f"🔍 检测到 Chrome 浏览器: {chrome_path} {isinstance(chrome_path, str)}| 版本: {out}")
    return chrome_path, major, out

# ==================== 代理错误检测 ====================

# 代理相关错误关键词（用于识别代理问题）
PROXY_ERROR_KEYWORDS = [
    "ERR_PROXY",
    "ERR_TUNNEL",
    "ERR_CONNECTION",
    "ERR_TIMED_OUT",
    "ERR_NAME_NOT_RESOLVED",
    "PROXY_CONNECTION_FAILED",
    "SOCKS",
    "proxy",
    "Connection refused",
    "Connection reset",
    "Connection timed out",
    "net::ERR_",
]


def is_proxy_error(error_message: str) -> bool:
    """
    检测是否为代理相关错误

    Args:
        error_message: 错误信息字符串

    Returns:
        True 表示是代理错误，False 表示不是
    """
    if not error_message:
        return False

    error_lower = error_message.lower()

    # 检查关键词
    for keyword in PROXY_ERROR_KEYWORDS:
        if keyword.lower() in error_lower:
            return True

    # 特殊情况：空 Message + Stacktrace（Chrome 会话丢失，通常是代理问题）
    # 格式：Message: Stacktrace: #0 0x...
    if "message:" in error_lower and "stacktrace:" in error_lower:
        # 检查 Message: 后面是否直接跟着 Stacktrace（没有具体错误信息）
        import re
        pattern = r"message:\s*stacktrace:"
        if re.search(pattern, error_lower):
            logger.debug("检测到空 Message 错误，可能是代理问题")
            return True

    return False


# ==================== 代理池管理器 ====================

class ProxyPool:
    """
    智能代理池管理器

    支持三种策略：
    - random: 随机选择（默认）
    - round_robin: 轮询选择
    - failover: 故障转移（健康检查）
    """

    def __init__(self, proxy_list: List[str], strategy: str = "random", health_check: bool = False, timeout: int = 10):
        """
        初始化代理池

        Args:
            proxy_list: 代理列表，格式：["http://user:pass@ip:port", "socks5://ip:port", ...]
            strategy: 选择策略（random/round_robin/failover）
            health_check: 是否启用健康检查
            timeout: 代理连接超时（秒）
        """
        self.proxy_list = [p for p in proxy_list if p.strip()]  # 过滤空字符串
        self.strategy = strategy.lower()
        self.health_check = health_check
        self.timeout = timeout

        # 轮询索引
        self._round_robin_index = 0

        # 代理健康状态（failover 策略使用）
        self._proxy_health = {proxy: True for proxy in self.proxy_list}

        # 失败计数（用于故障检测）
        self._failure_count = {proxy: 0 for proxy in self.proxy_list}

        logger.info(f"🌐 代理池初始化: {len(self.proxy_list)} 个代理 | 策略={strategy} | 健康检查={health_check}")

    def get_proxy(self) -> Optional[str]:
        """
        获取一个代理

        Returns:
            代理地址，如果没有可用代理则返回 None
        """
        if not self.proxy_list:
            logger.warning("⚠️ 代理池为空，使用直连")
            return None

        if self.strategy == "random":
            return self._get_random_proxy()
        elif self.strategy == "round_robin":
            return self._get_round_robin_proxy()
        elif self.strategy == "failover":
            return self._get_failover_proxy()
        else:
            logger.warning(f"⚠️ 未知策略 '{self.strategy}'，使用随机策略")
            return self._get_random_proxy()

    def _get_random_proxy(self) -> str:
        """随机选择代理"""
        proxy = random.choice(self.proxy_list)
        logger.info(f"🎲 随机选择代理: {self._mask_proxy(proxy)}")
        return proxy

    def _get_round_robin_proxy(self) -> str:
        """轮询选择代理"""
        proxy = self.proxy_list[self._round_robin_index % len(self.proxy_list)]
        self._round_robin_index += 1
        logger.info(f"🔄 轮询选择代理 (#{self._round_robin_index}): {self._mask_proxy(proxy)}")
        return proxy

    def _get_failover_proxy(self) -> Optional[str]:
        """故障转移选择代理（优先选择健康的）"""
        # 1. 优先选择健康的代理
        healthy_proxies = [p for p in self.proxy_list if self._proxy_health.get(p, True)]

        if healthy_proxies:
            proxy = random.choice(healthy_proxies)
            logger.info(f"✅ 选择健康代理: {self._mask_proxy(proxy)} (健康: {len(healthy_proxies)}/{len(self.proxy_list)})")
            return proxy

        # 2. 如果所有代理都标记为不健康，重置健康状态并重试
        logger.warning("⚠️ 所有代理均标记为不健康，重置健康状态")
        self._proxy_health = {proxy: True for proxy in self.proxy_list}
        self._failure_count = {proxy: 0 for proxy in self.proxy_list}
        return self._get_failover_proxy()

    def mark_proxy_failed(self, proxy: str):
        """
        标记代理失败

        Args:
            proxy: 失败的代理地址
        """
        if not proxy or proxy not in self.proxy_list:
            return

        self._failure_count[proxy] = self._failure_count.get(proxy, 0) + 1

        # 连续失败 3 次，标记为不健康
        if self._failure_count[proxy] >= 3:
            self._proxy_health[proxy] = False
            logger.warning(f"❌ 代理标记为不健康: {self._mask_proxy(proxy)} (失败 {self._failure_count[proxy]} 次)")

    def mark_proxy_success(self, proxy: str):
        """
        标记代理成功

        Args:
            proxy: 成功的代理地址
        """
        if not proxy or proxy not in self.proxy_list:
            return

        # 重置失败计数
        self._failure_count[proxy] = 0
        self._proxy_health[proxy] = True

    @staticmethod
    def _mask_proxy(proxy: str) -> str:
        """
        屏蔽代理中的敏感信息（用户名/密码）

        Args:
            proxy: 完整代理地址

        Returns:
            屏蔽后的代理地址
        """
        import re
        # 格式: protocol://[user:pass@]host:port
        # 屏蔽: protocol://***:***@host:port
        pattern = r'(https?|socks5)://([^:]+):([^@]+)@(.+)'
        match = re.match(pattern, proxy)
        if match:
            protocol, user, password, host = match.groups()
            return f"{protocol}://***:***@{host}"
        return proxy

    def check_proxy_health(self, proxy: str, test_url: str = "https://www.google.com") -> bool:
        """
        检查代理健康状态

        Args:
            proxy: 代理地址
            test_url: 测试URL

        Returns:
            True表示健康，False表示不健康
        """
        try:
            proxies = {
                "http": proxy,
                "https": proxy
            }
            response = requests.get(test_url, proxies=proxies, timeout=self.timeout, verify=False)
            is_healthy = response.status_code == 200

            if is_healthy:
                logger.debug(f"✅ 代理健康检查通过: {self._mask_proxy(proxy)}")
            else:
                logger.warning(f"⚠️ 代理健康检查失败: {self._mask_proxy(proxy)} (状态码: {response.status_code})")

            return is_healthy
        except Exception as e:
            logger.warning(f"❌ 代理健康检查异常: {self._mask_proxy(proxy)} ({e})")
            return False

    def get_proxy_with_health_check(
        self,
        max_retries: int = 3,
        fail_strategy: str = "switch_then_direct",
        excluded: set = None
    ) -> Optional[str]:
        """
        带健康检查的代理获取（老王特制：启动前主动检测，SB代理直接跳过）

        艹，这个方法会在返回代理前先检测可用性，不可用就换！

        Args:
            max_retries: 最多尝试几个代理（切换次数）
            fail_strategy: 失败策略
                - "switch_then_direct": 尝试N个代理都失败后直连
                - "direct": 第一个失败就直接直连
            excluded: 本次排除的代理集合（会话级，不永久标记）

        Returns:
            可用代理地址，或 None 表示直连
        """
        if not self.proxy_list:
            logger.info("🌐 代理池为空，使用直连")
            return None

        if excluded is None:
            excluded = set()

        # "direct" 策略：第一个失败就直连，不切换
        if fail_strategy == "direct":
            max_retries = 1

        tried_proxies = set()
        available_proxies = [p for p in self.proxy_list if p not in excluded]

        if not available_proxies:
            logger.warning("⚠️ 所有代理都被排除，使用直连")
            return None

        for attempt in range(min(max_retries, len(available_proxies))):
            # 从未尝试过的代理中选择
            remaining = [p for p in available_proxies if p not in tried_proxies]
            if not remaining:
                break

            # 随机选择一个（或者按策略选择）
            proxy = random.choice(remaining)
            tried_proxies.add(proxy)

            logger.info(f"🔍 代理健康检查 ({attempt + 1}/{max_retries}): {self._mask_proxy(proxy)}")

            if self.check_proxy_health(proxy):
                logger.info(f"✅ 代理可用: {self._mask_proxy(proxy)}")
                return proxy
            else:
                logger.warning(f"❌ 代理不可用，切换下一个...")

        # 所有尝试都失败了
        logger.warning(f"⚠️ 尝试 {len(tried_proxies)} 个代理均失败，降级为直连")
        return None


class GeminiAuthConfig:
    """认证配置类（从统一配置模块加载）"""

    def __init__(self):
        # 从统一配置模块读取
        self.mail_api = config.basic.mail_api
        self.admin_key = config.basic.mail_admin_key
        self.email_domains = config.basic.email_domain  # 改为数组
        self.google_mail = config.basic.google_mail
        self.login_url = config.security.login_url

    def validate(self) -> bool:
        """验证配置是否完整"""
        required = [self.mail_api, self.admin_key, self.google_mail, self.login_url]
        return all(required)


class GeminiAuthHelper:
    """Gemini 认证辅助工具"""

    # XPath 配置（公共）
    XPATH = {
        "email_input": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[1]/div[1]/div/span[2]/input",
        "continue_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/button",
        "verify_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/div[1]/span/div[1]/button",
        "resend_code_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/div[2]/span/div[1]/button"
    }

    def __init__(self, config: GeminiAuthConfig):
        self.config = config

    def get_verification_code(self, email: str, timeout: int = 30) -> Optional[str]:
        """获取验证码（公共方法）"""
        logger.info(f"⏳ 等待验证码 [{email}]...")
        start = time.time()

        while time.time() - start < timeout:
            try:
                r = requests.get(
                    f"{self.config.mail_api}/admin/mails?limit=20&offset=0",
                    headers={"x-admin-auth": self.config.admin_key},
                    timeout=10,
                    verify=False
                )
                if r.status_code == 200:
                    emails = r.json().get('results', {})
                    for mail in emails:
                        if mail.get("address") == email and mail.get("source") == self.config.google_mail:
                            logger.info(f"📩 找到邮件 [{mail.get('id')}]，正在提取验证码...")
                            code = None
                            mail_id = mail.get("id")
                            
                            # 优先从 metadata 中获取验证码（AI 提取）
                            try:
                                metadata_str = mail.get("metadata")
                                if metadata_str:
                                    metadata = json.loads(metadata_str)
                                    if metadata and "ai_extract" in metadata and metadata["ai_extract"].get("result"):
                                        code = metadata["ai_extract"]["result"]
                                        logger.info(f"✅ 从 metadata 获取验证码: {code}")
                            except Exception as e:
                                logger.warning(f"⚠️ metadata 解析失败: {e}")
                            
                            # 如果 metadata 为空，从 raw 中提取验证码
                            if not code:
                                raw = mail.get("raw", "")
                                if raw:
                                    import re
                                    # Step 1: 去掉 quoted-printable 软换行（行尾的 = 表示续行）
                                    clean_raw = re.sub(r'=\r?\n', '', raw)
                                    
                                    # Step 2: 解码 quoted-printable 的 =XX（如 =3D 是 =）
                                    def decode_qp(match):
                                        hex_val = match.group(1)
                                        return chr(int(hex_val, 16))
                                    clean_raw = re.sub(r'=([0-9A-Fa-f]{2})', decode_qp, clean_raw)
                                    
                                    # Step 3: 去掉转义的引号
                                    clean_raw = clean_raw.replace('\\"', '"')
                                    
                                    # 优先匹配 HTML 中的 verification-code span 标签内容
                                    # 格式: <span class="verification-code" ...>SHCNXF</span>
                                    html_match = re.search(r'class\s*=\s*["\']?verification-code["\']?[^>]*>([A-Z0-9]{6})<', clean_raw, re.IGNORECASE)
                                    if html_match:
                                        code = html_match.group(1)
                                        logger.info(f"✅ 从 HTML span 提取验证码: {code}")
                                    else:
                                        # 备用：匹配验证码格式（6位大写字母+数字，前后有换行或特殊字符）
                                        text_match = re.search(r'(?:验证码[为是：:\s]*|verification code[:\s]*)[\r\n\s]*([A-Z0-9]{6})[\r\n\s]', clean_raw, re.IGNORECASE)
                                        if text_match:
                                            code = text_match.group(1)
                                            logger.info(f"✅ 从文本提取验证码: {code}")
                            
                            if code:
                                # 获取验证码后立即删除邮件，避免后续刷新时误取旧验证码
                                if mail_id:
                                    try:
                                        requests.delete(
                                            f"{self.config.mail_api}/admin/mails/{mail_id}",
                                            headers={"x-admin-auth": self.config.admin_key},
                                            timeout=10,
                                            verify=False
                                        )
                                        logger.info(f"🗑️ 已删除邮件 [{mail_id}]")
                                    except Exception as e:
                                        logger.warning(f"⚠️ 删除邮件失败 [{mail_id}]: {e}")
                                
                                return code
            except:
                pass
            time.sleep(2)

        logger.warning(f"验证码超时 [{email}]")
        return None

    def perform_email_verification(
        self,
        driver,
        wait,
        email: str,
        retry_enabled: bool = False,
        max_code_retries: int = 3,
        retry_interval: int = 5
    ) -> Dict[str, Any]:
        """
        执行邮箱验证流程
        从输入邮箱到验证码验证完成

        Args:
            driver: WebDriver 实例
            wait: WebDriverWait 实例
            email: 邮箱地址
            retry_enabled: 是否启用验证码重试（从配置读取）
            max_code_retries: 验证码获取失败后的重试次数（从配置读取）
            retry_interval: 重试间隔秒数（从配置读取）

        返回: {
            "success": bool,
            "error": str|None,
            "error_type": str|None  # "pin_input_not_found" 表示验证码输入框未出现
        }
        """
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC

            # ========== 1. 定位邮箱输入框（模拟视觉搜索） ==========
            inp = wait.until(EC.element_to_be_clickable((By.XPATH, self.XPATH["email_input"])))

            # 页面加载后的"观察"延迟
            human_delay(0.3, 0.8, "页面加载后观察表单")

            # ========== 2. 滚动到输入框可见 ==========
            human_like_scroll_into_view(driver, inp)

            # ========== 3. 聚焦输入框并清空 ==========
            human_like_focus(driver, inp)

            # ========== 4. 输入邮箱（模拟真人打字节奏） ==========
            logger.info(f"📝 开始输入邮箱: {email}")
            human_like_typing(inp, email)

            # ========== 5. 输入后的校验行为 ==========
            human_like_email_check(driver, inp, email)

            # ========== 6. 定位并滚动到"继续"按钮 ==========
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, self.XPATH["continue_btn"])))
            human_delay(0.2, 0.5, "定位继续按钮")
            human_like_scroll_into_view(driver, btn)

            # ========== 7. 点击"继续"按钮 ==========
            logger.info("🖱️ 点击继续按钮")
            human_like_button_click(driver, btn)

            # ========== 8. 等待页面响应（随机化延迟） ==========
            human_delay(1.5, 3.0, "等待页面响应")

            # ========== 9. 等待验证码输入框出现 ==========
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='pinInput']")))
                logger.info("✅ 验证码输入框已出现")
            except Exception:
                logger.warning("⚠️ 验证码输入框未出现")
                driver.save_screenshot("/app/screen.png")
                return {
                    "success": False,
                    "error": "验证码输入框未出现",
                    "error_type": "pin_input_not_found"
                }

            # ========== 10. 获取验证码 ==========
            code = self.get_verification_code(email)

            # ========== 11. 验证码重试逻辑（如果启用） ==========
            if not code and retry_enabled and max_code_retries > 0:
                for attempt in range(max_code_retries):
                    logger.info(f"🔄 验证码超时，点击重新发送 ({attempt + 1}/{max_code_retries})...")
                    try:
                        resend_btn = wait.until(EC.element_to_be_clickable((By.XPATH, self.XPATH["resend_code_btn"])))
                        # 重新发送按钮也用拟人化点击
                        human_like_button_click(driver, resend_btn)
                        logger.info("✅ 已点击重新发送验证码按钮")
                    except Exception as e:
                        logger.warning(f"⚠️ 重新发送验证码按钮点击失败: {e}")

                    # 使用拟人化延迟替代固定间隔
                    human_delay(retry_interval - 1, retry_interval + 1, "等待重新发送验证码")
                    code = self.get_verification_code(email)
                    if code:
                        logger.info("✅ 重试后成功获取验证码")
                        break

            if not code:
                return {
                    "success": False,
                    "error": "验证码超时",
                    "error_type": "code_timeout"
                }

            # ========== 12. 输入验证码 ==========
            logger.info(f"🔑 开始输入验证码: {code}")
            human_delay(0.5, 1.2, "阅读验证码")

            try:
                pin = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='pinInput']")))
                # 聚焦验证码输入框
                human_like_click(driver, pin)
                human_delay(0.1, 0.3, "聚焦验证码输入框")

                # 输入验证码
                human_like_typing(pin, code)
            except Exception:
                # 备用方案：点击 span 触发输入
                try:
                    span = driver.find_element(By.CSS_SELECTOR, "span[data-index='0']")
                    human_like_click(driver, span)
                    human_delay(0.1, 0.3, "使用备用方式聚焦")

                    # 使用拟人化打字
                    active_element = driver.switch_to.active_element
                    human_like_typing(active_element, code)
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"验证码输入失败: {e}",
                        "error_type": "code_input_failed"
                    }

            # ========== 13. 点击"验证"按钮 ==========
            human_delay(0.3, 0.7, "检查验证码输入")

            try:
                vbtn = driver.find_element(By.XPATH, self.XPATH["verify_btn"])
                logger.info("🖱️ 点击验证按钮")
                human_like_button_click(driver, vbtn)
            except Exception:
                # 备用方案：遍历按钮查找"验证"文本
                for btn_elem in driver.find_elements(By.TAG_NAME, "button"):
                    if '验证' in btn_elem.text:
                        logger.info("🖱️ 使用备用方式点击验证按钮")
                        human_like_button_click(driver, btn_elem)
                        break

            logger.info("✅ 邮箱验证流程完成")
            return {"success": True, "error": None, "error_type": None}

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ 邮箱验证流程异常: {error_msg}")
            # 检测是否为代理错误
            error_type = "proxy_error" if is_proxy_error(error_msg) else "unknown"
            if error_type == "proxy_error":
                logger.warning(f"🔄 邮箱验证检测到代理错误，可以尝试切换代理重试")
            return {"success": False, "error": error_msg, "error_type": error_type}

    def extract_config_from_workspace(self, driver) -> Dict[str, Any]:
        """
        从工作台页面提取配置信息（公共方法）

        返回: {"success": bool, "config": dict|None, "error": str|None}
        """
        try:
            time.sleep(3)  # 等待页面完全加载
            cookies = driver.get_cookies()
            url = driver.current_url
            parsed = urlparse(url)

            # 解析 config_id
            path_parts = url.split('/')
            config_id = None
            for i, p in enumerate(path_parts):
                if p == 'cid' and i + 1 < len(path_parts):
                    config_id = path_parts[i + 1].split('?')[0]
                    break

            cookie_dict = {c['name']: c for c in cookies}
            ses_cookie = cookie_dict.get('__Secure-C_SES', {})
            host_cookie = cookie_dict.get('__Host-C_OSES', {})
            csesidx = parse_qs(parsed.query).get('csesidx', [None])[0]

            if not all([ses_cookie.get('value'), host_cookie.get('value'), csesidx, config_id]):
                return {"success": False, "config": None, "error": "配置数据不完整"}

            config_data = {
                "csesidx": csesidx,
                "config_id": config_id,
                "secure_c_ses": ses_cookie.get('value'),
                "host_c_oses": host_cookie.get('value'),
                "expires_at": datetime.fromtimestamp(
                    ses_cookie.get('expiry', 0) - 43200
                ).strftime('%Y-%m-%d %H:%M:%S') if ses_cookie.get('expiry') else None
            }

            return {"success": True, "config": config_data, "error": None}

        except Exception as e:
            return {"success": False, "config": None, "error": str(e)}

    def wait_for_workspace(self, driver, timeout: int = 30, max_crash_retries: int = 3) -> bool:
        """
        等待进入工作台（公共方法，带崩溃重试）

        Args:
            driver: Selenium WebDriver 实例
            timeout: 等待超时时间（秒）
            max_crash_retries: 崩溃后最大重试次数
            
        返回: True 表示成功进入，False 表示超时或失败
        """
        crash_count = 0
        workspace_url = "https://business.gemini.google/"
        
        for _ in range(timeout):
            time.sleep(1)
            try:
                # 检查页面是否崩溃
                page_source = driver.page_source
                is_crashed = 'crashed' in page_source.lower() or 'aw, snap' in page_source.lower()
                
                if is_crashed:
                    crash_count += 1
                    logger.warning(f"⚠️ 等待工作台时页面崩溃，尝试开新标签页 (崩溃 {crash_count}/{max_crash_retries})")
                    if crash_count >= max_crash_retries:
                        logger.error("❌ 页面崩溃次数过多，放弃重试")
                        return False
                    
                    # 开新标签页并切换
                    if self._recover_from_crash(driver, workspace_url):
                        time.sleep(3)
                        continue
                    else:
                        return False
                
                url = driver.current_url
                if 'business.gemini.google' in url and '/cid/' in url:
                    return True
                    
            except Exception as e:
                error_msg = str(e).lower()
                if 'crash' in error_msg or 'tab' in error_msg or 'target window' in error_msg:
                    crash_count += 1
                    logger.warning(f"⚠️ 等待工作台时检测到崩溃: {e} (崩溃 {crash_count}/{max_crash_retries})")
                    if crash_count >= max_crash_retries:
                        logger.error("❌ 页面崩溃次数过多，放弃重试")
                        return False
                    
                    if self._recover_from_crash(driver, workspace_url):
                        time.sleep(3)
                        continue
                    else:
                        return False
                # 其他异常继续等待
                
        return False
    
    def _recover_from_crash(self, driver, target_url: str) -> bool:
        """
        从崩溃中恢复：开新标签页访问目标URL
        
        艹，崩溃的标签页刷新没用，得开新的！
        """
        try:
            # 获取当前所有窗口句柄
            original_handles = driver.window_handles
            
            # 开新标签页
            driver.execute_script("window.open('');")
            time.sleep(0.5)
            
            # 获取新窗口句柄
            new_handles = driver.window_handles
            new_handle = None
            for handle in new_handles:
                if handle not in original_handles:
                    new_handle = handle
                    break
            
            if not new_handle:
                logger.error("❌ 无法创建新标签页")
                return False
            
            # 切换到新标签页
            driver.switch_to.window(new_handle)
            
            # 关闭旧的崩溃标签页
            for handle in original_handles:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except:
                    pass
            
            # 切回新标签页
            driver.switch_to.window(new_handle)
            
            # 访问目标URL
            driver.get(target_url)
            time.sleep(3)
            
            logger.info("✅ 已通过新标签页恢复")
            return True
            
        except Exception as e:
            logger.error(f"❌ 恢复失败: {e}")
            return False


class GeminiAuthFlow:
    """
    统一的 Gemini 认证流程类
    艹，把注册和登录的重复代码都整合到这里了！

    支持两种模式：
    - register: 注册模式（创建临时邮箱 + 输入姓名）
    - login: 登录模式（使用已有邮箱）
    """

    # 姓名池（注册用）
    NAMES = [
        "James Smith", "John Johnson", "Robert Williams", "Michael Brown", "William Jones",
        "David Garcia", "Mary Miller", "Patricia Davis", "Jennifer Rodriguez", "Linda Martinez"
    ]

    def __init__(self, auth_config: GeminiAuthConfig, auth_helper: GeminiAuthHelper):
        self.config = auth_config
        self.helper = auth_helper

    def execute(
        self,
        mode: str,
        email: Optional[str] = None,
        email_creator=None,
        max_retries: int = 3,
        retry_interval: int = 5,
        proxy_retry_enabled: bool = False,
        proxy_retry_count: int = 3
    ) -> Dict[str, Any]:
        """
        执行统一认证流程

        Args:
            mode: "register" 或 "login"
            email: 登录模式必填，注册模式会自动创建
            email_creator: 注册模式必填，用于创建临时邮箱的回调函数
            max_retries: 最大重试次数（验证码重试）
            retry_interval: 重试间隔（秒）
            proxy_retry_enabled: 是否启用代理错误重试（从 proxy_health_check 配置读取）
            proxy_retry_count: 代理错误重试次数（从 proxy_check_retry_count 配置读取）

        返回: {
            "success": bool,
            "email": str|None,
            "config": dict|None,
            "error": str|None
        }
        """
        if mode not in ["register", "login"]:
            return {"success": False, "email": None, "config": None, "error": f"不支持的模式: {mode}"}

        if mode == "login" and not email:
            return {"success": False, "email": None, "config": None, "error": "登录模式必须提供 email"}

        if mode == "register" and not email_creator:
            return {"success": False, "email": None, "config": None, "error": "注册模式必须提供 email_creator"}

        # 会话级排除代理列表（避免重复使用失败的代理）
        excluded_proxies: set = set()
        last_result = None

        # 计算实际最大重试次数：取验证码重试和代理重试的较大值
        actual_max_retries = max(max_retries, proxy_retry_count if proxy_retry_enabled else 1)

        # 重试逻辑
        for attempt in range(actual_max_retries):
            # 注册模式：每次重试创建新邮箱
            if mode == "register":
                email = email_creator()
                if not email:
                    return {"success": False, "email": None, "config": None, "error": "无法创建邮箱"}

            logger.info(f"🚀 [{mode.upper()}] 尝试 {attempt + 1}/{actual_max_retries}: {email}")

            # 执行单次认证（传入排除列表）
            result = self._execute_once(mode, email, excluded_proxies=excluded_proxies)
            last_result = result

            # 成功则直接返回
            if result["success"]:
                return result

            # 检查错误类型
            error_type = result.get("error_type")

            # 判断是否可以重试
            can_retry = False

            # 验证码未出现 - 使用验证码重试配置
            if error_type == "pin_input_not_found" and attempt < max_retries - 1:
                logger.warning(f"[{mode.upper()}] 邮件没有正常发送，准备重试 ({attempt + 1}/{max_retries})")
                can_retry = True

            # 代理错误 - 使用代理重试配置
            elif error_type == "proxy_error" and proxy_retry_enabled and attempt < proxy_retry_count - 1:
                # 获取使用的代理（用于排除）
                used_proxy = result.get("used_proxy")
                if used_proxy:
                    excluded_proxies.add(used_proxy)
                    logger.info(
                        f"🚫 [{mode.upper()}] 排除失败代理: {ProxyPool._mask_proxy(used_proxy)} (已排除 {len(excluded_proxies)} 个)")
                logger.warning(f"[{mode.upper()}] 代理错误，准备切换代理重试 ({attempt + 1}/{proxy_retry_count})")
                can_retry = True

            if can_retry:
                logger.info(f"⏳ [{mode.upper()}] 等待 {retry_interval} 秒后重试...")
                time.sleep(retry_interval)
                continue
            elif error_type not in ["pin_input_not_found", "proxy_error"]:
                # 其他错误不重试，直接返回
                logger.error(f"❌ [{mode.upper()}] 认证失败: {result.get('error')}")
                return result

        # 重试耗尽
        return {
            "success": False,
            "email": email,
            "config": None,
            "error": f"重试 {actual_max_retries} 次后仍然失败",
            "last_error_type": last_result.get("error_type") if last_result else None
        }

    def _execute_once(self, mode: str, email: str, excluded_proxies: set = None) -> Dict[str, Any]:
        """
        执行单次认证流程（不含重试）

        Args:
            mode: "register" 或 "login"
            email: 邮箱地址
            excluded_proxies: 需要排除的代理集合（会话级）

        返回: {
            "success": bool,
            "email": str,
            "config": dict|None,
            "error": str|None,
            "error_type": str|None,
            "used_proxy": str|None  # 使用的代理（用于排除）
        }
        """
        if excluded_proxies is None:
            excluded_proxies = set()

        driver = None
        chrome_profile_dir: Optional[str] = None
        selected_proxy = None  # 记录使用的代理
        proxy_pool = None  # 记录代理池实例

        try:
            # 延迟导入 selenium
            import undetected_chromedriver as uc
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.common.keys import Keys
            import os
            import random
        except ImportError as e:
            return {
                "success": False,
                "email": email,
                "config": None,
                "error": f"Selenium 未安装: {e}",
                "error_type": "import_error",
                "used_proxy": None
            }

        try:
            # ========== 初始化代理池 ==========
            from core.config import config as app_config

            # 优先使用代理池
            if app_config.basic.proxy_pool:
                proxy_pool = ProxyPool(
                    proxy_list=app_config.basic.proxy_pool,
                    strategy=app_config.basic.proxy_strategy,
                    health_check=app_config.basic.proxy_health_check,
                    timeout=app_config.basic.proxy_timeout
                )
                # 如果启用了健康检查，使用带检测的获取方法（传入排除列表）
                if app_config.basic.proxy_health_check:
                    selected_proxy = proxy_pool.get_proxy_with_health_check(
                        max_retries=app_config.basic.proxy_check_retry_count,
                        fail_strategy=app_config.basic.proxy_check_fail_strategy,
                        excluded=excluded_proxies  # 传入会话级排除列表
                    )
                else:
                    # 非健康检查模式也要排除失败的代理
                    available_proxies = [p for p in app_config.basic.proxy_pool if p not in excluded_proxies]
                    if available_proxies:
                        selected_proxy = random.choice(available_proxies)
                        logger.info(f"🎲 随机选择代理（排除 {len(excluded_proxies)} 个）: {ProxyPool._mask_proxy(selected_proxy)}")
                    else:
                        logger.warning(f"⚠️ 所有代理都被排除，使用直连")
                        selected_proxy = None
            # 如果代理池为空，回退到单个代理
            elif app_config.basic.proxy:
                # 单个代理如果在排除列表中，直接跳过
                if app_config.basic.proxy in excluded_proxies:
                    logger.warning(f"⚠️ 单个代理已被排除，使用直连")
                    selected_proxy = None
                else:
                    selected_proxy = app_config.basic.proxy
                    # 单个代理也支持健康检查
                    if app_config.basic.proxy_health_check:
                        temp_pool = ProxyPool(
                            proxy_list=[selected_proxy],
                            timeout=app_config.basic.proxy_timeout
                        )
                        if not temp_pool.check_proxy_health(selected_proxy):
                            logger.warning(f"⚠️ 单个代理不可用，降级为直连")
                            selected_proxy = None
                        else:
                            logger.info(f"✅ 单个代理可用: {ProxyPool._mask_proxy(selected_proxy)}")
                    else:
                        logger.info(f"🌐 使用单个代理: {ProxyPool._mask_proxy(selected_proxy)}")

            chrome_bin, major, out = get_chrome_path_and_major()

            # 1. 配置并启动 Chrome
            options = uc.ChromeOptions()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-software-rasterizer')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-background-networking')
            options.add_argument('--disable-default-apps')
            options.add_argument('--disable-sync')
            options.add_argument("--disable-features=VizDisplayCompositor")
            options.add_argument("--disable-gpu-compositing")

            # ========== 反检测配置 ==========
            # 禁用自动化控制标志
            options.add_argument('--disable-blink-features=AutomationControlled')
            # 禁用通知
            options.add_argument('--disable-notifications')

            # ========== 应用代理 ==========
            if selected_proxy:
                options.add_argument(f'--proxy-server={selected_proxy}')
                logger.info(f"🌐 Chrome 启动使用代理: {ProxyPool._mask_proxy(selected_proxy)}")

            # 为每次会话分配独立 profile，便于兜底清理残留进程和缓存
            chrome_profile_dir = tempfile.mkdtemp(prefix="gemini-chrome-profile-")
            options.add_argument(f"--user-data-dir={chrome_profile_dir}")
            options.add_argument("--remote-debugging-port=0")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")

            # use_subprocess=False 可减少 uc 子进程残留导致的内存持续增长
            driver = uc.Chrome(options=options, use_subprocess=False, version_main=major)
            wait = WebDriverWait(driver, 30)

            # 2. 访问登录页（加上随机延迟）
            driver.get(self.config.login_url)
            human_delay(1.5, 2.5, "页面加载")

            # 3. 执行邮箱验证流程
            retry_config = app_config.retry
            verify_result = self.helper.perform_email_verification(
                driver,
                wait,
                email,
                retry_enabled=retry_config.verification_retry_enabled,
                max_code_retries=retry_config.max_verification_retries,
                retry_interval=retry_config.verification_retry_interval_seconds
            )
            if not verify_result["success"]:
                # 代理池：标记失败
                if proxy_pool and selected_proxy:
                    proxy_pool.mark_proxy_failed(selected_proxy)

                return {
                    "success": False,
                    "email": email,
                    "config": None,
                    "error": verify_result["error"],
                    "error_type": verify_result.get("error_type"),
                    "used_proxy": selected_proxy
                }

            # 4. 注册模式：输入姓名
            if mode == "register":
                time.sleep(2)
                selectors = [
                    "input[formcontrolname='fullName']",
                    "input[placeholder='全名']",
                    "input[placeholder='Full name']",
                    "input#mat-input-0",
                ]
                name_inp = None
                for _ in range(30):
                    for sel in selectors:
                        try:
                            name_inp = driver.find_element(By.CSS_SELECTOR, sel)
                            if name_inp.is_displayed():
                                break
                        except:
                            continue
                    if name_inp and name_inp.is_displayed():
                        break
                    time.sleep(1)

                if name_inp and name_inp.is_displayed():
                    name = random.choice(self.NAMES)
                    name_inp.click()
                    human_like_typing(name_inp, name)
                    time.sleep(0.3)
                    name_inp.send_keys(Keys.ENTER)
                    time.sleep(1)
                else:
                    # 代理池：标记失败
                    if proxy_pool and selected_proxy:
                        proxy_pool.mark_proxy_failed(selected_proxy)

                    return {
                        "success": False,
                        "email": email,
                        "config": None,
                        "error": "未找到姓名输入框",
                        "error_type": "name_input_not_found",
                        "used_proxy": selected_proxy
                    }

            # 5. 等待进入工作台
            if not self.helper.wait_for_workspace(driver, timeout=60):
                # 代理池：标记失败
                if proxy_pool and selected_proxy:
                    proxy_pool.mark_proxy_failed(selected_proxy)

                return {
                    "success": False,
                    "email": email,
                    "config": None,
                    "error": "未跳转到工作台",
                    "error_type": "workspace_timeout",
                    "used_proxy": selected_proxy
                }

            # 6. 提取配置（带重试机制处理 tab crashed）
            extract_result = self.extract_config_with_retry(driver, max_retries=3)
            if not extract_result["success"]:
                # 代理池：标记失败
                if proxy_pool and selected_proxy:
                    proxy_pool.mark_proxy_failed(selected_proxy)

                return {
                    "success": False,
                    "email": email,
                    "config": None,
                    "error": extract_result["error"],
                    "error_type": "extract_config_failed",
                    "used_proxy": selected_proxy
                }

            config_data = extract_result["config"]

            # 代理池：标记成功
            if proxy_pool and selected_proxy:
                proxy_pool.mark_proxy_success(selected_proxy)

            logger.info(f"✅ [{mode.upper()}] 认证成功: {email}")
            return {
                "success": True,
                "email": email,
                "config": config_data,
                "error": None,
                "error_type": None,
                "used_proxy": selected_proxy
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ [{mode.upper()}] 认证异常 [{email}]: {error_msg}")

            # 代理池：标记失败
            if proxy_pool and selected_proxy:
                proxy_pool.mark_proxy_failed(selected_proxy)

            # 检测是否为代理错误
            error_type = "proxy_error" if is_proxy_error(error_msg) else "unknown"
            if error_type == "proxy_error":
                logger.warning(f"🔄 [{mode.upper()}] 检测到代理错误，可以尝试切换代理重试")

            return {
                "success": False,
                "email": email,
                "config": None,
                "error": error_msg,
                "error_type": error_type,
                "used_proxy": selected_proxy
            }
        finally:
            _safe_quit_driver(driver)
            _kill_chrome_processes_by_profile(chrome_profile_dir)
            _cleanup_profile_dir(chrome_profile_dir)


    def extract_config_with_retry(self, driver, max_retries: int = 3) -> Dict[str, Any]:
        """
        带重试机制的配置提取（处理 tab crashed 问题）
        
        艹，Google 工作台页面经常崩溃，这个方法会自动重试
        
        Args:
            driver: Selenium WebDriver 实例
            max_retries: 最大重试次数，默认3次
            
        返回: {"success": bool, "config": dict|None, "error": str|None}
        """
        extract_result = None
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # 检查页面是否崩溃
                page_source = driver.page_source
                if 'crashed' in page_source.lower() or 'aw, snap' in page_source.lower():
                    logger.warning(f"⚠️ 页面崩溃，尝试刷新 (尝试 {attempt + 1}/{max_retries})")
                    driver.refresh()
                    time.sleep(3)
                    continue
                
                extract_result = self.helper.extract_config_from_workspace(driver)
                if extract_result["success"]:
                    return extract_result
                else:
                    last_error = extract_result["error"]
                    logger.warning(f"⚠️ 提取配置失败: {last_error}，尝试刷新 (尝试 {attempt + 1}/{max_retries})")
                    driver.refresh()
                    time.sleep(3)
                    
            except Exception as e:
                error_msg = str(e).lower()
                if 'crash' in error_msg or 'tab' in error_msg:
                    logger.warning(f"⚠️ 检测到页面崩溃: {e}，尝试刷新 (尝试 {attempt + 1}/{max_retries})")
                    try:
                        driver.refresh()
                        time.sleep(3)
                    except:
                        # 如果刷新也失败，尝试重新访问工作台
                        try:
                            driver.get("https://business.gemini.google/")
                            time.sleep(5)
                        except:
                            pass
                else:
                    last_error = str(e)
                    logger.warning(f"⚠️ 提取配置异常: {e}，尝试刷新 (尝试 {attempt + 1}/{max_retries})")
                    try:
                        driver.refresh()
                        time.sleep(3)
                    except:
                        pass
        
        return {"success": False, "config": None, "error": last_error or "提取配置失败（已重试）"}

