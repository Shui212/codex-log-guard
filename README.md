# Codex Log Guard

用于检测并缓解 Codex `logs_2.sqlite` 持续高频写入问题的 Codex Skill，对应 [openai/codex#28224](https://github.com/openai/codex/issues/28224)。

它会先采样诊断日志数据库的写入情况；只有达到配置阈值时，才会创建可逆的 SQLite 触发器，阻止新的诊断日志写入，并截断 WAL 文件。

## 功能

- 自动定位 `CODEX_HOME/logs_2.sqlite`，默认使用 `~/.codex/logs_2.sqlite`
- 仅查询行数、`MAX(id)`、估算字节和文件大小，不读取日志正文
- 默认采样 15 秒
- 当 `MAX(id)` 增量达到 20，或 WAL 增长达到 256 KiB 时判定为高频写入
- 幂等创建 `block_log_inserts` 触发器
- 执行 `PRAGMA wal_checkpoint(TRUNCATE)`
- 支持只检测、强制保护和一键回滚
- 可由 Codex Automation 定期运行

## 安装

将仓库克隆到 Codex Skills 目录：

```bash
git clone https://github.com/Shui212/codex-log-guard.git ~/.codex/skills/codex-log-guard
```

重新启动 Codex 后，可以通过 `$codex-log-guard` 使用该 Skill。

## 使用

进入 Skill 目录后运行：

```bash
python scripts/codex_log_guard.py --json
```

仅检测，不修改数据库：

```bash
python scripts/codex_log_guard.py --dry-run --json
```

不采样，立即安装保护触发器：

```bash
python scripts/codex_log_guard.py --force --json
```

移除保护触发器：

```bash
python scripts/codex_log_guard.py --remove --json
```

自定义检测条件：

```bash
python scripts/codex_log_guard.py \
  --sample-seconds 30 \
  --id-threshold 50 \
  --wal-threshold-bytes 524288 \
  --json
```

PowerShell 也可以使用相同参数：

```powershell
python .\scripts\codex_log_guard.py --dry-run --json
```

## 自动化

可以在 Codex 中创建定期自动化，让它调用 `$codex-log-guard` 检查数据库。触发器一旦创建就会持续生效；定期自动化主要用于防止 Codex 更新或重建数据库后触发器丢失。

建议自动化任务执行：

```text
使用 $codex-log-guard 检测当前用户的 Codex logs_2.sqlite。
如果检测到高频写入，安装并验证 block_log_inserts，然后截断 WAL。
不要删除日志、不要运行 VACUUM、不要修改其他表。
```

## 工作原理

检测到高频写入后，脚本创建以下触发器：

```sql
CREATE TRIGGER IF NOT EXISTS block_log_inserts
BEFORE INSERT ON logs
BEGIN
  SELECT RAISE(IGNORE);
END;
```

该触发器位于 `logs_2.sqlite` 数据库内部。只要数据库没有被删除或重建，它就会持续拦截来自 Codex 桌面版、Codex CLI 以及使用同一 `CODEX_HOME` 的 VS Code Codex 扩展的诊断日志写入。

## 注意事项

- 该方案是社区临时规避措施，不是 Codex 官方根治方案。
- 启用后，Codex 不再向这个诊断日志表保存新记录。
- 它不会删除聊天记录、项目文件或 Codex 状态数据库。
- 脚本不会删除现有日志，也不会自动执行 `VACUUM`。
- 已经膨胀的主数据库文件不会因 WAL 截断而自动缩小。
- 官方修复发布后，建议先用 `--remove` 移除触发器，再用 `--dry-run` 重新检测。

## 要求

- Python 3.9 或更高版本
- Python 标准库 `sqlite3`
- Windows、macOS 或 Linux

## 风险声明

本项目按现状提供。使用前请了解：阻止诊断日志写入可能降低故障反馈时可用的本地诊断信息。
