from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # 转写走 OpenRouter 的 whisper-1；出题和判定走任意 OpenAI 兼容接口（不填就也走 OpenRouter）
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_base_url: str = ""
    llm_api_key: str = ""
    asr_model: str = "openai/whisper-1"
    llm_model: str = "anthropic/claude-sonnet-5.5"
    asr_timeout: float = 45
    llm_timeout: float = 60

    data_dir: Path = ROOT / "data"     # 数据库、录音、素材库 library.json；Docker 里挂成卷，不进仓库
    app_password: str = ""             # 部署到服务器必须设；本地不设 = 不用登录
    session_secret: str = ""
    fake_upstream: bool = False        # true = 不调任何付费接口，用内置的假转写 / 假判定（验收和测试用）

    new_per_day: int = 3               # 每天只加少量新表达（2–5 个），练得过来
    new_hard_max: int = 5
    session_cap: int = 15              # 一天最多排多少道到期复习
    intro_rounds: int = 3              # 新表达当天做几道替换题
    drill_rounds: int = 2              # 没用上时当场补几道


settings = Settings()
