# Resonance Visual Studio

`Resonance Visual Studio` 是一个基于 `Gradio` 的多模态图像创作与编辑工具，支持文本生图、以图改图、会话档案管理、历史回溯与高清预览，适合个人创作和提示词迭代工作流。

## 功能特性

- 双通道推理：
  - `🎨 标准绘图通道 (自动路由)`：优先走 `images/generations` / `images/edits`
  - `💬 多模态对话通道`：通过对话接口解析图片链接并落盘
- 会话档案系统：
  - 新建 / 切换 / 删除会话
  - 自动保存历史消息、最后底图、预览图
- 历史图片回溯：
  - 点击聊天中的历史图片，快速设为当前高清预览与后续编辑底图
- 配置持久化：
  - 自动保存 `Base URL / API Key / 模型 / 画幅 / 通道`
- 路径稳定性：
  - 统一基于程序所在目录读写配置、会话和输出图片
- 打包友好：
  - 针对 `PyInstaller --windowed` 做了标准输出兜底
  - 内置前端“退出程序”按钮，可关闭后台进程

## 项目结构

```text
.
├─ ui4.1.py                      # 主程序（推荐）
├─ ResonanceUI41.spec            # PyInstaller 专用打包模板
├─ resonance_config.json         # 运行后自动生成（配置）
├─ resonance_sessions.json       # 运行后自动生成（会话）
└─ resonance_outputs/            # 运行后自动生成（图片输出）
```

## 环境要求

- Python `3.10+`（推荐 `3.11/3.12`）
- 操作系统：
  - Windows（当前主要验证环境）
  - macOS（需在 macOS 本机打包）

## 安装与运行

### 1) 创建虚拟环境（推荐）

```bash
python -m venv venv
```

- Windows:

```bash
venv\Scripts\activate
```

- macOS/Linux:

```bash
source venv/bin/activate
```

### 2) 安装依赖

```bash
pip install -U pip
pip install gradio openai pillow fastapi starlette anyio safehttpx groovy
```

### 3) 启动程序

```bash
python ui4.1.py
```

启动后默认打开本地地址（通常是 `http://127.0.0.1:7860`）。

## 使用说明（快速）

1. 在左侧填写 `Base URL` 和 `API Key`
2. 点击 `📡 探测引擎库` 同步模型
3. 选择通道、模型和画幅比例
4. 在输入框输入提示词（可上传参考图）
5. 点击历史图片可切换右侧高清预览并作为下一轮编辑底图
6. 使用 `⏻ 退出程序` 按钮可同时结束前端与后台进程

## 打包为可执行文件（Windows）

### 方式 A：推荐（使用专用 spec）

```bash
pyinstaller --noconfirm --clean ResonanceUI41.spec
```

产物：

- `dist\ResonanceUI41.exe`

### 方式 B：命令行直接打包

```bash
pyinstaller --noconfirm --clean --onefile --windowed --name ResonanceUI41 ui4.1.py --collect-all gradio --collect-all fastapi --collect-all starlette --collect-all anyio --collect-all safehttpx --collect-all groovy
```

## 打包为可执行文件（macOS）

> 注意：不能在 Windows 直接打出可运行的 Mac 可执行文件。  
> 必须在 macOS 本机（或云 Mac）执行打包。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install gradio openai pillow pyinstaller fastapi starlette anyio safehttpx groovy
pyinstaller --noconfirm --clean --windowed --name ResonanceUI41 ui4.1.py --collect-all gradio --collect-all fastapi --collect-all starlette --collect-all anyio --collect-all safehttpx --collect-all groovy
```

产物：

- `dist/ResonanceUI41.app`

## 配置与数据文件

程序运行后会在程序所在目录生成：

- `resonance_config.json`：配置文件
- `resonance_sessions.json`：会话文件
- `resonance_outputs/`：图片输出目录

## 已知问题与排查

### 1) `safehttpx/version.txt` 缺失

现象：

- 启动时报 `FileNotFoundError ... safehttpx/version.txt`

解决：

- 使用 `ResonanceUI41.spec` 打包，或在命令中包含 `--collect-all safehttpx`

### 2) `groovy/version.txt` 缺失

现象：

- 启动时报 `FileNotFoundError ... groovy/version.txt`

解决：

- 使用 `ResonanceUI41.spec` 打包，或在命令中包含 `--collect-all groovy`

### 3) `Unable to configure formatter 'default'`

现象：

- `--windowed` 打包后启动报 `uvicorn logging` 相关错误

原因：

- GUI 模式下 `stdout/stderr` 可能为空

状态：

- 已在 `ui4.1.py` 增加标准输出兜底逻辑

### 4) 端口被占用

现象：

- 程序启动失败或无响应

解决：

- 关闭占用 `7860` 端口的进程，或修改启动端口后重试

### 5) 模型返回非图片内容

现象：

- 提示“模型未返回图片链接”

建议：

- 优先使用支持图像输出的模型
- 调整提示词，明确要求“返回图片链接”

## 安全提示

- 请勿将 `API Key` 提交到公开仓库
- 发布前建议将本地 `resonance_config.json` 从 Git 跟踪中排除（可写入 `.gitignore`）

## 版本建议

- 推荐将后续迭代集中在 `ui4.1.py`
- 发布前先本地验证：
  - 配置保存
  - 会话切换
  - 历史图片回溯
  - 退出程序按钮
  - 打包后冷启动

