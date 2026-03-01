"""
统一配置管理系统

优先级规则：
1. 环境变量（最高优先级）
2. YAML 配置文件
3. 默认值（最低优先级）

配置分类：
- 安全配置：仅从环境变量读取，不可热更新（ADMIN_KEY, PATH_PREFIX, SESSION_SECRET_KEY）
- 业务配置：环境变量 > YAML，支持热更新（API_KEY, PROXY, 重试策略等）
"""

import os
import yaml
import secrets
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


# ==================== 配置模型定义 ====================

class BasicConfig(BaseModel):
    """基础配置"""
    api_key: str = Field(default="", description="API访问密钥（留空则公开访问）")
    base_url: str = Field(default="", description="服务器URL（留空则自动检测）")
    proxy: str = Field(default="", description="代理地址（单个代理，优先级低于代理池）")
    google_mail: str = Field(default="noreply-googlecloud@google.com", description="谷歌发件邮箱地址")
    mail_api: str = Field(default="", description="临时邮箱API地址")
    mail_admin_key: str = Field(default="", description="临时邮箱管理员密钥")
    email_domain: list = Field(default=[], description="临时邮箱域名")
    register_number: int = Field(default=5, ge=1, le=100, description="注册临时邮箱数量")

    # ========== 代理池配置（老王特制，规避 IP 审查） ==========
    proxy_pool: List[str] = Field(default=[], description="代理池列表（支持http/https/socks5）")
    proxy_strategy: str = Field(default="random", description="代理选择策略：random(随机), round_robin(轮询), failover(故障转移)")
    proxy_health_check: bool = Field(default=False, description="是否启用代理健康检查")
    proxy_timeout: int = Field(default=10, ge=3, le=60, description="代理连接超时（秒）")
    # 代理检查失败策略配置
    proxy_check_fail_strategy: str = Field(default="switch_then_direct", description="代理检查失败策略：switch_then_direct(切换后直连), direct(直接直连)")
    proxy_check_retry_count: int = Field(default=3, ge=1, le=10, description="代理检查失败时切换代理的次数")



class ImageGenerationConfig(BaseModel):
    """图片生成配置"""
    enabled: bool = Field(default=True, description="是否启用图片生成")
    supported_models: List[str] = Field(
        default=["gemini-3-pro-preview"],
        description="支持图片生成的模型列表"
    )


class RetryConfig(BaseModel):
    """重试策略配置"""
    max_new_session_tries: int = Field(default=5, ge=1, le=20, description="新会话尝试账户数")
    max_request_retries: int = Field(default=3, ge=1, le=10, description="请求失败重试次数")
    max_account_switch_tries: int = Field(default=5, ge=1, le=20, description="账户切换尝试次数")
    account_failure_threshold: int = Field(default=3, ge=1, le=10, description="账户失败阈值")
    rate_limit_cooldown_seconds: int = Field(default=600, ge=60, le=3600, description="429冷却时间（秒）")
    session_cache_ttl_seconds: int = Field(default=3600, ge=300, le=86400, description="会话缓存时间（秒）")
    
    # 验证码重试配置
    verification_retry_enabled: bool = Field(default=False, description="是否启用验证码重试")
    max_verification_retries: int = Field(default=3, ge=1, le=10, description="验证码重试次数")
    verification_retry_interval_seconds: int = Field(default=5, ge=3, le=60, description="验证码重试时间间隔（秒）")


class PublicDisplayConfig(BaseModel):
    """公开展示配置"""
    logo_url: str = Field(default="", description="Logo URL")
    chat_url: str = Field(default="", description="开始对话链接")


class SessionConfig(BaseModel):
    """Session配置"""
    expire_hours: int = Field(default=24, ge=1, le=168, description="Session过期时间（小时）")


class AutoRegisterConfig(BaseModel):
    """自动注册配置"""
    enabled: bool = Field(default=False, description="是否启用自动注册")
    cron: str = Field(default="", description="Cron 表达式（5段）")
    task_history_limit: int = Field(default=10, ge=1, le=200, description="任务历史保留数量")
    cleanup_expired_accounts_enabled: bool = Field(default=False, description="是否启用自动清理过期超过2天的账户")


class SecurityConfig(BaseModel):
    """安全配置（仅从环境变量读取，不可热更新）"""
    admin_key: str = Field(default="", description="管理员密钥（必需）")
    path_prefix: str = Field(default="", description="路径前缀（隐藏管理端点）")
    session_secret_key: str = Field(..., description="Session密钥")
    login_url: str = Field(default="https://auth.business.gemini.google/login?continueUrl=https:%2F%2Fbusiness.gemini.google%2F&wiffid=CAoSJDIwNTlhYzBjLTVlMmMtNGUxZS1hY2JkLThmOGY2ZDE0ODM1Mg", description="google business 登录链接")

class AppConfig(BaseModel):
    """应用配置（统一管理）"""
    # 安全配置（仅从环境变量）
    security: SecurityConfig

    # 业务配置（环境变量 > YAML > 默认值）
    basic: BasicConfig
    image_generation: ImageGenerationConfig
    retry: RetryConfig
    public_display: PublicDisplayConfig
    session: SessionConfig
    auto_register: AutoRegisterConfig


# ==================== 配置管理器 ====================

class ConfigManager:
    """配置管理器（单例）"""

    def __init__(self, yaml_path: str = None):
        # 自动检测环境并设置默认路径
        if yaml_path is None:
            if os.path.exists("/data"):
                yaml_path = "/data/settings.yaml"  # HF Pro 持久化
            else:
                yaml_path = "data/settings.yaml"  # 本地存储
        self.yaml_path = Path(yaml_path)
        self._config: Optional[AppConfig] = None
        self.load()

    def load(self):
        """
        加载配置

        优先级规则：
        1. 安全配置（ADMIN_KEY, PATH_PREFIX, SESSION_SECRET_KEY）：仅从环境变量读取
        2. 其他配置：YAML > 环境变量 > 默认值
        """
        # 1. 加载 YAML 配置
        yaml_data = self._load_yaml()

        # 2. 加载安全配置（仅从环境变量，不允许 Web 修改）
        security_config = SecurityConfig(
            admin_key=os.getenv("ADMIN_KEY", ""),
            path_prefix=os.getenv("PATH_PREFIX", ""),
            session_secret_key=os.getenv("SESSION_SECRET_KEY", self._generate_secret()),
            login_url=os.getenv("LOGIN_URL", ""),
        )

        # 3. 加载基础配置（YAML > 环境变量 > 默认值）
        basic_data = yaml_data.get("basic", {})

        # 处理 email_domain（支持多种格式）
        email_domain_value = basic_data.get("email_domain")
        if not email_domain_value:  # YAML 中不存在或为空
            env_domains = os.getenv("EMAIL_DOMAIN", "")
            if env_domains:
                # 尝试解析 JSON 数组格式（如 ["domain1.com","domain2.org"]）
                if env_domains.strip().startswith('['):
                    try:
                        import json
                        email_domain_value = json.loads(env_domains)
                    except:
                        email_domain_value = []
                else:
                    # 逗号分隔字符串格式（如 "domain1.com,domain2.org,domain3.net"）
                    email_domain_value = [d.strip() for d in env_domains.split(",") if d.strip()]
            else:
                email_domain_value = []

        # 处理 proxy_pool（支持多种格式）
        proxy_pool_value = basic_data.get("proxy_pool")
        if not proxy_pool_value:  # YAML 中不存在或为空
            env_proxies = os.getenv("PROXY_POOL", "")
            if env_proxies:
                # 尝试解析 JSON 数组格式
                if env_proxies.strip().startswith('['):
                    try:
                        import json
                        proxy_pool_value = json.loads(env_proxies)
                    except:
                        proxy_pool_value = []
                else:
                    # 逗号/分号/换行符分隔格式
                    import re
                    proxy_pool_value = [
                        p.strip() for p in re.split(r'[,;\n]', env_proxies)
                        if p.strip()
                    ]
            else:
                proxy_pool_value = []

        basic_config = BasicConfig(
            api_key=basic_data.get("api_key") or os.getenv("API_KEY", ""),
            base_url=basic_data.get("base_url") or os.getenv("BASE_URL", ""),
            proxy=basic_data.get("proxy") or os.getenv("PROXY", ""),
            google_mail=basic_data.get("google_mail") or os.getenv("GOOGLE_MAIL", ""),
            mail_api=basic_data.get("mail_api") or os.getenv("MAIL_API", ""),
            mail_admin_key=basic_data.get("mail_admin_key") or os.getenv("MAIL_ADMIN_KEY", ""),
            email_domain=email_domain_value,
            register_number=basic_data.get("register_number") or int(os.getenv("REGISTER_NUMBER", 5)),
            # 代理池配置
            proxy_pool=proxy_pool_value,
            proxy_strategy=basic_data.get("proxy_strategy") or os.getenv("PROXY_STRATEGY", "random"),
            proxy_health_check=basic_data.get("proxy_health_check", False) if "proxy_health_check" in basic_data else os.getenv("PROXY_HEALTH_CHECK", "").lower() in ["1", "true", "yes"],
            proxy_timeout=basic_data.get("proxy_timeout") or int(os.getenv("PROXY_TIMEOUT", 10)),
            # 代理检查失败策略
            proxy_check_fail_strategy=basic_data.get("proxy_check_fail_strategy") or os.getenv("PROXY_CHECK_FAIL_STRATEGY", "switch_then_direct"),
            proxy_check_retry_count=basic_data.get("proxy_check_retry_count") or int(os.getenv("PROXY_CHECK_RETRY_COUNT", 3))
        )

        # 4. 加载其他配置（从 YAML）
        image_generation_config = ImageGenerationConfig(
            **yaml_data.get("image_generation", {})
        )

        retry_config = RetryConfig(
            **yaml_data.get("retry", {})
        )

        public_display_config = PublicDisplayConfig(
            **yaml_data.get("public_display", {})
        )

        session_config = SessionConfig(
            **yaml_data.get("session", {})
        )

        auto_register_data = yaml_data.get("auto_register", {})
        enabled_value = auto_register_data.get("enabled")
        if enabled_value is None:
            enabled_value = os.getenv("AUTO_REGISTER_ENABLED", "").lower() in ["1", "true", "yes", "y", "on"]

        task_history_limit_value = auto_register_data.get("task_history_limit")
        if task_history_limit_value is None:
            task_history_limit_value = int(os.getenv("AUTO_REGISTER_TASK_HISTORY_LIMIT", 10))

        cleanup_expired_accounts_enabled_value = auto_register_data.get("cleanup_expired_accounts_enabled")
        if cleanup_expired_accounts_enabled_value is None:
            cleanup_expired_accounts_enabled_value = os.getenv(
                "AUTO_REGISTER_CLEANUP_EXPIRED_ACCOUNTS_ENABLED", ""
            ).lower() in ["1", "true", "yes", "y", "on"]

        auto_register_config = AutoRegisterConfig(
            enabled=enabled_value,
            cron=auto_register_data.get("cron") or os.getenv("AUTO_REGISTER_CRON", ""),
            task_history_limit=task_history_limit_value,
            cleanup_expired_accounts_enabled=cleanup_expired_accounts_enabled_value
        )

        # 5. 构建完整配置
        self._config = AppConfig(
            security=security_config,
            basic=basic_config,
            image_generation=image_generation_config,
            retry=retry_config,
            public_display=public_display_config,
            session=session_config,
            auto_register=auto_register_config
        )

    def _load_yaml(self) -> dict:
        """加载 YAML 文件"""
        if self.yaml_path.exists():
            try:
                with open(self.yaml_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[WARN] 加载配置文件失败: {e}，使用默认配置")
        return {}

    def _generate_secret(self) -> str:
        """生成随机密钥"""
        return secrets.token_urlsafe(32)

    def save_yaml(self, data: dict):
        """保存 YAML 配置"""
        self.yaml_path.parent.mkdir(exist_ok=True)
        with open(self.yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def reload(self):
        """重新加载配置（热更新）"""
        self.load()

    @property
    def config(self) -> AppConfig:
        """获取配置"""
        return self._config

    # ==================== 便捷访问属性 ====================

    @property
    def api_key(self) -> str:
        """API访问密钥"""
        return self._config.basic.api_key

    @property
    def admin_key(self) -> str:
        """管理员密钥"""
        return self._config.security.admin_key

    @property
    def path_prefix(self) -> str:
        """路径前缀"""
        return self._config.security.path_prefix

    @property
    def session_secret_key(self) -> str:
        """Session密钥"""
        return self._config.security.session_secret_key

    @property
    def proxy(self) -> str:
        """代理地址"""
        return self._config.basic.proxy

    @property
    def base_url(self) -> str:
        """服务器URL"""
        return self._config.basic.base_url

    @property
    def logo_url(self) -> str:
        """Logo URL"""
        return self._config.public_display.logo_url

    @property
    def chat_url(self) -> str:
        """开始对话链接"""
        return self._config.public_display.chat_url

    @property
    def image_generation_enabled(self) -> bool:
        """是否启用图片生成"""
        return self._config.image_generation.enabled

    @property
    def image_generation_models(self) -> List[str]:
        """支持图片生成的模型列表"""
        return self._config.image_generation.supported_models

    @property
    def session_expire_hours(self) -> int:
        """Session过期时间（小时）"""
        return self._config.session.expire_hours

    @property
    def max_new_session_tries(self) -> int:
        """新会话尝试账户数"""
        return self._config.retry.max_new_session_tries

    @property
    def max_request_retries(self) -> int:
        """请求失败重试次数"""
        return self._config.retry.max_request_retries

    @property
    def max_account_switch_tries(self) -> int:
        """账户切换尝试次数"""
        return self._config.retry.max_account_switch_tries

    @property
    def account_failure_threshold(self) -> int:
        """账户失败阈值"""
        return self._config.retry.account_failure_threshold

    @property
    def rate_limit_cooldown_seconds(self) -> int:
        """429冷却时间（秒）"""
        return self._config.retry.rate_limit_cooldown_seconds

    @property
    def session_cache_ttl_seconds(self) -> int:
        """会话缓存时间（秒）"""
        return self._config.retry.session_cache_ttl_seconds

    @property
    def verification_retry_enabled(self) -> bool:
        """是否启用验证码重试"""
        return self._config.retry.verification_retry_enabled

    @property
    def max_verification_retries(self) -> int:
        """验证码重试次数"""
        return self._config.retry.max_verification_retries

    @property
    def verification_retry_interval_seconds(self) -> int:
        """验证码重试时间间隔（秒）"""
        return self._config.retry.verification_retry_interval_seconds


# ==================== 全局配置管理器 ====================

config_manager = ConfigManager()

# 注意：不要直接引用 config_manager.config，因为 reload() 后引用会失效
# 应该始终通过 config_manager.config 访问配置
def get_config() -> AppConfig:
    """获取当前配置（支持热更新）"""
    return config_manager.config

# 为了向后兼容，保留 config 变量，但使用属性访问
class _ConfigProxy:
    """配置代理，确保始终访问最新配置"""
    @property
    def basic(self):
        return config_manager.config.basic

    @property
    def security(self):
        return config_manager.config.security

    @property
    def image_generation(self):
        return config_manager.config.image_generation

    @property
    def retry(self):
        return config_manager.config.retry

    @property
    def public_display(self):
        return config_manager.config.public_display

    @property
    def session(self):
        return config_manager.config.session

    @property
    def auto_register(self):
        return config_manager.config.auto_register

config = _ConfigProxy()
