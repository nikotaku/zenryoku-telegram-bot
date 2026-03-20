#!/usr/bin/env python3
"""
bitbank API クライアント
bitbank（仮想通貨取引所）のプライベートAPIを使って
保有資産（ポートフォリオ）情報を取得する。

認証方式: ACCESS-TIME-WINDOW + HMAC-SHA256
API ドキュメント: https://github.com/bitbankinc/bitbank-api-docs/blob/master/rest-api.md
"""

import os
import time
import hmac
import hashlib
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# ─── 設定 ──────────────────────────────────────────────────────────────────
BITBANK_API_KEY = os.environ.get("BITBANK_API_KEY", "")
BITBANK_API_SECRET = os.environ.get("BITBANK_API_SECRET", "")

PRIVATE_BASE_URL = "https://api.bitbank.cc/v1"
PUBLIC_BASE_URL = "https://public.bitbank.cc"

# 表示対象の通貨シンボル → 日本語名マッピング
ASSET_NAMES = {
    "jpy":   "日本円",
    "btc":   "ビットコイン",
    "eth":   "イーサリアム",
    "xrp":   "リップル",
    "ltc":   "ライトコイン",
    "mona":  "モナコイン",
    "bcc":   "ビットコインキャッシュ",
    "xlm":   "ステラルーメン",
    "qtum":  "クアンタム",
    "bat":   "ベーシックアテンショントークン",
    "omg":   "オーエムジー",
    "xym":   "シンボル",
    "link":  "チェーンリンク",
    "mkr":   "メーカー",
    "boba":  "ボバ",
    "enj":   "エンジンコイン",
    "matic": "ポリゴン",
    "dot":   "ポルカドット",
    "doge":  "ドージコイン",
    "astr":  "アスター",
    "ada":   "カルダノ",
    "avax":  "アバランチ",
    "axs":   "アクシーインフィニティ",
    "flr":   "フレア",
    "sand":  "ザサンドボックス",
    "gala":  "ガラ",
    "chz":   "チリーズ",
    "ape":   "エイプコイン",
    "sol":   "ソラナ",
    "fil":   "ファイルコイン",
    "mana":  "ディセントラランド",
    "algo":  "アルゴランド",
    "near":  "ニアープロトコル",
    "ens":   "イーサリアムネームサービス",
    "sui":   "スイ",
    "arb":   "アービトラム",
    "op":    "オプティミズム",
    "wbtc":  "ラップドビットコイン",
    "atom":  "コスモス",
    "apt":   "アプトス",
    "imx":   "イミュータブルX",
    "sei":   "セイ",
    "rndr":  "レンダートークン",
    "fet":   "フェッチ",
    "wld":   "ワールドコイン",
    "pepe":  "ペペ",
    "bonk":  "ボンク",
    "ordi":  "オルディナルス",
    "blur":  "ブラー",
    "pyth":  "パイス",
    "jup":   "ジュピター",
    "strk":  "スタークネット",
    "w":     "ワームホール",
    "tnsr":  "テンソル",
    "not":   "ノットコイン",
    "zk":    "ジーケーsync",
    "zro":   "レイヤーゼロ",
    "pol":   "ポリゴンエコシステムトークン",
    "eigen": "アイゲンレイヤー",
    "hype":  "ハイパーリキッド",
    "virtual": "バーチャルプロトコル",
    "ai16z": "AI16Z",
    "arc":   "アーク",
    "trump": "オフィシャルトランプ",
    "melania": "メラニア",
}

# JPYペアを持つ通貨（価格取得用）
JPY_PAIRS = {
    "btc":   "btc_jpy",
    "eth":   "eth_jpy",
    "xrp":   "xrp_jpy",
    "ltc":   "ltc_jpy",
    "mona":  "mona_jpy",
    "bcc":   "bcc_jpy",
    "xlm":   "xlm_jpy",
    "qtum":  "qtum_jpy",
    "bat":   "bat_jpy",
    "omg":   "omg_jpy",
    "xym":   "xym_jpy",
    "link":  "link_jpy",
    "mkr":   "mkr_jpy",
    "boba":  "boba_jpy",
    "enj":   "enj_jpy",
    "matic": "matic_jpy",
    "dot":   "dot_jpy",
    "doge":  "doge_jpy",
    "astr":  "astr_jpy",
    "ada":   "ada_jpy",
    "avax":  "avax_jpy",
    "axs":   "axs_jpy",
    "flr":   "flr_jpy",
    "sand":  "sand_jpy",
    "gala":  "gala_jpy",
    "chz":   "chz_jpy",
    "ape":   "ape_jpy",
    "sol":   "sol_jpy",
    "fil":   "fil_jpy",
    "mana":  "mana_jpy",
    "algo":  "algo_jpy",
    "near":  "near_jpy",
    "ens":   "ens_jpy",
    "sui":   "sui_jpy",
    "arb":   "arb_jpy",
    "op":    "op_jpy",
    "wbtc":  "wbtc_jpy",
    "atom":  "atom_jpy",
    "apt":   "apt_jpy",
    "imx":   "imx_jpy",
    "sei":   "sei_jpy",
    "rndr":  "rndr_jpy",
    "fet":   "fet_jpy",
    "wld":   "wld_jpy",
    "pepe":  "pepe_jpy",
    "bonk":  "bonk_jpy",
    "ordi":  "ordi_jpy",
    "blur":  "blur_jpy",
    "pyth":  "pyth_jpy",
    "jup":   "jup_jpy",
    "strk":  "strk_jpy",
    "w":     "w_jpy",
    "tnsr":  "tnsr_jpy",
    "not":   "not_jpy",
    "zk":    "zk_jpy",
    "zro":   "zro_jpy",
    "pol":   "pol_jpy",
    "eigen": "eigen_jpy",
    "hype":  "hype_jpy",
    "virtual": "virtual_jpy",
    "ai16z": "ai16z_jpy",
    "arc":   "arc_jpy",
    "trump": "trump_jpy",
    "melania": "melania_jpy",
}


def _make_signature(secret: str, message: str) -> str:
    """HMAC-SHA256署名を生成する"""
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _private_get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    """
    bitbank プライベートAPI GET リクエスト
    ACCESS-TIME-WINDOW 方式で認証する
    """
    if not BITBANK_API_KEY or not BITBANK_API_SECRET:
        logger.error("BITBANK_API_KEY または BITBANK_API_SECRET が設定されていません")
        return None

    access_request_time = str(int(time.time() * 1000))
    access_time_window = "5000"

    # クエリ文字列を構築
    query_string = ""
    if params:
        query_string = "?" + "&".join(f"{k}={v}" for k, v in params.items())

    full_path = f"/v1{path}{query_string}"

    # 署名メッセージ: ACCESS-REQUEST-TIME + ACCESS-TIME-WINDOW + full_path
    message = access_request_time + access_time_window + full_path
    signature = _make_signature(BITBANK_API_SECRET, message)

    headers = {
        "ACCESS-KEY": BITBANK_API_KEY,
        "ACCESS-SIGNATURE": signature,
        "ACCESS-REQUEST-TIME": access_request_time,
        "ACCESS-TIME-WINDOW": access_time_window,
        "Content-Type": "application/json",
    }

    url = PRIVATE_BASE_URL + path
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") == 1:
            return data.get("data")
        else:
            error_code = data.get("data", {}).get("code", "unknown")
            logger.error(f"bitbank API エラー: code={error_code}, path={path}")
            return None
    except requests.RequestException as e:
        logger.error(f"bitbank API リクエストエラー: {e}")
        return None


def get_ticker(pair: str) -> Optional[dict]:
    """
    パブリックAPIから指定ペアのティッカー情報を取得する
    Returns: {"last": "...", "sell": "...", "buy": "..."} or None
    """
    url = f"{PUBLIC_BASE_URL}/{pair}/ticker"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") == 1:
            return data.get("data")
        return None
    except requests.RequestException as e:
        logger.error(f"ticker取得エラー ({pair}): {e}")
        return None


def get_assets() -> Optional[list]:
    """
    保有資産一覧を取得する
    Returns: assets リスト or None
    """
    data = _private_get("/user/assets")
    if data is None:
        return None
    return data.get("assets", [])


def get_portfolio() -> Optional[dict]:
    """
    保有資産のポートフォリオ情報を取得・計算して返す。

    Returns:
        {
            "total_jpy": float,          # 総評価額（JPY）
            "assets": [
                {
                    "asset": str,        # 通貨シンボル (例: "btc")
                    "name": str,         # 日本語名
                    "amount": float,     # 保有数量（onhand_amount）
                    "free_amount": float,# 利用可能数量
                    "price_jpy": float,  # 現在価格（JPY）
                    "value_jpy": float,  # 評価額（JPY）
                    "precision": int,    # 数量の小数点以下桁数
                },
                ...
            ],
            "error": None or str,
        }
    """
    result = {
        "total_jpy": 0.0,
        "assets": [],
        "error": None,
    }

    # 資産一覧を取得
    assets = get_assets()
    if assets is None:
        result["error"] = "API認証エラー: BITBANK_API_KEY / BITBANK_API_SECRET を確認してください"
        return result

    portfolio_assets = []
    total_jpy = 0.0

    for asset_info in assets:
        asset = asset_info.get("asset", "")
        onhand_amount_str = asset_info.get("onhand_amount", "0")
        free_amount_str = asset_info.get("free_amount", "0")
        precision = asset_info.get("amount_precision", 8)

        try:
            onhand_amount = float(onhand_amount_str)
            free_amount = float(free_amount_str)
        except (ValueError, TypeError):
            onhand_amount = 0.0
            free_amount = 0.0

        # 保有量が0の場合はスキップ
        if onhand_amount <= 0:
            continue

        # JPYはそのまま評価額
        if asset == "jpy":
            value_jpy = onhand_amount
            price_jpy = 1.0
        else:
            # ティッカーから現在価格を取得
            pair = JPY_PAIRS.get(asset)
            if pair:
                ticker = get_ticker(pair)
                if ticker:
                    try:
                        price_jpy = float(ticker.get("last", 0))
                    except (ValueError, TypeError):
                        price_jpy = 0.0
                else:
                    price_jpy = 0.0
            else:
                price_jpy = 0.0

            value_jpy = onhand_amount * price_jpy

        total_jpy += value_jpy

        name = ASSET_NAMES.get(asset, asset.upper())
        portfolio_assets.append({
            "asset": asset,
            "name": name,
            "amount": onhand_amount,
            "free_amount": free_amount,
            "price_jpy": price_jpy,
            "value_jpy": value_jpy,
            "precision": precision,
        })

    # 評価額の大きい順にソート（JPYを先頭に）
    jpy_assets = [a for a in portfolio_assets if a["asset"] == "jpy"]
    other_assets = [a for a in portfolio_assets if a["asset"] != "jpy"]
    other_assets.sort(key=lambda x: x["value_jpy"], reverse=True)

    result["assets"] = jpy_assets + other_assets
    result["total_jpy"] = total_jpy

    return result


def format_portfolio_message(portfolio: dict) -> str:
    """
    ポートフォリオ情報をTelegramメッセージ用にフォーマットする
    """
    if portfolio.get("error"):
        return f"❌ エラー: {portfolio['error']}"

    assets = portfolio.get("assets", [])
    total_jpy = portfolio.get("total_jpy", 0.0)

    if not assets:
        return (
            "💰 【仮想通貨ポートフォリオ】\n\n"
            "保有資産はありません。"
        )

    lines = ["💰 【仮想通貨ポートフォリオ】\n"]

    for asset_data in assets:
        asset = asset_data["asset"]
        name = asset_data["name"]
        amount = asset_data["amount"]
        price_jpy = asset_data["price_jpy"]
        value_jpy = asset_data["value_jpy"]
        precision = asset_data["precision"]

        # 通貨シンボルと名前
        lines.append(f"━━━━━━━━━━━━━━━━")
        lines.append(f"🪙 {asset.upper()} ({name})")

        if asset == "jpy":
            lines.append(f"  残高: ¥{amount:,.0f}")
        else:
            # 保有数量（精度に応じてフォーマット）
            if precision <= 0:
                amount_str = f"{amount:,.0f}"
            elif precision <= 4:
                amount_str = f"{amount:,.{precision}f}"
            else:
                # 末尾ゼロを除去
                amount_str = f"{amount:.{precision}f}".rstrip("0").rstrip(".")

            lines.append(f"  保有数量: {amount_str} {asset.upper()}")

            if price_jpy > 0:
                # 価格フォーマット（1円未満は小数点表示）
                if price_jpy >= 1:
                    price_str = f"¥{price_jpy:,.2f}"
                else:
                    price_str = f"¥{price_jpy:.6f}"
                lines.append(f"  現在価格: {price_str}")
                lines.append(f"  評価額:   ¥{value_jpy:,.0f}")
            else:
                lines.append(f"  評価額:   価格取得不可")

    lines.append("━━━━━━━━━━━━━━━━")
    lines.append(f"\n📊 総評価額: ¥{total_jpy:,.0f}")

    return "\n".join(lines)
