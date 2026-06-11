"""
scripts/run_demo.py — qlib 官方 quickstart 风格 demo

跑通 LightGBM + Alpha158 + CSI300 + 周频再平衡 TopkDropoutStrategy。
输出指标到 output/qlib_demo_result.txt。

参考:
 - qlib.contrib.workflow
 - https://github.com/microsoft/qlib/blob/main/examples/workflow_by_code.py
"""
from __future__ import annotations
import sys, json, os
from pathlib import Path
from datetime import datetime

import pandas as pd

import qlib
from qlib.constant import REG_CN
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import SignalRecord, PortAnaRecord, SigAnaRecord

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True, parents=True)
RESULT_FILE = OUTPUT / "qlib_demo_result.txt"

PROVIDER_URI = os.path.expanduser("~/.qlib/qlib_data/cn_data")
MARKET = "csi300"
BENCHMARK = "SH000300"


# ------------------------------------------------------------------
# qlib 配置
# ------------------------------------------------------------------
qlib.init(provider_uri=PROVIDER_URI, region=REG_CN)


# ------------------------------------------------------------------
# 1. 数据 handler
# ------------------------------------------------------------------
# ⚠️ qlib 免费 cn_data 当前只更新到 2020-09-25，故区间被压在此之前。
# 想要 2021+ 的数据需要自行 dump（详见 README 已知坑）。
data_handler_config = {
    "start_time": "2010-01-01",
    "end_time":   "2020-09-25",
    "fit_start_time": "2010-01-01",
    "fit_end_time":   "2017-12-31",
    "instruments": MARKET,
}

TRAIN = ("2010-01-01", "2017-12-31")
VALID = ("2018-01-01", "2018-12-31")
TEST  = ("2019-01-01", "2020-09-23")  # 预留 buffer 避开 backtest_loop 越界


# ------------------------------------------------------------------
# 2. task 定义：LightGBM + Alpha158
# ------------------------------------------------------------------
task = {
    "model": {
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "colsample_bytree": 0.8879,
            "learning_rate": 0.0421,
            "subsample": 0.8789,
            "lambda_l1": 205.6999,
            "lambda_l2": 580.9768,
            "max_depth": 8,
            "num_leaves": 210,
            "num_threads": 20,
        },
    },
    "dataset": {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": {
                "class": "Alpha158",
                "module_path": "qlib.contrib.data.handler",
                "kwargs": data_handler_config,
            },
            "segments": {
                "train": TRAIN,
                "valid": VALID,
                "test":  TEST,
            },
        },
    },
}

port_analysis_config = {
    "executor": {
        "class": "SimulatorExecutor",
        "module_path": "qlib.backtest.executor",
        "kwargs": {
            "time_per_step": "day",
            "generate_portfolio_metrics": True,
        },
    },
    "strategy": {
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {
            "signal": "<PRED>",   # 由 PortAnaRecord 自动注入
            "topk": 50,
            "n_drop": 5,
        },
    },
    "backtest": {
        "start_time": TEST[0],
        "end_time":   TEST[1],
        "account": 100000000,
        "benchmark": BENCHMARK,  # SH000300 沪深300 指数
        "exchange_kwargs": {
            "freq": "day",
            "limit_threshold": 0.095,
            "deal_price": "close",
            "open_cost": 0.0005,
            "close_cost": 0.0015,
            "min_cost": 5,
        },
    },
}


# ------------------------------------------------------------------
# 3. 训练 + 回测
# ------------------------------------------------------------------
def main():
    model = init_instance_by_config(task["model"])
    dataset = init_instance_by_config(task["dataset"])

    print("[1/3] training LightGBM on Alpha158 / CSI300 ...", flush=True)
    with R.start(experiment_name="quant-qlib-demo"):
        R.log_params(**{k: v for k, v in task["model"]["kwargs"].items() if isinstance(v, (int, float, str))})
        model.fit(dataset)
        R.save_objects(**{"params.pkl": model})

        print("[2/3] generating predictions ...", flush=True)
        sr = SignalRecord(model, dataset, R.get_recorder())
        sr.generate()

        # 信号分析（IC, Rank IC, ICIR）
        sar = SigAnaRecord(R.get_recorder())
        sar.generate()

        print("[3/3] running portfolio backtest ...", flush=True)
        par = PortAnaRecord(R.get_recorder(), port_analysis_config, "day")
        par.generate()

        recorder = R.get_recorder()

        # 提取 metrics
        try:
            metrics = recorder.list_metrics()
        except Exception:
            metrics = {}

        # 也试着把 IC summary 单独捞出来
        try:
            ic_df = recorder.load_object("sig_analysis/ic.pkl")
            ric_df = recorder.load_object("sig_analysis/ric.pkl")
            ic_summary = {
                "IC_mean":  float(ic_df.mean().iloc[0]) if hasattr(ic_df, 'mean') else None,
                "IC_std":   float(ic_df.std().iloc[0]) if hasattr(ic_df, 'std')  else None,
                "RankIC_mean": float(ric_df.mean().iloc[0]) if hasattr(ric_df, 'mean') else None,
                "RankIC_std":  float(ric_df.std().iloc[0]) if hasattr(ric_df, 'std')  else None,
            }
        except Exception as e:
            ic_summary = {"error": str(e)}

        # 回测指标（年化、Sharpe、最大回撤等）
        try:
            port_metrics = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")
            port_metrics_str = port_metrics.to_string() if hasattr(port_metrics, 'to_string') else str(port_metrics)
        except Exception as e:
            port_metrics_str = f"<port_metrics load error: {e}>"

        # 写文件
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write("qlib demo backtest result\n")
            f.write(f"generated_at: {datetime.now().isoformat()}\n")
            f.write(f"market:    {MARKET}\n")
            f.write(f"benchmark: {BENCHMARK}\n")
            f.write(f"train: {TRAIN}\n")
            f.write(f"valid: {VALID}\n")
            f.write(f"test:  {TEST}\n")
            f.write("=" * 70 + "\n\n")

            f.write("[recorder.list_metrics()]\n")
            f.write(json.dumps(metrics, indent=2, default=str) + "\n\n")

            f.write("[IC / Rank IC]\n")
            f.write(json.dumps(ic_summary, indent=2) + "\n\n")

            f.write("[portfolio_analysis_1day]\n")
            f.write(port_metrics_str + "\n")

        print(f"\nResult written to: {RESULT_FILE}\n")
        print("--- summary ---")
        print(json.dumps(ic_summary, indent=2))
        print(port_metrics_str[:1500])


if __name__ == "__main__":
    main()
