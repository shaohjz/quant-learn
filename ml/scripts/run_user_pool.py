"""
scripts/run_user_pool.py — 用户 10 只股票的 LightGBM 回测

股池：
  持仓 5 只: SH600330 / SZ002256 / SZ002453 / SZ002342 / SH603601
  观察 5 只: SZ002709 / SZ002149 / SZ002156 / SH605006 / SH603757

输出:
  output/user_pool_result.txt    — 指标摘要 + 命中率 + 最新 score
  output/signals.json            — 桥接 quant-learn 用的当日信号
"""
from __future__ import annotations
import sys, json, os
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

import qlib
from qlib.constant import REG_CN
from qlib.data import D
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True, parents=True)
RESULT_FILE = OUTPUT / "user_pool_result.txt"
SIGNALS_FILE = OUTPUT / "signals.json"

PROVIDER_URI = os.path.expanduser("~/.qlib/qlib_data/cn_data")

# ------------------------------------------------------------------
# 用户股池（qlib 风格代码）
# ------------------------------------------------------------------
HOLDINGS = ["SH600330", "SZ002256", "SZ002453", "SZ002342", "SH603601"]
WATCHLIST = ["SZ002709", "SZ002149", "SZ002156", "SH605006", "SH603757"]
NAME_MAP = {
    "SH600330": "天通股份", "SZ002256": "兆新股份", "SZ002453": "华软科技",
    "SZ002342": "巨力索具", "SH603601": "再升科技", "SZ002709": "天赐材料",
    "SZ002149": "西部材料", "SZ002156": "通富微电", "SH605006": "山东玻纤",
    "SH603757": "大元泵业",
}
USER_POOL = HOLDINGS + WATCHLIST


def to_short_code(qcode: str) -> str:
    """SH600330 -> 600330"""
    return qcode[2:]


# ------------------------------------------------------------------
qlib.init(provider_uri=PROVIDER_URI, region=REG_CN)


# ------------------------------------------------------------------
# 1. 用 csi300 池训练（10只股票太少，IC 分位无意义；
#    训练用大池，预测时投影到用户10只）
# ------------------------------------------------------------------
TRAIN = ("2014-01-01", "2018-12-31")
VALID = ("2019-01-01", "2019-06-30")
TEST  = ("2019-07-01", "2020-09-23")

handler_kwargs = {
    "start_time": TRAIN[0],
    "end_time":   TEST[1],
    "fit_start_time": TRAIN[0],
    "fit_end_time":   TRAIN[1],
    "instruments":    "csi300",
}

task = {
    "model": {
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "colsample_bytree": 0.8,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "lambda_l1": 100,
            "lambda_l2": 200,
            "max_depth": 8,
            "num_leaves": 128,
            "num_threads": 8,
        },
    },
    "dataset": {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": {
                "class": "Alpha158",
                "module_path": "qlib.contrib.data.handler",
                "kwargs": handler_kwargs,
            },
            "segments": {
                "train": TRAIN,
                "valid": VALID,
                "test":  TEST,
            },
        },
    },
}


def predict_for_user_pool(model):
    """对用户池单独跑 inference（避免 csi300 测试集中可能不含全部 10 只）。"""
    user_handler_kwargs = {
        "start_time": TRAIN[0],
        "end_time":   TEST[1],
        "fit_start_time": TRAIN[0],
        "fit_end_time":   TRAIN[1],
        "instruments": USER_POOL,
    }
    user_dataset_cfg = {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": {
                "class": "Alpha158",
                "module_path": "qlib.contrib.data.handler",
                "kwargs": user_handler_kwargs,
            },
            "segments": {
                "train": TRAIN,
                "valid": VALID,
                "test":  TEST,
            },
        },
    }
    user_ds = init_instance_by_config(user_dataset_cfg)
    pred = model.predict(user_ds, segment="test")
    # pred: pd.Series (datetime, instrument) -> score
    return pred


def evaluate_hit_rate(pred: pd.Series, label: pd.Series) -> dict:
    """简单的方向命中率：score>0 当作"看多"，与第二日 ret>0 比较。"""
    df = pd.concat({"score": pred, "label": label}, axis=1).dropna()
    if df.empty:
        return {"hit_rate": None, "n_obs": 0}
    df["pred_sign"] = np.sign(df["score"])
    df["true_sign"] = np.sign(df["label"])
    hit = (df["pred_sign"] == df["true_sign"]).mean()
    long_only = df[df["pred_sign"] > 0]
    hit_long = (long_only["true_sign"] > 0).mean() if len(long_only) else None
    return {
        "hit_rate":      float(hit),
        "hit_rate_long": float(hit_long) if hit_long is not None else None,
        "n_obs":         int(len(df)),
        "n_long":        int(len(long_only)),
    }


def get_realized_label(start, end):
    """用 next-day return 作为 label（与 Alpha158 默认 label 相同思路）。"""
    feature = D.features(USER_POOL, ["Ref($close, -1)/$close - 1"], start_time=start, end_time=end, freq="day")
    feature.columns = ["label"]
    return feature["label"]


def calc_cumulative_return(pred: pd.Series, label_ret: pd.Series, threshold_quantile=0.5) -> dict:
    """简化的累计收益估算：
       每天选 score 排名前 N 只（N=3）等权持有，next-day 收益累加。
    """
    df = pd.concat({"score": pred, "ret": label_ret}, axis=1).dropna()
    if df.empty:
        return {"cum_return": None, "annualized": None, "trading_days": 0}
    # 每日 cross-section
    df = df.reset_index()
    df.columns = ["dt", "code", "score", "ret"]
    daily = []
    for d, g in df.groupby("dt"):
        if len(g) < 3:
            continue
        topk = g.nlargest(3, "score")
        daily.append({"dt": d, "ret": topk["ret"].mean()})
    if not daily:
        return {"cum_return": None, "annualized": None, "trading_days": 0}
    daily_df = pd.DataFrame(daily).set_index("dt").sort_index()
    cum = (1 + daily_df["ret"]).prod() - 1
    n = len(daily_df)
    ann = (1 + cum) ** (252 / n) - 1 if n else None
    sharpe = (daily_df["ret"].mean() / daily_df["ret"].std()) * np.sqrt(252) if daily_df["ret"].std() > 0 else None
    return {
        "cum_return": float(cum),
        "annualized": float(ann) if ann is not None else None,
        "sharpe": float(sharpe) if sharpe is not None else None,
        "trading_days": n,
    }


def export_signals(latest_scores: pd.Series, ic: float, rank_ic: float, trading_dt=None):
    """根据当日 score 写 signals.json（设计契约 v1，参见 docs/integration.md）。"""
    if latest_scores.empty:
        return None
    # 排名 + 分位
    df = latest_scores.reset_index()
    df.columns = ["code", "score"]
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    df["quantile"] = 1 - (df["rank"] - 1) / max(len(df) - 1, 1)

    def action(q):
        if q >= 0.80:
            return "BUY"
        if q <= 0.20:
            return "SELL"
        return "HOLD"

    score_std = df["score"].std()
    confidence_floor = 0.30
    score_range = df["score"].max() - df["score"].min() or 1.0

    signals = []
    for _, row in df.iterrows():
        a = action(row["quantile"])
        # 置信度：score 离均值越远越大；同时受 IC 影响
        z = abs(row["score"] - df["score"].mean()) / (score_std or 1.0)
        conf = max(confidence_floor, min(1.0, 0.4 + 0.3 * z + 0.3 * abs(rank_ic or 0) * 10))
        signals.append({
            "code": to_short_code(row["code"]),
            "qlib_code": row["code"],
            "name": NAME_MAP.get(row["code"], ""),
            "score": float(row["score"]),
            "rank": int(row["rank"]),
            "quantile": float(row["quantile"]),
            "action": a,
            "confidence": float(conf),
        })

    # trading_date: 优先使用外部传入的 trading_dt（应为 Timestamp），其次尝试从 index 读，都不行就用 today
    try:
        if trading_dt is not None:
            trading_date = pd.Timestamp(trading_dt).strftime("%Y-%m-%d")
        else:
            trading_date = datetime.now().strftime("%Y-%m-%d")
    except Exception:
        trading_date = datetime.now().strftime("%Y-%m-%d")

    payload = {
        "schema_version": "1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": "lightgbm-alpha158-userpool-v1",
        "trading_date": trading_date,
        "valid_until": (datetime.now().replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone().isoformat(timespec="seconds"),
        "metadata": {
            "ic": float(ic) if ic is not None else None,
            "rank_ic": float(rank_ic) if rank_ic is not None else None,
            "stock_pool_size": len(signals),
        },
        "signals": signals,
    }

    tmp = SIGNALS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SIGNALS_FILE)
    return payload


# ------------------------------------------------------------------
def main():
    print("[1/4] training LightGBM on Alpha158 / CSI300 ...", flush=True)
    model = init_instance_by_config(task["model"])
    dataset = init_instance_by_config(task["dataset"])
    model.fit(dataset)

    print("[2/4] predicting on user 10-stock pool ...", flush=True)
    pred = predict_for_user_pool(model)

    label = get_realized_label(TEST[0], TEST[1])
    # 统一两个 Series 的 MultiIndex
    pred.index.names = ["datetime", "instrument"]
    label.index.names = ["datetime", "instrument"]
    
    # 重要修复：D.features 返回的 index 顺序是 (instrument, datetime)，pred 是 (datetime, instrument)
    # 反正化为同一顺序才能 join
    if isinstance(label.index, pd.MultiIndex):
        # 探测 label 到底是哪个顺序
        if label.index.names[0] == "instrument" or (label.index.names[0] is None and not isinstance(label.index.get_level_values(0)[0], pd.Timestamp)):
            label = label.swaplevel().sort_index()
            label.index.names = ["datetime", "instrument"]
    
    aligned = pd.concat({"score": pred, "label": label}, axis=1, join="inner").dropna()

    if aligned.empty:
        ic = rank_ic = None
        hit = {"hit_rate": None, "hit_rate_long": None, "n_obs": 0}
        cum_ret = {"cum_return": None, "annualized": None, "sharpe": None, "trading_days": 0}
    else:
        # IC: 每日横截面 pearson
        def daily_ic(g, method):
            if len(g) < 3:
                return np.nan
            return g["score"].corr(g["label"], method=method)
        ic_series = aligned.groupby(level=0).apply(lambda g: daily_ic(g, "pearson"))
        rank_ic_series = aligned.groupby(level=0).apply(lambda g: daily_ic(g, "spearman"))
        ic = float(ic_series.mean()) if not ic_series.empty else None
        rank_ic = float(rank_ic_series.mean()) if not rank_ic_series.empty else None

        hit = evaluate_hit_rate(aligned["score"], aligned["label"])
        cum_ret = calc_cumulative_return(aligned["score"], aligned["label"])

    print("[3/4] writing summary ...", flush=True)
    # 拿"最近一个交易日"的 score 作为 signals.json
    if not pred.empty:
        latest_dt = pred.index.get_level_values(0).max()
        latest_scores = pred.xs(latest_dt, level=0)
    else:
        latest_dt = None
        latest_scores = pd.Series(dtype=float)

    summary_lines = [
        "=" * 70,
        "quant-qlib · 用户10股池 LightGBM 回测",
        f"generated_at: {datetime.now().isoformat()}",
        f"train: {TRAIN}",
        f"valid: {VALID}",
        f"test:  {TEST}",
        f"stock_pool ({len(USER_POOL)}): {USER_POOL}",
        "=" * 70,
        "",
        f"[ IC (pearson, daily-mean) ] = {ic}",
        f"[ Rank IC (spearman daily-mean) ] = {rank_ic}",
        "",
        f"[ 命中率 ] = {hit}",
        f"[ Top-3 等权累计收益 ] = {cum_ret}",
        "",
        "[ 最近一日 score ranking (越高越看多) ]",
    ]
    if not latest_scores.empty:
        ranked = latest_scores.sort_values(ascending=False)
        for code, score in ranked.items():
            short = to_short_code(code)
            name = NAME_MAP.get(code, "")
            summary_lines.append(f"  {code} {name:<8} score={score: .6f}  ({short})")

    print("[4/4] exporting signals.json ...", flush=True)
    payload = export_signals(latest_scores, ic, rank_ic, latest_dt)
    if payload:
        summary_lines.append("")
        summary_lines.append("[ signals.json BUY/SELL ]")
        for s in payload["signals"]:
            mark = "🟢" if s["action"] == "BUY" else ("🔴" if s["action"] == "SELL" else "⚪")
            summary_lines.append(f"  {mark} {s['qlib_code']} {s['name']:<8} action={s['action']:<5} q={s['quantile']:.2f}  conf={s['confidence']:.2f}")

    out = "\n".join(summary_lines)
    RESULT_FILE.write_text(out, encoding="utf-8")
    print(out)
    print(f"\n📄 result -> {RESULT_FILE}")
    print(f"📡 signals -> {SIGNALS_FILE}")


if __name__ == "__main__":
    main()
