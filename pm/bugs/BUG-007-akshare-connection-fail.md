# BUG-007: AKShare 数据源连接失败

## 基本信息
- **Bug ID**: BUG-007
- **标题**: AKShare 数据源连接失败（RemoteDisconnected）
- **状态**: open
- **优先级**: P2
- **创建时间**: 2026-06-16 19:37
- **创建人**: data-agent
- **指派给**: dev-manager

## 描述
在数据完整性检查过程中，发现 AKShare 数据源无法连接，所有尝试均返回 `RemoteDisconnected` 错误。BaoStock 作为备选数据源工作正常。

## 错误信息
```
('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
```

## 影响
- AKShare 数据源 100% 失败
- 缺少一个冗余数据源
- 当前 BaoStock 工作正常，不影响主要功能

## 根本原因（待调查）
1. AKShare 版本过旧
2. AKShare 依赖的数据源服务端限流/IP封禁
3. 网络配置问题（代理、防火墙）

## 修复方案（待实施）
1. **排查 AKShare 问题**：
   - 检查并升级 AKShare 到最新版
   - 测试 AKShare 连接性
   
2. **增加数据源冗余**：
   - 配置 Tushare 作为额外备选
   - 实现多数据源智能切换

3. **数据源健康检查**：
   - 在 `backfill_data.py` 中增加数据源可达性检测
   - 不可用时自动切换到备选源

## 验收标准
1. AKShare 数据源恢复正常或
2. 实现多数据源冗余机制，单个源失败不影响数据抓取

## 状态历史
- 2026-06-16 19:37: 由 data-agent 创建（原 bugs/BUG-20260616-001-AKShare连接失败.md）
- 2026-06-17 01:06: 纳入 PM 流程，状态 `open`

## 附件
- `data/data_fetch.log` — 数据抓取日志
- `scripts/backfill_data.py` — 当前使用 BaoStock 主力 + AKShare 备选
