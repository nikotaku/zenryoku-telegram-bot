"""
りおん自動運用の設定管理（JSON永続化）

- enabled: 自動ツイート/リプ/RT のON/OFFフラグ
- X API認証情報のオーバーライド（環境変数より優先）

設定ファイル rion_config.json はgit管理外（.gitignore）。
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "rion_config.json"

# X API認証のキー名（環境変数名と対応）
X_CRED_KEYS = [
    "RION_X_API_KEY",
    "RION_X_API_SECRET",
    "RION_X_ACCESS_TOKEN",
    "RION_X_ACCESS_SECRET",
]


def _load() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"rion_config 読み込みエラー: {e}")
    return {}


def _save(cfg: dict):
    try:
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"rion_config 保存エラー: {e}")


def is_enabled() -> bool:
    """自動運用が有効か。デフォルトはOFF（アカウント譲渡のため停止中）。"""
    return bool(_load().get("enabled", False))


def set_enabled(value: bool):
    cfg = _load()
    cfg["enabled"] = bool(value)
    _save(cfg)
    logger.info(f"りおん自動運用 enabled={value}")


def get_credential(key: str) -> str:
    """X API認証情報を取得する。設定ファイル優先、なければ環境変数。"""
    cfg = _load()
    creds = cfg.get("x_credentials", {})
    if creds.get(key):
        return creds[key]
    return os.environ.get(key, "")


def set_credentials(api_key: str, api_secret: str, access_token: str, access_secret: str):
    cfg = _load()
    cfg["x_credentials"] = {
        "RION_X_API_KEY": api_key.strip(),
        "RION_X_API_SECRET": api_secret.strip(),
        "RION_X_ACCESS_TOKEN": access_token.strip(),
        "RION_X_ACCESS_SECRET": access_secret.strip(),
    }
    _save(cfg)
    logger.info("りおん X API認証情報を更新しました")


def has_credentials() -> bool:
    return all(get_credential(k) for k in X_CRED_KEYS)
