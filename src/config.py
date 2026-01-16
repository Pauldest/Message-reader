"""配置管理模块"""

import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class AIConfig(BaseModel):
    """AI 服务配置"""
    provider: str = "deepseek"
    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    max_tokens: int = 4096
    temperature: float = 0.3


class EmailConfig(BaseModel):
    """邮件配置"""
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    use_ssl: bool = True
    username: str = ""
    password: str = ""
    from_addr: str = ""
    from_name: str = "AI 阅读助手"
    to_addrs: list[str] = Field(default_factory=list)


class ScheduleConfig(BaseModel):
    """调度配置"""
    fetch_interval: str = "2h"
    digest_times: list[str] = Field(default_factory=lambda: ["09:00", "21:00"])  # 早报和晚报
    timezone: str = "Asia/Shanghai"


class FilterConfig(BaseModel):
    """筛选配置"""
    top_pick_count: int = 5
    min_score: float = 5.0
    max_articles_per_digest: int = 100


class LoggingConfig(BaseModel):
    """日志配置"""
    level: str = "INFO"
    file: str = "logs/app.log"
    max_size: str = "10MB"
    backup_count: int = 5


class StorageConfig(BaseModel):
    """存储配置"""
    database_path: str = "data/articles.db"
    article_retention_days: int = 30


class FeedSource(BaseModel):
    """RSS 订阅源"""
    name: str
    url: str
    category: str = "未分类"
    enabled: bool = True


class AppConfig(BaseModel):
    """应用配置"""
    ai: AIConfig = Field(default_factory=AIConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    feeds: list[FeedSource] = Field(default_factory=list)


def _expand_env_vars(value):
    """递归展开环境变量"""
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        return value
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


def load_config(config_dir: Optional[Path] = None) -> AppConfig:
    """加载配置文件"""
    if config_dir is None:
        config_dir = Path(__file__).parent.parent / "config"
    
    config_dir = Path(config_dir)
    
    # 加载主配置
    config_path = config_dir / "config.yaml"
    if not config_path.exists():
        config_path = config_dir / "config.example.yaml"
    
    config_data = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    
    # 展开环境变量
    config_data = _expand_env_vars(config_data)
    
    # 加载订阅源
    feeds_path = config_dir / "feeds.yaml"
    if not feeds_path.exists():
        feeds_path = config_dir / "feeds.example.yaml"
    
    feeds_data = []
    if feeds_path.exists():
        with open(feeds_path, "r", encoding="utf-8") as f:
            feeds_content = yaml.safe_load(f) or {}
            feeds_data = feeds_content.get("feeds", [])
    
    config_data["feeds"] = feeds_data
    
    return AppConfig(**config_data)


# 全局配置实例
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config(config_dir: Optional[Path] = None) -> AppConfig:
    """重新加载配置"""
    global _config
    _config = load_config(config_dir)
    return _config
