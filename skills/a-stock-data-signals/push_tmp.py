import sys
sys.path.insert(0, r"C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts")
from wecom_webhook import push_markdown

md = """# 📊 量化信号日报 — 2026-07-10

## 一、市场概览（权重抗跌、成长重挫）
- 上证指数 <font color="warning">-0.38%</font> | 上证50 <font color="info">+0.81%</font>（大盘蓝筹逆势）
- 深证成指 <font color="warning">-2.29%</font> | 创业板指 <font color="warning">-4.37%</font> | 科创50 <font color="warning">-4.49%</font>
- 中证1000 <font color="warning">-1.23%</font>
> 指数显著分化：上证50独红，科创/创业板上演深度回调，市场风险偏好明显回落。

## 二、当日强势股（共30只 · 题材集中度极高）
题材热度：商业航天(20) · 央企(11) · 卫星互联网(3) 居前
> 商业航天板块批量异动，央企属性叠加明显，资金主线高度集中。

**代表个股：**
- 中信重工(601608)：商业航天+矿山机器人+央企
- 中国卫通(601698)：卫星通信+卫星互联网+央企
- 航天电子(600879)：商业航天+无人系统+央企
- 中船科技(600072)：中船系+风电制氢氨醇
- 联环药业(600513)：创新药+LH-1801申报+扬州国资

## 三、题材热度 TOP10
商业航天 · 央企 · 人形机器人 · 卫星互联网 · 国企改革 · 国企 · 机器人 · CRO · 生猪养殖 · 中报预增
> 航天/军工+央企改革为日内最强主线；机器人、CRO、中报预增为潜在轮动方向。

## 四、北向资金（温和流出）
- 沪股通 <font color="warning">-9.28亿</font> | 深股通 <font color="warning">-31.10亿</font> | 合计 <font color="warning">-40.38亿</font>
> 外资延续净流出，深市抛压更重，与创业板/科创大跌相互印证。

## 五、龙虎榜
- 无数据（盘后未更新）

---
⚠️ 以上为量化信号梳理，不构成投资建议。"""

push_markdown(md)
print("PUSH_OK")
