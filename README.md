# 简易版 nanobot (simple_nanobot)

一个轻量级 AI 智能体框架的教学实现，约 1900 行 Python 代码，完整保留了 nanobot 核心架构的数据流和状态机模式。

## 功能特性

- **消息总线**：`asyncio.Queue` 双队列解耦消息收发
- **多通道支持**：CLI（命令行）+ QQ（botpy WebSocket）双通道
- **真实大模型**：OpenAI 兼容 API（`openai.AsyncOpenAI`），支持 DeepSeek、通义千问等
- **4 个工具**：shell / read_file / write_file / list_dir
- **技能系统**：SKILL.md 技能（officecli / tavily-search），渐进式加载，AI 用 read_file 读取完整内容
- **4 状态 Agent 循环**：RESTORE → BUILD → RUN → RESPOND
- **中文注释**：所有公开方法均有详细中文文档字符串

## 快速开始

### 安装

```bash
# 安装核心（Mock 模式，无需 API Key）
pip install -e .

# 安装 LLM 依赖（真实大模型）
pip install -e ".[llm]"

# 安装全部依赖（含 QQ 通道）
pip install -e ".[llm,qq,dev]"
```

### 配置

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env，填入 LLM API Key
# LLM_API_KEY=sk-xxx
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_MODEL=gpt-4o-mini
```

### 运行

```bash
python main.py
```

无 API Key 时自动降级为 MockProvider（模拟 AI）。

> 也可以用 `pip install -e .` 安装后，使用 `simple-nanobot` 命令启动。

### QQ 通道

在 `.env` 中配置 QQ 凭据：

```
QQ_APP_ID=你的AppID
QQ_SECRET=你的Secret
```

## 技能系统

技能是 `skills/<技能名>/SKILL.md` 文件，frontmatter 声明元数据（name / description / always），正文是给 AI 的操作指南。机制对齐原版 nanobot：

- **always: true**：每次会话都完整注入 system prompt
- **渐进式加载**：普通技能只在 system prompt 列出摘要（名称 + 描述 + 绝对路径），AI 使用技能前必须先 `read_file` 加载对应 SKILL.md
- **身份契约**：frontmatter 的 name 必须与目录名一致，且匹配 `[a-z0-9-]` 格式，否则该技能被跳过

## 运行测试

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## 架构概览

```
Channel (CLI/QQ) → MessageBus → AgentLoop(4状态) → AgentRunner(LLM多轮+工具) → MessageBus → Channel
```

## 项目结构

```
simple_nanobot/            # 项目根目录
├── events.py       # 消息事件数据结构
├── bus.py          # asyncio.Queue 消息总线
├── provider.py     # LLMProvider (Mock + OpenAI)
├── tools.py        # 4 个工具 + ToolRegistry
├── context.py      # 上下文构建（含技能注入）
├── runner.py       # AgentRunner 多轮对话
├── loop.py         # AgentLoop 状态机主循环
├── main.py         # 入口 + Provider 工厂
├── skills_loader.py  # SkillsLoader（yaml 解析 + 摘要 + 渐进式加载）
├── channels/       # 通道系统
│   ├── base.py     #   Channel 抽象基类
│   ├── cli.py      #   CLI 通道
│   ├── qq.py       #   QQ 通道
│   ├── manager.py  #   ChannelManager
│   └── __init__.py
└── skills/         # 技能系统（只存放 SKILL.md 技能定义）
    ├── officecli/SKILL.md
    └── tavily-search/SKILL.md
```

## 许可证

MIT
