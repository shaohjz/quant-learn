#!/bin/bash
#
# A股量化回测 - 一键运行脚本
# 先拉取数据，再对每只股票跑三个策略，最后输出对比结果
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║           A 股量化回测系统 - 一键运行                    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ──────────── Step 1: 拉取数据 ────────────
echo "📥 Step 1: 拉取股票数据..."
echo ""
python3 data/fetch_data.py
echo ""

# ──────────── Step 2: 逐一回测 ────────────
echo "📊 Step 2: 开始回测..."

STOCKS=("000967" "002256")
STOCK_NAMES=("盈峰环境" "兆新股份")
STRATEGIES=("sma_cross" "macd_strategy" "bollinger_strategy")
STRATEGY_NAMES=("双均线策略" "MACD策略" "布林带策略")

# 结果收集（用临时文件）
RESULT_FILE=$(mktemp)
echo "stock_code,stock_name,strategy,total_return,annual_return,max_drawdown,sharpe_ratio,trades,win_rate" > "$RESULT_FILE"

for i in "${!STOCKS[@]}"; do
    stock="${STOCKS[$i]}"
    stock_name="${STOCK_NAMES[$i]}"

    for j in "${!STRATEGIES[@]}"; do
        strategy="${STRATEGIES[$j]}"
        strategy_name="${STRATEGY_NAMES[$j]}"

        echo ""
        echo "▶ 回测: ${stock_name}(${stock}) - ${strategy_name}"
        output=$(python3 backtest.py --stock "$stock" --strategy "$strategy" 2>&1) || true
        echo "$output"

        # 提取数值写入结果文件
        total_ret=$(echo "$output" | grep "总收益率" | grep -oP '[+-]?[\d.]+' | head -1 || echo "N/A")
        annual_ret=$(echo "$output" | grep "年化收益率" | grep -oP '[+-]?[\d.]+' | head -1 || echo "N/A")
        max_dd=$(echo "$output" | grep "最大回撤" | grep -oP '[\d.]+' | head -1 || echo "N/A")
        sharpe=$(echo "$output" | grep "夏普比率" | grep -oP '[+-]?[\d.]+' | head -1 || echo "N/A")
        trades=$(echo "$output" | grep "交易次数" | grep -oP '[\d]+' | head -1 || echo "N/A")
        winrate=$(echo "$output" | grep "胜率" | grep -oP '[\d.]+' | head -1 || echo "N/A")

        echo "${stock},${stock_name},${strategy_name},${total_ret},${annual_ret},${max_dd},${sharpe},${trades},${winrate}" >> "$RESULT_FILE"
    done
done

# ──────────── Step 3: 对比汇总 ────────────
echo ""
echo ""
echo "╔══════════════════════════════════════════════════════════════════════════════════╗"
echo "║                              回 测 结 果 汇 总                                 ║"
echo "╠══════════════════════════════════════════════════════════════════════════════════╣"

printf "║ %-12s %-12s %-12s %-10s %-10s %-10s %-10s %-8s ║\n" \
    "股票" "策略" "总收益%" "年化%" "最大回撤%" "夏普" "交易次数" "胜率%"
echo "╠══════════════════════════════════════════════════════════════════════════════════╣"

tail -n +2 "$RESULT_FILE" | while IFS=',' read -r code name strat tr ar dd sr td wr; do
    printf "║ %-10s %-12s %10s %10s %10s %10s %8s %8s ║\n" \
        "$name" "$strat" "$tr" "$ar" "$dd" "$sr" "$td" "$wr"
done

echo "╚══════════════════════════════════════════════════════════════════════════════════╝"

# 保存汇总结果
cp "$RESULT_FILE" "$SCRIPT_DIR/output/summary.csv"
echo ""
echo "✅ 所有回测完成！"
echo "   📁 收益曲线图: output/"
echo "   📄 汇总CSV:    output/summary.csv"
echo ""

# 清理
rm -f "$RESULT_FILE"
