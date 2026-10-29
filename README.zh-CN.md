# 🐟 FishyBox

> 一个本地优先、端到端加密的 **Prompt 资产管理器**，专为多任务并行的开发者打造。

[English](README.md) · **简体中文**

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)
![Status](https://img.shields.io/badge/Status-Active-success.svg)

---

## 💡 为什么是 FishyBox？

现有工具大多走向两个极端：

- **专业密码管理器（如 1Password）** —— 安全性顶级，但用来整理、渲染带代码块/表格的 AI Prompt 很别扭；
- **通用笔记软件（如 Obsidian）** —— 写东西灵活，但缺少内置的本地加密，且需要装一堆插件。

**FishyBox 是两者的"极客混合体"**：把本地加密保险柜和专用的 Prompt 资产库放在一起。解压即用，无需安装、无需账号、零云端依赖。

而且它专门为**侧边小窗**设计 —— 贴在 IDE、AI 聊天窗口旁边，写代码和查 Prompt 之间不用来回切全屏。

---

## 📸 截图

| 主界面 | Markdown 渲染 |
|---|---|
| ![主界面](docs/img/main-zh.webp) | ![Markdown 渲染](docs/img/markdown-zh.webp) |

| 加密隐私库 | 锁屏状态 |
|---|---|
| ![加密隐私库](docs/img/vault-zh.webp) | ![锁屏状态](docs/img/lock-zh.webp) |

---

## ✨ 功能

| 功能 | 说明 |
|---|---|
| 🪟 **独立桌面窗口** | 无标签页、无地址栏的干净窗口。贴到 VS Code / AI 聊天旁边，切换不打断思路。 |
| 📝 **完整 Markdown** | 表格、代码块、列表、语法高亮，即时渲染。 |
| 🏷️ **标签系统** | 自定义标签、拖拽排序、一键填充。 |
| 🔐 **加密隐私库** | 逐字段加密、主密码保护、空闲自动锁定。 |
| 📋 **智能剪贴板** | 复制密码后可自动清除（默认关闭，时间可配）。 |
| 🌐 **中英双语** | 自动识别浏览器语言。 |
| 💾 **灵活备份** | 导出 Markdown、加密备份隐私库、一键备份整库。 |

---

## 🚀 快速开始

1. 从 [Releases](../../releases) 下载 `FishyBox-v1.0.zip`；
2. 解压到任意文件夹（**避免** `C:\Program Files`，防止权限问题）；
3. 双击 **`FishyBox.bat`** 启动。

> **提示**：Windows Defender 可能对未签名程序弹警告（代码签名证书对独立开发者太贵）。点 **更多信息 → 仍要运行** 即可，或自行从源码编译。

所有数据存在程序同级的 `database/` 文件夹；手动备份存 `backup/`。

---

## 💻 本地开发

```bash
# 1. 克隆仓库
git clone https://github.com/Shenfengyuan08/FishyBox.git
cd FishyBox

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动（服务 + 窗口）
python launcher.py
```

---

## 🛠️ 技术栈

- **后端**：FastAPI + SQLite（标准库 `sqlite3`）
- **前端**：原生 HTML/CSS/JS —— 单文件，零构建
- **打包**：PyInstaller（文件夹模式，更稳定）
- **窗口**：Microsoft Edge `--app` 模式 + 独立配置目录

---

## 🧠 AI 辅助开发

本项目采用**多 AI 协作工作流**，不是"一次提示词复制粘贴"。

**工作流**

1. **定规格** —— 人类开发者定义目标、约束和验收标准；
2. **多 AI 审计** —— 4 个不同大模型独立审计代码、UI、安全和文档；
3. **仲裁** —— 人类对比各家意见，**否决错误建议**，决定采纳哪些；
4. **定稿审核** —— 由最强的模型做最终一致性检查。

**分工**

- **人类开发者**：产品架构、UI 交互设计、安全策略、功能验收、Prompt 工程；
- **AI 助手**：实现、调试、独立审计。

> 在约 15 小时的开发中，我**指出了大量 AI 错误** —— 从 HTML 语法错误、API 误用，到文档里的夸大表述。**AI 写代码，人类抓错误。**

> *本项目的每一个架构决策、安全取舍和交互流程都由人类开发者完成 —— AI 写的是代码，产品是人设计的。*

---

## 🛡️ 安全设计与边界

### 核心安全机制

- **PBKDF2-HMAC-SHA256**，60 万次迭代 → 32 字节密钥；
- **Fernet**（AES-128-CBC + HMAC-SHA256）逐字段加密；
- **密钥只存内存** —— 不落盘，进程退出即销毁；
- **哨兵校验** —— 不存储主密码也能验证；
- **空闲 5 分钟自动锁定**；
- **剪贴板自动清除**（可选，默认关闭）。

> 密码永远不会明文显示在屏幕上，只在你主动点击时复制到剪贴板。

**安全等级：个人开发者级。** 它能扛住"随手翻看、硬盘被偷、身后窥屏"，但**不是**经过审计的企业级密码管理器，**也不适合**存放高价值资产或受监管的数据。

### ⚠️ 免责声明

本项目遵循 OWASP 推荐的加密实践，但请知悉以下边界：

1. **无密码找回** —— 忘记主密码，数据永久无法恢复，没有后门；
2. **无系统级防护** —— 无法抵御木马、键盘记录器、屏幕录制；
3. **备份自理** —— 纯本地存储有磁盘故障风险，强烈建议定期用内置导出功能备份；
4. **未经第三方审计** —— 本项目未经过独立的安全审计；
5. **使用范围** —— 面向**个人开发者使用**。**请勿存放高价值资产（如加密钱包、大额银行凭证）、企业机密或任何国家机密。** 开发者不对数据丢失或滥用承担责任。

---

## 🗺️ 路线图

- [ ] 把 `database/prompts.db` 拆成独立的 `main.db` 和 `vault.db`；
- [ ] 基于 SQLite FTS5 的全文搜索；
- [ ] Prompt 版本历史；
- [ ] 基于本地 embedding 的语义搜索。

---

## 🤝 参与贡献

欢迎提交 Issue 和 PR！

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/AmazingFeature`）
3. 提交改动（`git commit -m 'Add some AmazingFeature'`）
4. 推送到分支（`git push origin feature/AmazingFeature`）
5. 发起 Pull Request

---

## 📄 开源协议

基于 MIT 协议发布，详见 [LICENSE](LICENSE)。
