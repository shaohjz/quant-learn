#!/usr/bin/env python3
"""
check_qmt_status.py — 检查 QMT xtquant 导入状态和环境兼容性

用法:
  python scripts/check_qmt_status.py               # 使用当前 Python
  venv_qmt\Scripts\python.exe scripts\check_qmt_status.py  # 使用 venv
"""
import sys
import os
from pathlib import Path

QMT_SITE_PACKAGES = r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages"
VENV_QMT = Path(__file__).resolve().parent.parent / "venv_qmt" / "Scripts" / "python.exe"


def check_python_version() -> bool:
    print(f"Python 版本: {sys.version}")
    major, minor = sys.version_info[:2]
    if major == 3 and minor <= 11:
        print(f"✅ Python {major}.{minor} 兼容 xtquant（支持 <= 3.11）")
        return True
    else:
        print(f"❌ Python {major}.{minor} 不兼容 xtquant（需要 <= 3.11）")
        print(f"   可用 .pyd 文件: cp36, cp37, cp38, cp39, cp310, cp311")
        return False


def check_xtquant_import() -> bool:
    xtquant_path = QMT_SITE_PACKAGES
    if xtquant_path not in sys.path:
        sys.path.insert(0, xtquant_path)

    try:
        from xtquant import xtdata, xttrader  # type: ignore
        print(f"✅ xtquant.xtdata 导入成功（来自 {xtquant_path}）")
        print(f"✅ xtquant.xttrader 导入成功")
        return True
    except ImportError as e:
        print(f"❌ xtquant 导入失败: {e}")
        return False
    except Exception as e:
        print(f"❌ xtquant 导入异常: {e}")
        return False


def check_venv() -> None:
    if VENV_QMT.exists():
        print(f"✅ 找到 venv_qmt: {VENV_QMT}")
        import subprocess
        result = subprocess.run(
            [str(VENV_QMT), "-c", "import sys; print('  venv Python:', sys.version)"],
            capture_output=True, text=True,
        )
        print(f"   {result.stdout.strip()}")
    else:
        print(f"⚠️  venv_qmt 不存在: {VENV_QMT}")
        print(f"   创建方法: py -3.11 -m venv venv_qmt")


def check_qmt_client() -> bool:
    qmt_path = Path(r"D:\国金QMT交易端模拟\userdata_mini")
    if qmt_path.exists():
        print(f"✅ QMT userdata_mini 存在: {qmt_path}")
        return True
    else:
        print(f"⚠️  QMT userdata_mini 不存在: {qmt_path}")
        return False


def main():
    print("=" * 60)
    print("QMT 状态检查")
    print("=" * 60)

    print("\n[1] Python 版本检查")
    py_ok = check_python_version()

    print("\n[2] xtquant 导入检查")
    xt_ok = check_xtquant_import() if py_ok else False

    print("\n[3] venv_qmt 检查")
    check_venv()

    print("\n[4] QMT 客户端检查")
    check_qmt_client()

    print("\n" + "=" * 60)
    if py_ok and xt_ok:
        print("✅ QMT 网关可以正常使用")
        sys.exit(0)
    elif not py_ok:
        print("❌ Python 版本不兼容，请使用 Python 3.11")
        print(f"   运行: {VENV_QMT} scripts/check_qmt_status.py")
        sys.exit(1)
    else:
        print("⚠️  QMT 部分功能不可用，请检查 QMT 客户端")
        sys.exit(1)


if __name__ == "__main__":
    main()
