#!/usr/bin/env python3
"""
import_production_data.py
从生产环境 MongoDB 导出数据并导入本地 MongoDB

功能:
  1. 连接生产环境 MongoDB (readPreference=secondary)
  2. 导出指定表全量数据为 JSON（使用 pymongo.json_util，保留 ObjectId 信息）
  3. 导入本地 MongoDB（递归将所有 _id 转为 str，避免 ObjectId 不可哈希错误）
  4. 支持 --env production/本地 自动识别

使用:
  # 默认: 导出 production 数据并导入本地
  python scripts/import_production_data.py

  # 只导出，不导入
  python scripts/import_production_data.py --export-only

  # 只导入已有 JSON 文件
  python scripts/import_production_data.py --import-only

  # 指定要导入的表（逗号分隔）
  python scripts/import_production_data.py --collections positions,trades

  # 查看生产环境数据统计
  python scripts/import_production_data.py --stats

  # 强制重新导出（覆盖已有 JSON）
  python scripts/import_production_data.py --force

  # 使用 pymongo.json_util 特殊处理（处理 ObjectId/Decimal128 等类型）
  python scripts/import_production_data.py --use-json-util

Author: @lancelt
Date: 2026-06-23
"""

import argparse
import json
import os
import sys
import datetime
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── pymongo json_util ────────────────────────────────────────────────────────
try:
    from bson import ObjectId, Decimal128
    from bson.json_util import CANONICAL_JSON_OPTIONS, RELAXED_JSON_OPTIONS, dumps as bson_dumps, loads as bson_loads
    HAS_BSON = True
except ImportError:
    HAS_BSON = False

# ── pymongo ───────────────────────────────────────────────────────────────────
try:
    import pymongo
    from pymongo import MongoClient
    from pymongo.uri_parser import parse_uri
    HAS_PYMONGO = True
except ImportError:
    HAS_PYMONGO = False


# ── 配置 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
WORKSPACE_DIR = SCRIPT_DIR.parent
DATA_DIR = WORKSPACE_DIR / "data" / "import"

# 生产环境 MongoDB URI（从环境变量读取，避免硬编码）
PROD_URI = os.environ.get(
    "QUANT_MONGODB_PROD_URI",
    "mongodb://prod-mongodb:27017/quant"
)

# 本地 MongoDB URI
LOCAL_URI = os.environ.get(
    "QUANT_MONGODB_LOCAL_URI",
    "mongodb://localhost:27017/quant"
)

# 默认要导出的表
DEFAULT_COLLECTIONS = [
    "positions",
    "trades",
    "daily_pnl",
    "signals",
    "valuation_history",
    "trading_days",
]


# ── 颜色输出 ─────────────────────────────────────────────────────────────────
class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    RESET = "\033[0m"

    @staticmethod
    def s(text: str, color: str) -> str:
        return f"{color}{text}{Color.RESET}"


def log_info(msg: str):
    print(f"{Color.s('[INFO]', Color.CYAN)} {msg}", flush=True)


def log_ok(msg: str):
    print(f"{Color.s('[OK]', Color.GREEN)} {msg}", flush=True)


def log_warn(msg: str):
    print(f"{Color.s('[WARN]', Color.YELLOW)} {msg}", flush=True)


def log_err(msg: str):
    print(f"{Color.s('[ERR]', Color.RED)} {msg}", flush=True)


# ── ObjectId 转换工具 ────────────────────────────────────────────────────────

def objectid_to_str(obj: Any) -> Any:
    """
    递归将对象中的 ObjectId 转为 str，
    同时处理 Decimal128, datetime, UUID 等 BSON 类型。

    这是解决 "unhashable type: ObjectId" 的核心函数。
    """
    if HAS_BSON:
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, Decimal128):
            return float(obj.to_decimal())
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, bytes):
            # UUID 等二进制类型
            try:
                return str(uuid.UUID(bytes=obj))
            except Exception:
                return obj.hex()

    if isinstance(obj, dict):
        return {k: objectid_to_str(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [objectid_to_str(item) for item in obj]
    else:
        return obj


def sanitize_for_json(obj: Any) -> Any:
    """
    将 BSON 特殊类型转为 JSON 可序列化类型。
    用于 json.dumps 前的最终清洗。
    """
    if HAS_BSON:
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, Decimal128):
            return float(obj.to_decimal())
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, datetime.date):
            return obj.isoformat()

    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    else:
        # 其他未知类型，转为字符串
        return str(obj)


# ── MongoDB 连接 ─────────────────────────────────────────────────────────────

def get_mongo_client(uri: str, read_preference: str = "primary") -> MongoClient:
    """获取 MongoDB 连接客户端"""
    if not HAS_PYMONGO:
        raise RuntimeError("pymongo 未安装，无法连接 MongoDB")

    kwargs = {
        "serverSelectionTimeoutMS": 5000,
        "connectTimeoutMS": 10000,
    }

    if read_preference == "secondary":
        from pymongo import ReadPreference
        kwargs["readPreference"] = ReadPreference.SECONDARY
    elif read_preference == "secondaryPreferred":
        from pymongo import ReadPreference
        kwargs["readPreference"] = ReadPreference.SECONDARY_PREFERRED

    client = MongoClient(uri, **kwargs)
    # 触发一次连接，验证可达性
    client.admin.command("ping")
    return client


def get_database_name(uri: str) -> str:
    """从 URI 中解析数据库名"""
    parsed = parse_uri(uri)
    db_name = parsed.get("database") or "quant"
    return db_name


# ── 导出 ─────────────────────────────────────────────────────────────────────

def export_collection(
    client: MongoClient,
    db_name: str,
    collection_name: str,
    output_path: Path,
    use_json_util: bool = False,
    query: Optional[Dict] = None,
    limit: Optional[int] = None,
) -> int:
    """
    导出单个 collection 到 JSON 文件。

    Args:
        use_json_util: 使用 pymongo.json_util.dumps（保留类型信息如 {"$oid": "..."}）
                       而不是纯 str 转换（更适合直接导入本地 MongoDB）

    Returns:
        导出的文档数量
    """
    db = client[db_name]
    coll = db[collection_name]

    final_query = query or {}
    count = coll.estimate_document_count() if not query else coll.count_documents(final_query)
    log_info(f"  {collection_name}: 共 {count} 条记录")

    # 使用 batch 方式导出，避免一次性加载到内存
    batch_size = 1000
    exported = 0

    # 写入 JSON 数组
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[\n")
        cursor = coll.find(final_query)
        if limit:
            cursor = cursor.limit(limit)
        cursor = cursor.batch_size(batch_size)

        for doc in cursor:
            # 转换 ObjectId 为 str
            doc_clean = objectid_to_str(doc)

            if use_json_util and HAS_BSON:
                # 使用 bson.json_util 序列化（保留类型信息）
                doc_json = bson_dumps(doc_clean, json_options=RELAXED_JSON_OPTIONS)
            else:
                doc_json = json.dumps(doc_clean, ensure_ascii=False, default=str)

            if exported > 0:
                f.write(",\n")
            f.write(doc_json)
            exported += 1

            if exported % 5000 == 0:
                log_info(f"  已导出 {exported}/{count} ...")

        f.write("\n]\n")

    log_ok(f"  {collection_name}: 导出 {exported} 条 → {output_path.name}")
    return exported


def export_all(
    uri: str,
    collections: List[str],
    output_dir: Path,
    use_json_util: bool = False,
    read_preference: str = "secondary",
    force: bool = False,
) -> Dict[str, int]:
    """
    导出多个 collection。

    Returns:
        {collection_name: exported_count}
    """
    log_info(f"连接生产环境 MongoDB: {uri[:60]}...")
    client = get_mongo_client(uri, read_preference=read_preference)
    db_name = get_database_name(uri)

    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for coll_name in collections:
        out_file = output_dir / f"{coll_name}.json"
        if out_file.exists() and not force:
            log_warn(f"  {coll_name}.json 已存在，使用 --force 覆盖")
            continue

        log_info(f"导出 {coll_name} ...")
        try:
            n = export_collection(
                client, db_name, coll_name, out_file,
                use_json_util=use_json_util,
            )
            results[coll_name] = n
        except Exception as e:
            log_err(f"  导出 {coll_name} 失败: {e}")
            results[coll_name] = -1

    client.close()
    return results


# ── 导入 ─────────────────────────────────────────────────────────────────────

def import_collection(
    client: MongoClient,
    db_name: str,
    collection_name: str,
    input_path: Path,
    drop_existing: bool = True,
    use_json_util: bool = False,
) -> int:
    """
    将 JSON 文件导入到本地 MongoDB。

    ObjectId 问题已在导出时转为 str，这里只需正常导入。
    如果 JSON 中含有 {"$oid": "..."} 格式（use_json_util=True 导出），
    则使用 bson.json_util.loads 解析。

    Returns:
        导入的文档数量
    """
    db = client[db_name]
    coll = db[collection_name]

    log_info(f"读取 {input_path.name} ...")
    with open(input_path, "r", encoding="utf-8") as f:
        if use_json_util and HAS_BSON:
            # 支持 {"$oid": "...", "$numberDecimal": "..."} 格式
            docs = bson_loads(f.read())
        else:
            docs = json.load(f)

    if not isinstance(docs, list):
        raise ValueError(f"{input_path.name} 内容不是 JSON 数组")

    log_info(f"  {collection_name}: 文件中有 {len(docs)} 条记录")

    if drop_existing:
        existing = coll.estimate_document_count()
        if existing > 0:
            log_warn(f"  {collection_name}: 本地已有 {existing} 条，先清空")
            coll.drop()
            log_info(f"  {collection_name}: 已清空")

    # 再次确保 _id 为 str（双重保险）
    docs_clean = [objectid_to_str(doc) for doc in docs]

    # 批量插入
    batch_size = 500
    inserted = 0
    for i in range(0, len(docs_clean), batch_size):
        batch = docs_clean[i:i + batch_size]
        try:
            coll.insert_many(batch, ordered=False)
            inserted += len(batch)
        except pymongo.errors.BulkWriteError as e:
            # 忽略重复 key 错误
            inserted += e.details.get("nInserted", 0)
            dup_errors = [err for err in e.details.get("writeErrors", []) if err.get("code") == 11000]
            if dup_errors:
                log_warn(f"  批次 {i // batch_size + 1}: {len(dup_errors)} 条重复，已跳过")
        except Exception as e:
            log_err(f"  批次 {i // batch_size + 1} 插入失败: {e}")

        if (i // batch_size + 1) % 10 == 0:
            log_info(f"  已插入 {inserted}/{len(docs_clean)} ...")

    # 重建索引
    log_info(f"  {collection_name}: 重建索引...")
    try:
        coll.create_index([("symbol", pymongo.ASCENDING)])
        coll.create_index([("open_date", pymongo.DESCENDING)])
        if collection_name == "trades":
            coll.create_index([("symbol", pymongo.ASCENDING), ("close_date", pymongo.DESCENDING)])
        log_ok(f"  {collection_name}: 索引已创建")
    except Exception as e:
        log_warn(f"  索引创建失败（可忽略）: {e}")

    log_ok(f"  {collection_name}: 成功导入 {inserted} 条")
    return inserted


def import_all(
    uri: str,
    input_dir: Path,
    collections: List[str],
    use_json_util: bool = False,
) -> Dict[str, int]:
    """
    从 JSON 文件导入多个 collection 到本地 MongoDB。

    Returns:
        {collection_name: imported_count}
    """
    log_info(f"连接本地 MongoDB: {uri[:60]}...")
    client = get_mongo_client(uri, read_preference="primary")
    db_name = get_database_name(uri)

    results = {}
    for coll_name in collections:
        in_file = input_dir / f"{coll_name}.json"
        if not in_file.exists():
            log_warn(f"  {coll_name}.json 不存在，跳过")
            continue

        log_info(f"导入 {coll_name} ...")
        try:
            n = import_collection(
                client, db_name, coll_name, in_file,
                use_json_util=use_json_util,
            )
            results[coll_name] = n
        except Exception as e:
            log_err(f"  导入 {coll_name} 失败: {e}")
            results[coll_name] = -1

    client.close()
    return results


# ── 统计 ─────────────────────────────────────────────────────────────────────

def show_stats(uri: str, collections: List[str], read_preference: str = "secondary"):
    """显示生产环境各表数据统计"""
    log_info(f"连接 MongoDB: {uri[:60]}...")
    client = get_mongo_client(uri, read_preference=read_preference)
    db_name = get_database_name(uri)
    db = client[db_name]

    print(f"\n{Color.s('═' * 60, Color.CYAN)}")
    print(f"{Color.s('  MongoDB 数据统计', Color.CYAN)}  ({uri[:50]}...)")
    print(f"{Color.s('═' * 60, Color.CYAN)}\n")

    for coll_name in collections:
        coll = db[coll_name]
        try:
            total = coll.estimate_document_count()
            # 最近一条记录的时间（如果有 time/data_time 字段）
            sample = coll.find_one(sort=[("$natural", -1)])
            time_str = ""
            if sample:
                for key in ["data_time", "time", "created_at", "open_date", "date"]:
                    if key in sample:
                        val = sample[key]
                        if isinstance(val, datetime.datetime):
                            time_str = f"  最新: {val.strftime('%Y-%m-%d %H:%M')}"
                        else:
                            time_str = f"  最新 {key}: {val}"
                        break

            print(f"  {Color.s(coll_name.ljust(25), Color.YELLOW)} {Color.s(f'{total:>8} 条', Color.GREEN)}  {time_str}")
        except Exception as e:
            print(f"  {coll_name.ljust(25)} 查询失败: {e}")

    print()
    client.close()


# ── 验证 ─────────────────────────────────────────────────────────────────────

def verify_import(local_uri: str, collections: List[str]) -> bool:
    """验证本地导入是否成功"""
    log_info("验证本地数据...")
    client = get_mongo_client(local_uri)
    db_name = get_database_name(local_uri)
    db = client[db_name]

    all_ok = True
    for coll_name in collections:
        coll = db[coll_name]
        try:
            count = coll.estimate_document_count()
            # 抽查一条，确认 _id 是 str 而非 ObjectId
            sample = coll.find_one()
            if sample:
                id_val = sample.get("_id")
                id_type = type(id_val).__name__
                if isinstance(id_val, str):
                    log_ok(f"  {coll_name}: {count} 条, _id 类型={id_type} ✓")
                else:
                    log_warn(f"  {coll_name}: {count} 条, _id 类型={id_type} (非 str，可能有问题)")
                    all_ok = False
            else:
                log_warn(f"  {coll_name}: 0 条（空表）")
        except Exception as e:
            log_err(f"  {coll_name}: 验证失败: {e}")
            all_ok = False

    client.close()
    return all_ok


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="从生产环境导入数据到本地 MongoDB")
    parser.add_argument("--prod-uri", default=PROD_URI, help="生产环境 MongoDB URI")
    parser.add_argument("--local-uri", default=LOCAL_URI, help="本地 MongoDB URI")
    parser.add_argument("--collections", default=",".join(DEFAULT_COLLECTIONS),
                        help="要导出的表名，逗号分隔")
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="JSON 文件存放目录")
    parser.add_argument("--export-only", action="store_true",
                        help="只导出，不导入")
    parser.add_argument("--import-only", action="store_true",
                        help="只导入已有 JSON 文件")
    parser.add_argument("--stats", action="store_true",
                        help="只显示生产环境数据统计")
    parser.add_argument("--force", action="store_true",
                        help="强制重新导出（覆盖已有 JSON）")
    parser.add_argument("--use-json-util", action="store_true",
                        help="使用 pymongo.json_util 序列化（保留 $oid 等类型信息）")
    parser.add_argument("--read-preference", default="secondary",
                        choices=["primary", "secondary", "secondaryPreferred"],
                        help="生产环境读偏好")
    parser.add_argument("--verify", action="store_true",
                        help="导入后验证数据")
    args = parser.parse_args()

    if not HAS_PYMONGO:
        log_err("pymongo 未安装，请执行: pip install pymongo")
        sys.exit(1)

    collections = [c.strip() for c in args.collections.split(",") if c.strip()]
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # ── 只显示统计 ────────────────────────────────────────────────────────────
    if args.stats:
        show_stats(args.prod_uri, collections, read_preference=args.read_preference)
        return

    # ── 只导入 ────────────────────────────────────────────────────────────────
    if args.import_only:
        log_info("模式: 只导入（--import-only）")
        results = import_all(
            uri=args.local_uri,
            input_dir=data_dir,
            collections=collections,
            use_json_util=args.use_json_util,
        )
        log_info("导入结果:")
        for name, n in results.items():
            status = f"{n} 条" if n >= 0 else "失败"
            log_info(f"  {name}: {status}")

        if args.verify:
            verify_import(args.local_uri, collections)
        return

    # ── 导出 + 导入 ───────────────────────────────────────────────────────────
    log_info("模式: 导出 + 导入")

    # 1) 导出
    log_info(f"{Color.s('─' * 50, Color.CYAN)}")
    log_info("Step 1/2: 从生产环境导出数据")
    log_info(f"{Color.s('─' * 50, Color.CYAN)}")
    export_results = export_all(
        uri=args.prod_uri,
        collections=collections,
        output_dir=data_dir,
        use_json_util=args.use_json_util,
        read_preference=args.read_preference,
        force=args.force,
    )

    # 2) 导入
    log_info(f"{Color.s('─' * 50, Color.CYAN)}")
    log_info("Step 2/2: 导入到本地 MongoDB")
    log_info(f"{Color.s('─' * 50, Color.CYAN)}")
    import_results = import_all(
        uri=args.local_uri,
        input_dir=data_dir,
        collections=collections,
        use_json_util=args.use_json_util,
    )

    # 3) 验证
    if args.verify or True:  # 默认验证
        log_info(f"{Color.s('─' * 50, Color.CYAN)}")
        log_info("Step 3/3: 验证导入结果")
        log_info(f"{Color.s('─' * 50, Color.CYAN)}")
        verify_import(args.local_uri, collections)

    # 总结
    print(f"\n{Color.s('═' * 60, Color.CYAN)}")
    print(f"{Color.s('  导入完成', Color.CYAN)}")
    print(f"{Color.s('═' * 60, Color.CYAN)}\n")
    print(f"  JSON 文件目录: {data_dir}")
    print(f"  本地 MongoDB:  {args.local_uri}")
    print()


if __name__ == "__main__":
    main()
