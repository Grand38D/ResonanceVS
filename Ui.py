import gradio as gr
import json, os, sys, traceback, urllib.request, urllib.parse, uuid, base64, io, re, datetime, threading, time
from openai import OpenAI
from PIL import Image

def ensure_stdio_for_windowed_mode():
    """
    PyInstaller --windowed 下 stdout/stderr 可能为 None，
    uvicorn/gradio 的日志配置会调用 isatty()，需要兜底流对象。
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

ensure_stdio_for_windowed_mode()

# ================= 1. 目录与配置初始化 =================
def get_app_dir():
    # 打包后使用 exe 所在目录；源码运行时使用当前脚本目录
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()
CONFIG_FILE = os.path.join(APP_DIR, "resonance_config.json")
SESSIONS_FILE = os.path.join(APP_DIR, "resonance_sessions.json")
OUTPUT_DIR = os.path.join(APP_DIR, "resonance_outputs")
SESSIONS_LOCK = threading.RLock()
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 🌅 v18.1 晨曦柔和版 CSS 
CUSTOM_CSS = """
.gradio-container { background-color: #f1f5f9 !important; color: #334155 !important; font-family: 'Segoe UI', system-ui, sans-serif !important; }
footer { display: none !important; }
.res-card { background-color: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 16px !important; padding: 20px !important; margin-bottom: 15px !important; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05) !important; }
input[type="text"], input[type="password"], textarea, .dropdown-container { background-color: #ffffff !important; color: #1e293b !important; border: 1px solid #cbd5e1 !important; }
#chatbot-container { background-color: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 20px !important; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05) !important; }
.message.user { background-color: #dbeafe !important; color: #1e40af !important; border-radius: 16px 16px 4px 16px !important; border: 1px solid #bfdbfe !important; }
.message.bot { background-color: #f8fafc !important; color: #475569 !important; border: 1px solid #f1f5f9 !important; border-radius: 16px 16px 16px 4px !important; }
#chat-input-container { background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 16px !important; box-shadow: 0 4px 12px rgba(0,0,0,0.05) !important; }
#chat-input-container textarea { min-height: 48px !important; padding-top: 12px !important; }
#chat-input-container .block-label { display: none !important; }
.status-badge { background: #f0fdf4 !important; color: #166534 !important; border: 1px solid #bbf7d0 !important; padding: 6px 14px; border-radius: 8px; font-weight: 600; font-family: monospace; margin-top: 8px; display: inline-block; }
.error-badge { background: #fef2f2 !important; color: #b91c1c !important; border: 1px solid #fecaca !important; padding: 6px 14px; border-radius: 8px; font-weight: 600; font-family: monospace; margin-top: 8px; display: inline-block; }
.warning-badge { background: #fffbeb !important; color: #b45309 !important; border: 1px solid #fde68a !important; padding: 6px 14px; border-radius: 8px; font-weight: 600; font-family: monospace; margin-top: 8px; display: inline-block; }
.image-preview-area { background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 20px !important; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.05) !important; }
h1 { color: #1e293b !important; font-weight: 800 !important; }
.res-row-btns { display: flex; gap: 10px; margin-top: 10px; }
.res-row-btns button { flex: 1; }
"""

def sanitize_input(text):
    return ''.join(char for char in text.strip() if ord(char) < 128) if text else ""

def make_text_message(role, text):
    return {"role": role, "content": text}

def make_image_message(role, img_path):
    return {"role": role, "content": {"path": img_path}}

def format_error_message(prefix, err):
    return f"{prefix}{err.__class__.__name__}: {str(err)}"

def get_data_dir_notice_text():
    return f"<div class='status-badge'>📁 当前数据目录: {APP_DIR}</div>"

def get_data_dir_notice_message():
    return make_text_message("assistant", get_data_dir_notice_text())

def get_data_dir_notice_serialized():
    return {"role": "assistant", "content": get_data_dir_notice_text(), "type": "text"}

def shutdown_app_logic(history):
    history = history or []
    history.append(make_text_message("assistant", "<div class='warning-badge'>⏻ 程序已经退出,请关闭当前浏览器窗口...</div>"))

    def _delayed_exit():
        time.sleep(0.3)
        os._exit(0)

    threading.Thread(target=_delayed_exit, daemon=True).start()
    return history

# ================= 2. 核心架构：无损档案记忆系统 =================

def load_config():
    cfg = {"base_url": "", "api_key": "", "model_name": "", "size": "1024x1024 (1:1 标准)", "engine_type": "🎨 标准绘图通道 (自动路由)"}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: cfg.update(json.load(f))
        except: pass
    return cfg

def normalize_engine_type(engine_type):
    # 兼容旧配置文案，避免 Radio value 不在 choices 里导致报错
    if engine_type == "💬 多模态对话通道 (针对 Gemini)":
        return "💬 多模态对话通道 (针对 Gemini/Grok-3-image)"
    return engine_type

def save_config(base_url, api_key, model_name, size, engine_type):
    engine_type = normalize_engine_type(engine_type)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"base_url": base_url, "api_key": api_key, "model_name": model_name, "size": size, "engine_type": engine_type}, f, indent=2)

def load_sessions_data():
    with SESSIONS_LOCK:
        if os.path.exists(SESSIONS_FILE):
            try:
                with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 启动时自动修复旧会话中的临时缓存路径
                changed = False
                for sid, session in data.items():
                    hist = session.get("history", [])
                    for msg in hist:
                        if msg.get("type") == "image":
                            fixed = extract_image_path(msg.get("content"))
                            if fixed and fixed != msg.get("content"):
                                msg["content"] = fixed
                                changed = True
                    for key in ("last_img", "preview"):
                        fixed = extract_image_path(session.get(key))
                        if fixed and fixed != session.get(key):
                            session[key] = fixed
                            changed = True
                if changed:
                    save_sessions_data(data)
                return data
            except:
                pass
        return {}

def save_sessions_data(data):
    with SESSIONS_LOCK:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def update_sessions_data(mutator):
    """原子化更新会话文件，避免并发读写覆盖。"""
    with SESSIONS_LOCK:
        data = {}
        if os.path.exists(SESSIONS_FILE):
            try:
                with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except:
                data = {}
        mutator(data)
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return data

def resolve_image_candidate(path_str):
    """将候选路径解析为可用本地文件，优先回到 resonance_outputs 的持久文件。"""
    if not isinstance(path_str, str) or not path_str:
        return None

    candidate = path_str.strip()
    if candidate.startswith("/gradio_api/file="):
        candidate = urllib.parse.unquote(candidate.split("=", 1)[1])

    if os.path.exists(candidate):
        return os.path.abspath(candidate)

    # Temp/gradio 缓存可能过期，回退到持久输出目录同名文件
    base = os.path.basename(candidate)
    if base:
        stable = os.path.abspath(os.path.join(OUTPUT_DIR, base))
        if os.path.exists(stable):
            return stable
    return None

def extract_image_path(content):
    """从多种 Gradio 消息格式中提取本地图片路径。"""
    if isinstance(content, str):
        return resolve_image_candidate(content)
    if isinstance(content, dict):
        # 先尝试常见键的递归解析
        for key in ("path", "value", "url", "image"):
            if key in content:
                p = extract_image_path(content.get(key))
                if p:
                    return p
        # 兜底：orig_name 可还原到输出目录
        orig_name = content.get("orig_name")
        if isinstance(orig_name, str) and orig_name:
            p = resolve_image_candidate(os.path.join(OUTPUT_DIR, orig_name))
            if p:
                return p
        return None
    if hasattr(content, "value"):
        return extract_image_path(content.value)
    if isinstance(content, (list, tuple)) and content:
        return extract_image_path(content[0])
    return None

def serialize_history(history):
    """【核心修复】：将对话记录无损序列化，安全脱壳图片对象"""
    s_hist =[]
    for msg in history:
        role = msg.get("role")
        content = msg.get("content")
        img_path = extract_image_path(content)
        
        if img_path:
            s_hist.append({"role": role, "content": img_path, "type": "image"})
        elif isinstance(content, str):
            s_hist.append({"role": role, "content": content, "type": "text"})
        else:
            s_hist.append({"role": role, "content": str(content), "type": "text"})
    return s_hist

def deserialize_history(s_hist):
    """将 JSON 里的路径还原为 Chatbot 可序列化的图片消息。"""
    history =[]
    for msg in s_hist:
        role = msg.get("role")
        content = msg.get("content")
        msg_type = msg.get("type", "text")
        
        if msg_type == "image":
            img_path = extract_image_path(content)
            if img_path:
                # Chatbot 历史消息必须是可 deepcopy 的简单结构
                history.append(make_image_message(role, img_path))
            else:
                history.append(make_text_message(role, f"[图片不可用] {content}"))
        else:
            history.append(make_text_message(role, content))
    return history

def create_new_session_logic():
    data = load_sessions_data()
    session_id = uuid.uuid4().hex[:8]
    name = datetime.datetime.now().strftime("档案 %m-%d %H:%M")
    data[session_id] = {"name": name, "history":[get_data_dir_notice_serialized()], "last_img": None, "preview": None}
    save_sessions_data(data)
    choices = [(v["name"], k) for k, v in data.items()][::-1]
    return gr.update(choices=choices, value=session_id), session_id,[get_data_dir_notice_message()], None, None

def switch_session_logic(session_id):
    if not session_id: return gr.update(),[], None, None
    data = load_sessions_data()
    if session_id not in data: return gr.update(), [], None, None
    session = data[session_id]
    history = deserialize_history(session.get("history",[]))
    if not history:
        history = [get_data_dir_notice_message()]
    last_img = session.get("last_img")
    preview = session.get("preview")
    return session_id, history, last_img, preview

def delete_session_logic(session_id):
    data = load_sessions_data()
    if session_id in data:
        del data[session_id]
        save_sessions_data(data)
    choices = [(v["name"], k) for k, v in data.items()][::-1]
    if not choices:
        return create_new_session_logic()
    else:
        next_id = choices[0][1]
        sid, hist, img, prev = switch_session_logic(next_id)
        return gr.update(choices=choices, value=next_id), sid, hist, img, prev

# ================= 3. 图像防变形与 API 调度 =================

def prepare_image_for_edit_v2(image_path, target_size_str):
    try: t_w, t_h = map(int, target_size_str.split('x'))
    except: t_w, t_h = 1024, 1024
    img = Image.open(image_path).convert("RGBA")
    src_w, src_h = img.size
    ratio = min(t_w / src_w, t_h / src_h)
    new_w, new_h = int(src_w * ratio), int(src_h * ratio)
    resized_img = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (t_w, t_h), (0, 0, 0, 0))
    canvas.paste(resized_img, ((t_w - new_w) // 2, (t_h - new_h) // 2), resized_img)
    byte_io = io.BytesIO()
    canvas.save(byte_io, format="PNG")
    return byte_io.getvalue()

def parse_image_src_from_ai_text(ai_text):
    """从多模态文本回复中提取图片链接或 data URL。"""
    md_match = re.search(r'!\[.*?\]\((.*?)\)', ai_text or "")
    if md_match:
        return md_match.group(1).strip('()\"\' ')
    url_match = re.search(r'(https?://\S+|data:image/\S+)', ai_text or "")
    if url_match:
        return url_match.group(0).strip('()\"\' ')
    raise ValueError(f"模型未返回图片链接，原生回复为：\n\n{ai_text}")

def fetch_remote_models(base_url, api_key, history):
    base_url = sanitize_input(base_url).rstrip('/')
    api_key = sanitize_input(api_key)
    if not base_url or not api_key:
        history.append(make_text_message("assistant", "<div class='error-badge'>❌ 缺少网络凭证</div>"))
        return gr.update(), history
    try:
        req = urllib.request.Request(f"{base_url}/models")
        req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            model_ids = sorted([m['id'] for m in data.get('data',[])])
        history.append(make_text_message("assistant", "<div class='status-badge'>✅ 探测成功！引擎列表已同步。</div>"))
        return gr.update(choices=model_ids), history
    except Exception as e:
        history.append(make_text_message("assistant", f"<div class='error-badge'>❌ {format_error_message('探测失败: ', e)}</div>"))
        return gr.update(), history

def handle_image_selection_v4(evt: gr.SelectData, history, current_session_id):
    img_path = extract_image_path(getattr(evt, "value", None))
    
    if not img_path:
        try:
            msg_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
            content = history[msg_idx].get("content")
            img_path = extract_image_path(content)
        except: pass

    if img_path and os.path.exists(img_path):
        def _mutate(data):
            if current_session_id in data:
                data[current_session_id]["last_img"] = img_path
                data[current_session_id]["preview"] = img_path
        update_sessions_data(_mutate)
        return img_path, img_path
    
    return gr.update(), gr.update()

def resonance_chat_engine(user_input, history, engine_type, model_name, size_label, base_url, api_key, last_img_state, current_session_id):
    prompt = user_input.get("text", "")
    upload_files = user_input.get("files",[])
    base_url = sanitize_input(base_url).rstrip('/')
    api_key = sanitize_input(api_key)
    engine_type = normalize_engine_type(engine_type)
    
    if not base_url or not api_key:
        history.append(make_text_message("assistant", "<div class='error-badge'>⚠️ 请在左侧填写 API 凭证。</div>"))
        return {"text": "", "files":[]}, history, gr.update(), last_img_state, gr.update()

    actual_size = size_label.split(' ')[0] if ' ' in size_label else size_label
    save_config(base_url, api_key, model_name, size_label, engine_type)
    client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
    current_image_path = extract_image_path(upload_files[0]) if upload_files else extract_image_path(last_img_state)
    
    # 构建 UI 回显（使用可序列化图片结构，避免组件对象进入历史）
    if upload_files:
        upload_path = extract_image_path(upload_files[0]) if isinstance(upload_files[0], (dict, list, tuple)) else upload_files[0]
        if upload_path:
            history.append(make_image_message("user", upload_path))
        history.append(make_text_message("user", f"🎯 修改指令: {prompt}"))
    else:
        history.append(make_text_message("user", prompt))

    try:
        img_src = ""
        route_log = ""
        is_standard_api = "标准绘图" in engine_type

        if is_standard_api:
            if current_image_path:
                img_payload = prepare_image_for_edit_v2(current_image_path, actual_size)
                res = client.images.edit(model=model_name, image=img_payload, prompt=prompt, n=1, size=actual_size)
                img_src = res.data[0].url or res.data[0].b64_json
                route_log = "API: /v1/images/edits (修改模式)"
            else:
                res = client.images.generate(model=model_name, prompt=prompt, n=1, size=actual_size)
                img_src = res.data[0].url or res.data[0].b64_json
                route_log = "API: /v1/images/generations (生图模式)"
        else:
            content =[{"type": "text", "text": f"请执行视觉任务:\n{prompt}\n输出分辨率: {actual_size}。必须返回图片链接。"}]
            if current_image_path:
                with open(current_image_path, "rb") as img_file:
                    img_b64 = base64.b64encode(img_file.read()).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
            res = client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": content}])
            ai_text = res.choices[0].message.content
            img_src = parse_image_src_from_ai_text(ai_text)
            route_log = "API: /v1/chat/completions (对话模式)"

        # 物理具现化
        local_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"res_{uuid.uuid4().hex[:8]}.png"))
        if img_src.startswith("http"):
            req = urllib.request.Request(img_src, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r, open(local_path, 'wb') as f: f.write(r.read())
        else:
            b64_c = img_src.split("base64,")[1] if "base64," in img_src else img_src
            with open(local_path, "wb") as f: f.write(base64.b64decode(b64_c))
        
        # 注入可序列化的图像消息
        history.append(make_image_message("assistant", local_path))
        status_html = f"<div class='status-badge'>📡 {route_log} | 🧠 锚定: {os.path.basename(local_path)[:10]}...</div>"
        history.append(make_text_message("assistant", status_html))
        
        # 存入档案库
        def _mutate(data):
            if current_session_id in data:
                if len(history) <= 4 and prompt:
                    short_name = (prompt[:12] + "..") if len(prompt) > 12 else prompt
                    data[current_session_id]["name"] = f"[{short_name}]"
                data[current_session_id]["history"] = serialize_history(history)
                data[current_session_id]["last_img"] = local_path
                data[current_session_id]["preview"] = local_path
        data = update_sessions_data(_mutate)
        
        choices = [(v["name"], k) for k, v in data.items()][::-1]
        return {"text": "", "files":[]}, history, local_path, local_path, gr.update(choices=choices, value=current_session_id)
        
    except Exception as e:
        history.append(make_text_message("assistant", f"<div class='error-badge'>❌ {format_error_message('任务失败: ', e)}</div>"))
        return {"text": "", "files":[]}, history, gr.update(), last_img_state, gr.update()

# ================= 4. 初始化档案数据 =================

init_data = load_sessions_data()
if not init_data:
    sid = uuid.uuid4().hex[:8]
    init_data[sid] = {"name": "初始视界", "history":[get_data_dir_notice_serialized()], "last_img": None, "preview": None}
    save_sessions_data(init_data)

init_choices = [(v["name"], k) for k, v in init_data.items()][::-1]
init_session_id = init_choices[0][1]
init_session = init_data[init_session_id]
if not init_session.get("history"):
    init_session["history"] = [get_data_dir_notice_serialized()]

# ================= 5. UI 界面布局 =================
cfg = load_config()
original_engine_type = cfg.get("engine_type", "🎨 标准绘图通道 (自动路由)")
cfg["engine_type"] = normalize_engine_type(original_engine_type)

ENGINE_TYPE_CHOICES = [
    "🎨 标准绘图通道 (自动路由)",
    "💬 多模态对话通道 (针对 Gemini/Grok-3-image)",
]
if cfg["engine_type"] not in ENGINE_TYPE_CHOICES:
    cfg["engine_type"] = "🎨 标准绘图通道 (自动路由)"
if cfg["engine_type"] != original_engine_type:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

SIZE_MATRIX =[
    "1024x1024 (1:1 标准)", "2048x2048 (1:1 2K)", "4096x4096 (1:1 4K)", 
    "1792x1024 (16:9 宽屏)", "3840x2160 (16:9 4K)", 
    "1024x1792 (9:16 竖屏)", "2160x3840 (9:16 4K)"
]

with gr.Blocks() as demo:
    current_session_id = gr.State(init_session_id)
    last_img_memory = gr.State(init_session.get("last_img"))

    gr.HTML("<h1 style='color: #1e293b; padding: 15px 0 5px 10px;'>🌌 Resonance Visual Studio</h1>")

    with gr.Row():
        with gr.Column(scale=1):
            
            with gr.Group(elem_classes="res-card"):
                gr.Markdown("#### 📂 历史档案 (Archives)")
                session_selector = gr.Dropdown(choices=init_choices, value=init_session_id, show_label=False, interactive=True)
                with gr.Row(elem_classes="res-row-btns"):
                    new_session_btn = gr.Button("✨ 新建档", variant="primary")
                    del_session_btn = gr.Button("🗑️ 删当前档", variant="stop")
                exit_app_btn = gr.Button("⏻ 退出程序", variant="secondary")

            with gr.Group(elem_classes="res-card"):
                gr.Markdown("#### 🔌 链路协议 (非常重要)")
                engine_type_in = gr.Radio(choices=ENGINE_TYPE_CHOICES, label=None, show_label=False, value=cfg["engine_type"])
                with gr.Accordion("⚙️ API 凭证", open=False):
                    base_url_in = gr.Textbox(label="Base URL", value=cfg.get("base_url", ""))
                    api_key_in = gr.Textbox(label="API Key", type="password", value=cfg.get("api_key", ""))
                fetch_btn = gr.Button("📡 探测引擎库", variant="secondary")
            
            with gr.Group(elem_classes="res-card"):
                gr.Markdown("#### 🎨 创作规格")
                model_name_in = gr.Dropdown(label="视觉引擎", choices=[cfg.get("model_name", "")], value=cfg.get("model_name", ""), allow_custom_value=True)
                size_in = gr.Dropdown(label="画幅比例", choices=SIZE_MATRIX, value=cfg.get("size", "1024x1024 (1:1 标准)"), allow_custom_value=True)
            
        with gr.Column(scale=2):
            chatbot_ui = gr.Chatbot(
                value=deserialize_history(init_session.get("history",[])),
                label=None, show_label=False, height=680, elem_id="chatbot-container"
            )
            chat_input_ui = gr.MultimodalTextbox(
                label=None, show_label=False, placeholder="指令回车点火...", file_types=["image"], elem_id="chat-input-container", lines=1, max_lines=5
            )

        with gr.Column(scale=2):
            gr.Markdown("<h4 style='color: #64748b;'>🔍 高清聚焦</h4>")
            master_preview = gr.Image(
                value=init_session.get("preview"),
                label=None, show_label=False, height=680, interactive=False, elem_classes="image-preview-area"
            )

    # ============ 事件绑定 ============
    
    new_session_btn.click(fn=create_new_session_logic, outputs=[session_selector, current_session_id, chatbot_ui, master_preview, last_img_memory])
    session_selector.change(fn=switch_session_logic, inputs=[session_selector], outputs=[current_session_id, chatbot_ui, last_img_memory, master_preview])
    del_session_btn.click(fn=delete_session_logic, inputs=[current_session_id], outputs=[session_selector, current_session_id, chatbot_ui, last_img_memory, master_preview])
    exit_app_btn.click(fn=shutdown_app_logic, inputs=[chatbot_ui], outputs=[chatbot_ui])

    # 修复探测引擎清空记录的问题：将 chatbot 传入并在原记录后追加提示
    fetch_btn.click(fn=fetch_remote_models, inputs=[base_url_in, api_key_in, chatbot_ui], outputs=[model_name_in, chatbot_ui])
    
    chatbot_ui.select(fn=handle_image_selection_v4, inputs=[chatbot_ui, current_session_id], outputs=[master_preview, last_img_memory])
    
    chat_input_ui.submit(fn=resonance_chat_engine, inputs=[chat_input_ui, chatbot_ui, engine_type_in, model_name_in, size_in, base_url_in, api_key_in, last_img_memory, current_session_id], outputs=[chat_input_ui, chatbot_ui, master_preview, last_img_memory, session_selector])

if __name__ == "__main__":
    # CSS 和 Theme 在此安全挂载
    demo.launch(server_name="127.0.0.1", inbrowser=True, css=CUSTOM_CSS, theme=gr.themes.Monochrome())
