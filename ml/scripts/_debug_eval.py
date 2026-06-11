"""快速 debug：看 user_pool 的 pred / label 索引差异"""
import qlib, os, pandas as pd
from qlib.constant import REG_CN
from qlib.utils import init_instance_by_config
from qlib.data import D

qlib.init(provider_uri=os.path.expanduser("~/.qlib/qlib_data/cn_data"), region=REG_CN)

USER_POOL = ["SH600330","SZ002256","SZ002453","SZ002342","SH603601","SZ002709","SZ002149","SZ002156","SH605006","SH603757"]

# label
label = D.features(USER_POOL, ["Ref($close, -1)/$close - 1"], start_time="2020-01-01", end_time="2020-09-23", freq="day")
label.columns = ["label"]
print("label index names:", label.index.names)
print("label sample:")
print(label.head())
print("label instruments:", label.index.get_level_values(0).unique().tolist()[:5] if label.index.names[0] == 'instrument' else label.index.get_level_values(1).unique().tolist()[:5])

# 加载之前的 pred 还得训练；改用一个简单的 dataset.prepare 看格式
ds_cfg = {
    "class": "DatasetH",
    "module_path": "qlib.data.dataset",
    "kwargs": {
        "handler": {
            "class": "Alpha158",
            "module_path": "qlib.contrib.data.handler",
            "kwargs": {
                "start_time": "2020-01-01",
                "end_time":   "2020-09-23",
                "fit_start_time": "2020-01-01",
                "fit_end_time":   "2020-06-30",
                "instruments": USER_POOL,
            },
        },
        "segments": {
            "train": ("2020-01-01","2020-06-30"),
            "test":  ("2020-07-01","2020-09-23"),
        },
    },
}
ds = init_instance_by_config(ds_cfg)
df = ds.prepare("test", col_set=["label"], data_key="raw")
print("\n--- DatasetH test label ---")
print("index names:", df.index.names)
print(df.head())
