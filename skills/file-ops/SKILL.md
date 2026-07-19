---
name: file-ops
description: 文件操作 - 读取、写入、列出文件的最佳实践
---

# 文件操作技能

你拥有以下文件操作工具：
- read_file: 读取文件内容
- write_file: 写入或创建文件
- list_dir: 列出目录内容

## 使用原则

1. **先列出，后读取**：不确定文件路径时，先用 list_dir 查看目录结构
2. **读取前检查大小**：大文件先部分读取
3. **写入前确认**：覆盖已有文件前告知用户
4. **路径规范**：始终使用绝对路径

## 常见场景

- "帮我看看 README 里写了什么" → read_file /workspace/README.md
- "在项目里创建一个配置文件" → write_file /workspace/project/config.json
- "列出当前目录下所有 Python 文件" → list_dir 然后用 read_file
