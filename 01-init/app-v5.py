import streamlit as st
import time
import random

# ==========================================
# 0. 全局视窗配置与极客暗黑主题劫持
# ==========================================
st.set_page_config(
    page_title="inFlow / Cogno 资产大脑控制中心",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 强力注入定制 CSS，将 Streamlit 侧边栏全面重塑为 SaaS 级经典左导航，并保留 3D 卡片美学
st.markdown("""
<style>
    /* 劫持全局底色 */
    .stApp {
        background-color: #0b0f19 !important;
        color: #cbd5e1 !important;
    }
    
    /* 侧边栏常驻左导航菜单区域样式重写 */
    section[data-testid="stSidebar"] {
        background-color: #0d1527 !important;
        border-right: 1px solid #1e293b !important;
        width: 320px !important;
    }
    
    /* 强力改造右侧 Streamlit 的 border container 变成高级 3D 悬浮卡片 */
    div[data-testid="stVerticalBlockBorderReady"] {
        background: linear-gradient(145deg, #111827, #0b132b) !important;
        border: 1px solid #1f293d !important;
        border-radius: 16px !important;
        padding: 22px !important;
        transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5) !important;
    }
    
    /* 鼠标 Hover 卡片形变与发光特效 - 完美复刻 aa-v2.html 心智 */
    div[data-testid="stVerticalBlockBorderReady"]:hover {
        transform: translateY(-5px) scale(1.01) !important;
        border-color: #3b82f6 !important;
        box-shadow: 0 10px 30px rgba(59, 130, 246, 0.2) !important;
    }
    
    /* 音频波形跳跃动效 */
    .waveform-bar {
        display: inline-block;
        width: 3px;
        background-color: #38bdf8;
        margin-right: 2px;
        border-radius: 2px;
        animation: bounce 0.8s infinite alternate;
    }
    @keyframes bounce {
        0% { height: 4px; }
        100% { height: 22px; }
    }
    
    /* 极客玻璃微章 */
    .glass-badge {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-family: monospace;
        color: #94a3b8;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 内存动态模拟数据库初始化
# ==========================================
if 'speaker_mappings' not in st.session_state:
    st.session_state.speaker_mappings = {"Speaker_0": "主持小张", "Speaker_1": "嘉宾李教授"}
if 'book_rolled' not in st.session_state:
    st.session_state.book_rolled = False
if 'current_book' not in st.session_state:
    st.session_state.current_book = {}

MOCK_BOOKS_DB = [
    {"id": "b1", "title": "《失控》", "author": "凯文·凯利", "format": "EPUB", "size": "4.2MB", "status": "🟢 已归仓", "age": "🧒 儿童安全", "intro": "系统自我演化启示录。"},
    {"id": "b2", "title": "《黑客与画家》", "author": "保罗·格雷厄姆", "format": "EPUB", "size": "1.8MB", "status": "🟢 已归仓", "age": "🧒 儿童安全", "intro": "硅谷极客自由创作者宣言。"},
    {"id": "b3", "title": "《当下的力量》", "author": "埃克哈特·托利", "format": "PDF", "size": "2.1MB", "status": "🟡 待校对", "age": "🔞 成人限制", "intro": "粉碎心理内耗与多维焦虑的内在指南。"},
    {"id": "b4", "title": "《大明王朝1566排版集》", "author": "刘和平", "format": "MOBI", "size": "12.5MB", "status": "🔴 原始", "age": "⏳ 未审计", "intro": "高密度硬核历史政治小说，亟待AI多维打标。"}
]

MOCK_PODCASTS_DB = [
    {"id": "p1", "title": "乱翻书 Vol.83：大厂做不对硬件的隐秘核心", "show": "乱翻书", "time": "84 分钟", "status": "🟢 转录完成"},
    {"id": "p2", "title": "知行小酒馆 E64：普通人如何安全配置第一份资产", "show": "知行小酒馆", "time": "58 分钟", "status": "🟢 转录完成"},
    {"id": "p3", "title": "声东击西 Vol.210：硅谷AI淘金热下的真实生态", "show": "声东击西", "time": "125 分钟", "status": "🟡 抽取中(72%)"},
    {"id": "p4", "title": "疯投圈 Vol.50：消费品行业的下半场突围战", "show": "疯投圈", "time": "72 分钟", "status": "🔴 纯音频"}
]

MOCK_VIDEOS_DB = [
    {"id": "v1", "title": "BBC.人类星球.Human.Planet.Ep01.mkv", "source": "家庭 NAS", "size": "4.2GB", "chapters": "🟢 已拆分 12 章节"},
    {"id": "v2", "title": "陆奇最新公开课：大模型时代的创业机会.mp4", "source": "本地下载", "size": "850MB", "chapters": "🔴 未分离视频轨"}
]

# ==========================================
# 2. 【左侧常驻导航菜单栏 (Sidebar Menu)】
# ==========================================
with st.sidebar:
    st.markdown("<h2 style='color:#3b82f6;'>🧠 inFlow / Cogno</h2>", unsafe_allow_html=True)
    st.caption("v2.0.0 · 个人数字资产控制塔")
    st.markdown("---")
    
    # 核心经典左侧垂直路由选择器
    menu_selection = st.radio(
        "导航菜单控制轴",
        ["📊 大盘数据总览", "🗂️ 中央数字藏馆", "⚡ 流水线控制塔", "🛠️ 人机协同控制舱", "🎲 资产多维激活原力"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    st.markdown("### 📡 基础设施网关")
    st.success("● Calibre SQLite: 已挂载")
    st.success("● Audiobookshelf: 已联通")
    st.success("● Jellyfin Proxy: 正常")
    
    st.markdown("---")
    st.caption("💡 架构说明：左侧导航状态常驻，右侧视窗动态响应，避免页面刷新带来的卡顿。")

# ==========================================
# 3. 【右侧动态内容画布区 (Main Content Canvas)】
# ==========================================

# ------------------------------------------
# 菜单 1：📊 大盘数据总览
# ------------------------------------------
if menu_selection == "📊 大盘数据总览":
    st.header("📊 数字化资产大盘智能总览")
    st.caption("实时监控资产大盘储量与 AI 能力层的硬件开销指标。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 顶置核心高燃 Telemetry 指标
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(label="📚 Calibre 标准书量", value="102,481 册", delta="+12 册 (今日)")
    m2.metric(label="🎙️ 播客全量文本底座", value="482 小时", delta="Groq LPU 加速")
    m3.metric(label="🎬 视频切片追踪章节", value="142 个章节")
    m4.metric(label="💰 今日 AI 算力开销", value="$0.58", delta="-15% 极速并发")
    
    st.markdown("<br><h3>🔄 快捷宏控制中心</h3>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("##### ⚡ 极客跨端自动化 Webhook 联推")
        st.write("点击下方核心宏按钮，系统将自动向后台调度执行对应的资产清洗管道集群任务。")
        col_macro1, col_macro2 = st.columns(2)
        if col_macro1.button("🔥 触发夜间批处理：全量电子书年龄智能分级打标", use_container_width=True):
            st.toast("已成功向控制台推送电子书打标流水线任务！")
        if col_macro2.button("🎵 一键触发：对未转录播客音频启动 Groq Whisper 编译", use_container_width=True):
            st.toast("已唤醒 Groq 极速 STT 引擎集群！")

# ------------------------------------------
# 菜单 2：🗂️ 中央数字藏馆 (核心视觉画廊)
# ------------------------------------------
elif menu_selection == "🗂️ 中央数字藏馆":
    st.header("🗂️ 跨模态资产中央画廊视窗")
    st.caption("基于高级 CSS 卡片劫持排版，彻底告别传统冷冰冰的表格数据展示。")
    
    # 检索条
    search_query = st.text_input("🔍 输入灵感关键词或作者进行全球跨模态高密度智能检索...", "", key="main_vault_search")
    
    v_tab_b, v_tab_p, v_tab_v = st.tabs(["📚 3D立体书架", "🎙️ 播客声纹声学墙", "🎬 影院级公开课"])
    
    # 2.1 3D立体书架卡片流
    with v_tab_b:
        st.markdown("<br>", unsafe_allow_html=True)
        grid_b1, grid_b2 = st.columns(2)
        for idx, book in enumerate(MOCK_BOOKS_DB):
            if search_query.lower() not in book["title"].lower() and search_query.lower() not in book["author"].lower():
                continue
            target_grid = grid_b1 if idx % 2 == 0 else grid_b2
            with target_grid:
                with st.container(border=True):
                    head1, head2 = st.columns([3, 1])
                    head1.markdown(f"### {book['title']}")
                    if "🟢" in book["status"]:
                        head2.markdown(f"<span style='color:#10b981; font-weight:bold;'>{book['status']}</span>", unsafe_allow_html=True)
                    else:
                        head2.markdown(f"<span style='color:#f59e0b; font-weight:bold;'>{book['status']}</span>", unsafe_allow_html=True)
                    
                    st.markdown(f"**作者：** `{book['author']}` | *{book['intro']}*")
                    st.markdown(f"<span class='glass-badge'>{book['format']}</span> &nbsp; <span class='glass-badge'>{book['size']}</span> &nbsp; <span class='glass-badge'>{book['age']}</span>", unsafe_allow_html=True)
                    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                    
                    act1, act2 = st.columns(2)
                    act1.button("👁️ 阅览AI安利卡", key=f"v_book_pre_{book['id']}", use_container_width=True)
                    act2.button("📌 同步至 Obsidian", key=f"v_book_ob_{book['id']}", use_container_width=True)

    # 2.2 播客声纹波形墙
    with v_tab_p:
        st.markdown("<br>", unsafe_allow_html=True)
        grid_p1, grid_p2 = st.columns(2)
        for idx, pod in enumerate(MOCK_PODCASTS_DB):
            if search_query.lower() not in pod["title"].lower():
                continue
            target_grid = grid_p1 if idx % 2 == 0 else grid_p2
            with target_grid:
                with st.container(border=True):
                    p_head1, p_head2 = st.columns([4, 1])
                    with p_head1:
                        st.markdown(f"#### {pod['title']}")
                        st.caption(f"📻 {pod['show']}  |  ⏱️  {pod['time']}")
                    with p_head2:
                        wave_html = f"""
                        <div style='display:flex; align-items:flex-end; height:24px; justify-content:flex-end;'>
                            <div class='waveform-bar' style='animation-delay:0.1s; height:10px;'></div>
                            <div class='waveform-bar' style='animation-delay:0.3s; height:20px;'></div>
                            <div class='waveform-bar' style='animation-delay:0.5s; height:14px;'></div>
                        </div>
                        """
                        st.markdown(wave_html, unsafe_allow_html=True)
                    st.markdown("---")
                    p_act1, p_act2 = st.columns(2)
                    if "🔴" in pod["status"]:
                        p_act1.button("⚡ Groq 极速转录", key=f"v_pod_g_{pod['id']}", type="primary", use_container_width=True)
                    else:
                        p_act1.button("🔊 声音锚点交互页", key=f"v_pod_h5_{pod['id']}", use_container_width=True)
                    p_act2.button("👥 校对多人声纹", key=f"v_pod_hitl_{pod['id']}", use_container_width=True)

    # 2.3 视频影院公开课卡片
    with v_tab_v:
        st.markdown("<br>", unsafe_allow_html=True)
        for vid in MOCK_VIDEOS_DB:
            if search_query.lower() not in vid["title"].lower():
                continue
            with st.container(border=True):
                v_col_img, v_col_info = st.columns([1, 2])
                with v_col_img:
                    st.markdown(f"""
                    <div style='background:linear-gradient(135deg, #1e293b, #0f172a); border-radius:10px; height:110px; display:flex; justify-content:center; align-items:center; border:1px dashed #334155;'>
                        <span style='font-size:32px;'>🎬</span>
                    </div>
                    """, unsafe_allow_html=True)
                with v_col_info:
                    st.markdown(f"#### {vid['title']}")
                    st.write(f"🧬 **AI大模型章节深度切片：** `{vid['chapters']}`")
                    v_act1, v_act2 = st.columns(2)
                    v_act1.button("✂️ FFmpeg 离线剥离音轨", key=f"v_vid_ff_{vid['id']}", use_container_width=True)
                    v_act2.button("🔗 Plex / Jellyfin 深度跳转", key=f"v_vid_link_{vid['id']}", use_container_width=True)

# ------------------------------------------
# 菜单 3：⚡ 流水线控制塔
# ------------------------------------------
elif menu_selection == "⚡ 流水线控制塔":
    st.header("⚡ 异步任务清洗流核心管道控制台")
    st.caption("查看和强行熔断正在后台跑的任务集群队列。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    with st.container(border=True):
        col_pipe1, col_pipe2, col_pipe3 = st.columns([2, 5, 1])
        col_pipe1.write("🎙️ **[播客处理中]** 乱翻书 Vol.102.mp3")
        col_pipe2.progress(72, text="Groq Whisper 极速引擎并行提取 Word-level 时间戳 json (72%)...")
        if col_pipe3.button("强行熔断", key="btn_abort_main_pipe"):
            st.error("执行管道已被紧急挂起")

# ------------------------------------------
# 菜单 4：🛠️ 人机协同控制舱
# ------------------------------------------
elif menu_selection == "🛠️ 人机协同控制舱":
    st.header("🛠️ 人机协同控制舱")
    st.caption("AI 负责 95% 的自动化清洗，您负责 5% 的终审校对，防止脏数据污染 Obsidian 双链结构。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_hitl_l, col_hitl_r = st.columns(2)
    with col_hitl_l:
        with st.container(border=True):
            st.markdown("##### 👤 角色声纹快捷修正一键映射表")
            in_spk0 = st.text_input("AI 根据上下文推断 [Speaker_0] ──► 替换为：", value=st.session_state.speaker_mappings["Speaker_0"])
            in_spk1 = st.text_input("AI 根据上下文推断 [Speaker_1] ──► 替换为：", value=st.session_state.speaker_mappings["Speaker_1"])
            if st.button("💾 执行全本替换并交付归仓", type="primary", use_container_width=True):
                st.session_state.speaker_mappings["Speaker_0"] = in_spk0
                st.session_state.speaker_mappings["Speaker_1"] = in_spk1
                st.success("声纹替换完成！已经重新编译文本底座。")
                
    with col_hitl_r:
        with st.container(border=True):
            st.markdown("##### 🔍 Obsidian 三轨并行结构文本底座预览")
            st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_0']} 00:01:12]**：欢迎收听本期对谈，今天我们聊聊人工智能如何落地。")
            st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_1']} 00:01:45]**：其实让前端不仅能看表格，还能以发光卡片这种惊喜形态呈现，才是好产品的核心。")

# ------------------------------------------
# 菜单 5：🎲 资产多维激活原力
# ------------------------------------------
elif menu_selection == "🎲 资产多维激活原力":
    st.header("🎲 沉睡资产激活原力场")
    st.caption("打破选择瘫痪，激活您的阅读热情与社交分享冲动。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_act_l, col_act_r = st.columns([1, 1])
    
    # 5.1 盲盒机制
    with col_act_l:
        st.markdown("### 🔮 电子书随机抽取激活盲盒")
        if st.button("🎰 摇一摇！打破选择瘫痪", type="primary", use_container_width=True, key="btn_vault_roll"):
            st.session_state.current_book = random.choice(MOCK_BOOKS_DB)
            raw_intro = st.session_state.current_book['intro']
            raw_age = st.session_state.current_book['age']
            st.session_state.current_book['ai_vibe'] = f"🔥 一句话击中：{raw_intro}\n\n💡 智能分级：`{raw_age}`\n\n🪝 悬念钩子：打开 Obsidian，顺着思想脉络探索未知的神经双链系统。"
            st.session_state.book_rolled = True
            
        if st.session_state.book_rolled:
            st.markdown(f"## 📖 今日抽取经典：{st.session_state.current_book['title']}")
            st.info(st.session_state.current_book['ai_vibe'])
            if st.button("📌 投递卡片至今日 Obsidian 盲盒笔记", use_container_width=True):
                st.toast("写入 Vault 成功！")

    # 5.2 社交媒体引流长图
    with col_act_r:
        st.markdown("### 🖼️ 爆款引流高燃长图实时分发")
        podcast_title = st.text_input("长图标题联动绑定", value="乱翻书 Vol.83：大厂做不对硬件的隐秘核心", key="p_title_v2")
        hook_text = st.text_area("高燃爆款悬念配置", value="1. 为什么雷军说做硬件必须有“亏死五个亿”的觉悟？\n2. 纯纯的互联网思维去做智能手机，为什么必然沦为堆砌料件的组装厂？", key="p_hook_v2")
        
        # 【Python 3.11 安全向下兼容处理】在外侧将换行符替换为 HTML 换行标签
        hook_html_content = hook_text.replace('\n', '<br>')
        
        # 实时手机端 375px Canvas 长图动态平铺预览
        preview_html = f"""
        <div style="background-color: #0f172a; color: #f8fafc; padding: 22px; font-family: sans-serif; border-radius: 14px; width: 330px; margin: auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #1e293b;">
            <div style="background-color: #3b82f6; color: white; padding: 4px 8px; font-size: 10px; font-weight: bold; border-radius: 4px; display: inline-block; margin-bottom: 8px;">🎙️ INFLOW · 智能分发引擎</div>
            <h4 style="margin: 0 0 10px 0; font-size: 14px; line-height: 1.4; color: #f1f5f9;">{podcast_title}</h4>
            <hr style="border-color: #1e293b; margin-bottom: 12px;">
            <p style="color: #38bdf8; font-size: 11px; font-weight: bold; margin: 0 0 6px 0;">🪝 爆款高燃悬念自测题</p>
            <div style="font-size: 11px; color: #cbd5e1; line-height: 1.6; background-color: #0b0f19; padding: 12px; border-radius: 8px; border: 1px solid #1f293d;">
                {hook_html_content}
            </div>
            <div style="margin-top: 14px; text-align: center; border: 2px dashed #1e293b; padding: 10px; border-radius: 8px; background: #0b0f19;">
                <span style="font-size: 18px;">🔲</span>
                <p style="font-size: 9px; color: #64748b; margin: 2px 0 0 0;">长按扫码 · 听觉时空缝隙精准锚点跳转</p>
            </div>
        </div>
        """
        st.components.v1.html(preview_html, height=335)
        if st.button("📥 一键导出 PNG 发送朋友圈/小红书", use_container_width=True):
            st.toast("已调用本地网页切片引擎启动无损转换...图片已下载")