import streamlit as st
import time
import random

# ==========================================
# 0. 全局配置与 aa-v2.html 暗黑极客主题强力注入
# ==========================================
st.set_page_config(
    page_title="inFlow / Cogno 资产大脑控制中心",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 强力注入全定制 CSS：复刻 aa-v2.html 的 3D 透视、霓虹发光、玻璃态微章，并美化原生按钮
st.markdown("""
<style>
    /* 引入 FontAwesome 6.4.0 状态图标生态 */
    @import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css');

    /* 全局暗黑星际底色劫持 */
    .stApp {
        background-color: #0b0f19 !important;
        color: #e2e8f0 !important;
        font-family: 'PingFang SC', 'Helvetica Neue', sans-serif !important;
    }
    
    /* 左侧常驻高阶 SaaS 级垂直大导航栏 */
    section[data-testid="stSidebar"] {
        background-color: #0d1527 !important;
        border-right: 1px solid #1f293d !important;
        width: 300px !important;
    }
    
    /* 核心 3D 悬浮发光卡片 - 严格复刻 aa-v2.html 核心视觉密度 */
    div[data-testid="stVerticalBlockBorderReady"] {
        background: linear-gradient(145deg, #111827, #0b132b) !important;
        border: 1px solid #1f293d !important;
        border-radius: 16px !important;
        padding: 24px !important;
        perspective: 1000px !important; /* 注入 3D 空间感 */
        transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
        box-shadow: 0 4px 25px rgba(0, 0, 0, 0.6) !important;
    }
    
    /* 严格实现 aa-v2.html 的 Hover 形变升空与发光特效 */
    div[data-testid="stVerticalBlockBorderReady"]:hover {
        transform: translateY(-6px) scale(1.015) !important;
        border-color: #3b82f6 !important;
        box-shadow: 0 15px 35px rgba(59, 130, 246, 0.25) !important;
    }
    
    /* 美化 Streamlit 原生按钮，使其获得类似 aa-v2.html 的毛玻璃高亮质感 */
    .stButton>button {
        background: rgba(255, 255, 255, 0.05) !important;
        color: #f1f5f9 !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 10px !important;
        transition: all 0.3s ease !important;
    }
    .stButton>button:hover {
        background: linear-gradient(90deg, #2563eb, #1d4ed8) !important;
        border-color: #3b82f6 !important;
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3) !important;
        transform: translateY(-1px) !important;
    }
    
    /* 清洗状态呼吸灯指示条 */
    .glow-green-border { border-left: 4px solid #10b981 !important; }
    .glow-amber-border { border-left: 4px solid #f59e0b !important; }
    .glow-red-border { border-left: 4px solid #ef4444 !important; }
    
    /* 毛玻璃高透微章样式 */
    .glass-badge {
        background: rgba(255, 255, 255, 0.04) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        padding: 4px 12px !important;
        border-radius: 8px !important;
        font-size: 11px !important;
        font-family: monospace !important;
        color: #94a3b8 !important;
        display: inline-block !important;
    }

    /* 播客时间轨律动状态条 */
    .waveform-container {
        display: flex;
        align-items: flex-end;
        height: 24px;
        justify-content: flex-end;
        gap: 2px;
    }
    .wave-bar {
        width: 3px;
        background-color: #38bdf8;
        border-radius: 2px;
        animation: waveBounce 0.7s infinite alternate;
    }
    @keyframes waveBounce {
        0% { height: 4px; }
        100% { height: 20px; }
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 核心高动态内存模拟数据库
# ==========================================
if 'speaker_mappings' not in st.session_state:
    st.session_state.speaker_mappings = {"Speaker_0": "主持小张", "Speaker_1": "嘉宾李教授"}
if 'book_rolled' not in st.session_state:
    st.session_state.book_rolled = False
if 'current_book' not in st.session_state:
    st.session_state.current_book = {}

MOCK_BOOKS_DB = [
    {"id": "b1", "title": "《失控》", "author": "凯文·凯利", "format": "EPUB", "size": "4.2MB", "status": "🟢 已归仓", "age": "🧒 儿童安全", "intro": "系统自我演化启示录。"},
    {"id": "b2", "title": "《黑客与画家》", "author": "保罗·格雷厄姆", "format": "EPUB", "size": "1.8MB", "status": "🟢 已归仓", "age": "🧒 儿童安全", "intro": "硅谷极客自由创作者宣言，揭示财富密码。"},
    {"id": "b3", "title": "《当下的力量》", "author": "埃克哈特·托利", "format": "PDF", "size": "2.1MB", "status": "🟡 待校对", "age": "🔞 成人限制", "intro": "深度剖析时间幻相，彻底粉碎心理内耗与多维焦虑的内在指南。"},
    {"id": "b4", "title": "《大明王朝1566排版集》", "author": "刘和平", "format": "MOBI", "size": "12.5MB", "status": "🔴 原始", "age": "⏳ 未审计", "intro": "高密度硬核历史政治小说，亟待AI多维深度打标分级。"}
]

MOCK_PODCASTS_DB = [
    {"id": "p1", "title": "乱翻书 Vol.83：大厂做不对硬件的隐秘核心", "show": "乱翻书", "time": "84 分钟", "status": "🟢 转录完成"},
    {"id": "p2", "title": "知行小酒馆 E64：普通人如何安全配置第一份资产", "show": "知行小酒馆", "time": "58 分钟", "status": "🟢 转录完成"},
    {"id": "p3", "title": "声东击西 Vol.210：硅谷AI淘金热下的真实生态", "show": "声东击西", "time": "125 分钟", "status": "🟡 抽取中(72%)"},
    {"id": "p4", "title": "疯投圈 Vol.50：消费品行业的下半场突围战", "show": "疯投圈", "time": "72 分钟", "status": "🔴 纯音频"}
]

MOCK_VIDEOS_DB = [
    {"id": "v1", "title": "BBC.人类星球.Human.Planet.Ep01.mkv", "source": "家庭 NAS", "size": "4.2GB", "chapters": "🟢 已拆分 12 章节", "desc": "包含 00:12 捕鲸震撼场面跳转链接"},
    {"id": "v2", "title": "陆奇最新公开课：大模型时代的创业机会.mp4", "source": "本地下载", "size": "850MB", "chapters": "🔴 未分离视频轨", "desc": "非结构化视频，需要一键剥离音轨并唤醒 Groq LPU"}
]

# ==========================================
# 2. 【左侧常驻 SaaS 级黄金一导航栏】
# ==========================================
with st.sidebar:
    st.markdown("<h2 style='color:#3b82f6; font-size: 26px; font-weight: 800;'><i class='fa-solid fa-brain-circuit'></i> inFlow / Cogno</h2>", unsafe_allow_html=True)
    st.caption("全景核心资产画廊控制中心")
    st.markdown("---")
    
    # 严格按照指示，将三大全量物理实体资产提炼为左侧常驻一级菜单
    menu_selection = st.radio(
        "资产路由切换轨",
        [
            "📊 大盘数据总览", 
            "📚 3D立体书架", 
            "🎙️ 播客声纹声学墙", 
            "🎬 影院级公开课", 
            "⚡ 流水线控制塔", 
            "🛠️ 人机协同控制舱", 
            "🎲 资产多维激活原力"
        ],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    st.markdown("#### <i class='fa-solid fa-server text-sky-400'></i> 基础设施网关", unsafe_allow_html=True)
    st.success("● Calibre SQLite: 已挂载")
    st.success("● Audiobookshelf: 已联通")
    st.success("● Jellyfin Proxy: 稳定运行")
    
    st.markdown("---")
    st.markdown("#### <i class='fa-solid fa-bolt text-amber-400'></i> 今日算力开销", unsafe_allow_html=True)
    st.metric(label="Groq LPU 并行吞吐", value="$0.58")

# ==========================================
# 3. 【右侧高交互内容画布区 (SaaS 级闭环)】
# ==========================================

# ------------------------------------------
# 菜单 1：📊 大盘数据总览
# ------------------------------------------
if menu_selection == "📊 大盘数据总览":
    st.markdown("<h2><i class='fa-solid fa-chart-pie text-sky-500'></i> 数字化资产大盘智能总览</h2>", unsafe_allow_html=True)
    st.caption("实时监控资产大盘储量与 AI 能力层的实时开销指标。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(label="📚 电子书库标准化总数", value="102,481 册", delta="+12 册 (今日清洗)")
    m2.metric(label="🎙️ 播客高保真文本底座", value="482 小时", delta="Groq LPU 极速编译")
    m3.metric(label="🎬 视频硬核拆分章节", value="142 个章节")
    m4.metric(label="💰 今日 AI 综合算力消耗", value="$0.58")
    
    st.markdown("<br><h3><i class='fa-solid fa-wand-magic-sparkles text-indigo-400'></i> 交叉混推批量激活 (Webhook集群)</h3>", unsafe_allow_html=True)
    with st.container(border=True):
        st.write("一键向全屋智能终端或后台管道击发组合任务批处理：")
        col_macro1, col_macro2 = st.columns(2)
        if col_macro1.button("🔥 执行全量电子书年龄智能审计打标", use_container_width=True):
            st.toast("已击发 Webhook！正在调度后台 LLM 针对 Calibre 简介抓取打标...")
        if col_macro2.button("🎵 一键唤醒：对所有原始播客音频提取词级 json", use_container_width=True):
            st.toast("Groq Whisper API 集群已就绪，正在进行高频碎片吞吐...")

# ------------------------------------------
# 菜单 2：📚 3D立体书架 (参考 aa-v2.html 修正)
# ------------------------------------------
elif menu_selection == "📚 3D立体书架":
    st.markdown("<h2><i class='fa-solid fa-book-bookmark text-emerald-400'></i> 3D 立体数字虚拟书架</h2>", unsafe_allow_html=True)
    st.caption("严格同步本地 Calibre SQLite 数据库，具备 3D 立体悬浮升空形变与儿童安全隐藏控制。")
    
    search_book = st.text_input("🔍 全球跨模态检索：输入图书名称、作者或核心简介关键词...", "", key="search_b")
    st.markdown("<br>", unsafe_allow_html=True)
    
    grid_b1, grid_b2 = st.columns(2)
    for idx, book in enumerate(MOCK_BOOKS_DB):
        if search_book.lower() not in book["title"].lower() and search_book.lower() not in book["author"].lower():
            continue
        target_grid = grid_b1 if idx % 2 == 0 else grid_b2
        
        with target_grid:
            with st.container(border=True):
                # 状态与标题区
                b_h1, b_h2 = st.columns([4, 1])
                b_h1.markdown(f"### 📖 {book['title']}", unsafe_allow_html=True)
                b_h2.write(f"`{book['status']}`")
                
                st.markdown(f"**作者：** `{book['author']}`")
                st.markdown(f"<p style='color:#94a3b8; font-style:italic; font-size:13px;'>{book['intro']}</p>", unsafe_allow_html=True)
                
                # 玻璃态微章行
                st.markdown(f"<span class='glass-badge'>格式: {book['format']}</span> &nbsp; <span class='glass-badge'>大小: {book['size']}</span> &nbsp; <span class='glass-badge'>审计: {book['age']}</span>", unsafe_allow_html=True)
                st.markdown("<div style='margin-top:14px;'></div>", unsafe_allow_html=True)
                
                # 【全面修复】移除不支持的 unsafe_allow_html，转用 Emoji 图标提供极客交互感
                b_act1, b_act2, b_act3 = st.columns(3)
                with b_act1:
                    st.button("👁️ 预览高燃卡", key=f"preview_{book['id']}", use_container_width=True)
                with b_act2:
                    st.button("📌 投递Obsidian", key=f"sync_ob_{book['id']}", use_container_width=True)
                with b_act3:
                    if st.button("🚀 击发到Kindle", key=f"kindle_{book['id']}", use_container_width=True):
                        st.toast("全链路打通！已成功截获优质 EPUB 实体书并同步至您的 Kindle 账户！")

# ------------------------------------------
# 菜单 3：🎙️ 播客声纹声学墙 (音频动态律动)
# ------------------------------------------
elif menu_selection == "🎙️ 播客声纹声学墙":
    st.markdown("<h2><i class='fa-solid fa-podcast text-sky-400'></i> 🎙️ 播客时间轨声纹声学墙</h2>", unsafe_allow_html=True)
    st.caption("基于 Groq Whisper 编译的句级/词级时间戳（verbose_json）高阶结构化多维呈现。")
    
    search_pod = st.text_input("🔍 全球跨模态检索：输入播客单集标题或频道名...", "", key="search_p")
    st.markdown("<br>", unsafe_allow_html=True)
    
    grid_p1, grid_p2 = st.columns(2)
    for idx, pod in enumerate(MOCK_PODCASTS_DB):
        if search_pod.lower() not in pod["title"].lower():
            continue
        target_grid = grid_p1 if idx % 2 == 0 else grid_p2
        
        with target_grid:
            with st.container(border=True):
                p_col1, p_col2 = st.columns([4, 1])
                with p_col1:
                    st.markdown(f"#### {pod['title']}")
                    st.caption(f"📻 频道：{pod['show']}  |  ⏱️ 时长：{pod['time']}")
                with p_col2:
                    wave_html = """
                    <div class='waveform-container'>
                        <div class='wave-bar' style='animation-delay:0.1s;'></div>
                        <div class='wave-bar' style='animation-delay:0.4s;'></div>
                        <div class='wave-bar' style='animation-delay:0.2s;'></div>
                        <div class='wave-bar' style='animation-delay:0.6s;'></div>
                    </div>
                    """
                    st.markdown(wave_html, unsafe_allow_html=True)
                
                st.markdown("---")
                p_btn1, p_btn2 = st.columns(2)
                with p_btn1:
                    if "🔴" in pod["status"]:
                        st.button("⚡ Groq 10秒级转录", key=f"run_g_{pod['id']}", type="primary", use_container_width=True)
                    else:
                        st.button("🔊 声音轴锚点页", key=f"play_h5_{pod['id']}", use_container_width=True)
                with p_btn2:
                    st.button("👥 矫正对谈声纹", key=f"hitl_p_{pod['id']}", use_container_width=True)

# ------------------------------------------
# 菜单 4：🎬 影院级公开课 (16:9 宽幅大卡片)
# ------------------------------------------
elif menu_selection == "🎬 影院级公开课":
    st.markdown("<h2><i class='fa-solid fa-film text-purple-400'></i> 🎬 影院级硬核公开课/纪录片大盘</h2>", unsafe_allow_html=True)
    st.caption("采用 16:9 流媒体宽幅卡片矩阵，支持音视频分离清洗、AI 章节（Chapters）自动拆分。")
    
    search_vid = st.text_input("🔍 全球跨模态检索：输入公开课或纪录片关键词...", "", key="search_v")
    st.markdown("<br>", unsafe_allow_html=True)
    
    for vid in MOCK_VIDEOS_DB:
        if search_vid.lower() not in vid["title"].lower():
            continue
        with st.container(border=True):
            v_img, v_info = st.columns([1, 2])
            with v_img:
                st.markdown(f"""
                <div style='background:linear-gradient(135deg, #1e293b, #0f172a); border-radius:12px; height:125px; display:flex; flex-direction:column; justify-content:center; align-items:center; border:1px dashed #4b5563;'>
                    <span style='font-size:36px;'>🎬</span>
                    <span style='font-size:10px; color:#64748b; margin-top:6px;'>{vid['source']} | {vid['size']}</span>
                </div>
                """, unsafe_allow_html=True)
            with v_info:
                st.markdown(f"#### {vid['title']}")
                st.markdown(f"🧬 **大模型智能章节切片跟踪：** `{vid['chapters']}`")
                st.caption(f"💡 语义内核：{vid['desc']}")
                
                v_act1, v_act2 = st.columns(2)
                if "🔴" in vid["chapters"]:
                    v_act1.button("✂️ 离线剥离视频轨并编译", key=f"ff_{vid['id']}", type="primary", use_container_width=True)
                else:
                    v_act1.button("🔗 唤醒本地 Jellyfin 播放", key=f"jelly_{vid['id']}", use_container_width=True)
                v_act2.button("📺 推送家庭电视墙翻牌", key=f"tv_{vid['id']}", use_container_width=True)

# ------------------------------------------
# 菜单 5：⚡ 流水线控制塔
# ------------------------------------------
elif menu_selection == "⚡ 流水线控制塔":
    st.markdown("<h2><i class='fa-solid fa-bars-progress text-amber-400'></i> ⚡ 异步清洗管道流水监控塔</h2>", unsafe_allow_html=True)
    st.caption("实时透视后台正在异步清洗、转录、打包归仓的并行任务集群。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    with st.container(border=True):
        col_pipe1, col_pipe2, col_pipe3 = st.columns([2, 5, 1])
        col_pipe1.markdown("🎙️ **[播客转录中]** <br>乱翻书 Vol.102.mp3", unsafe_allow_html=True)
        col_pipe2.progress(72, text="Groq Whisper 极速引擎正在抽取句级词级时间戳对齐 (72%)...")
        if col_pipe3.button("紧急熔断", key="abort_p_塔"):
            st.error("已手动强制挂起执行管道。")

# ------------------------------------------
# 菜单 6：🛠️ 人机协同控制舱
# ------------------------------------------
elif menu_selection == "🛠️ 人机协同控制舱":
    st.markdown("<h2><i class='fa-solid fa-user-astronaut text-indigo-400'></i> 🛠️ 人机协同控制舱 (Human-in-the-Loop)</h2>", unsafe_allow_html=True)
    st.caption("AI 负责 95% 的自动化清洗，您负责最后的 5% 黄金终审，决不污染 Obsidian 本地双链。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_h_l, col_h_r = st.columns(2)
    with col_h_l:
        with st.container(border=True):
            st.markdown("##### 大模型推断角色声纹快速映射表")
            spk0_val = st.text_input("AI 检测到 [Speaker_0] ──► 批量全局重命名为：", value=st.session_state.speaker_mappings["Speaker_0"])
            spk1_val = st.text_input("AI 检测到 [Speaker_1] ──► 批量全局重命名为：", value=st.session_state.speaker_mappings["Speaker_1"])
            if st.button("💾 执行映射并批量修改文本底座", type="primary", use_container_width=True):
                st.session_state.speaker_mappings["Speaker_0"] = spk0_val
                st.session_state.speaker_mappings["Speaker_1"] = spk1_val
                st.success("重映射底座重写成功！就绪同步。")
    with col_h_r:
        with st.container(border=True):
            st.markdown("##### Obsidian 三轨并行结构文本底座预览")
            st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_0']} 00:01:12]**：欢迎收听，今天我们深度拆解将 CSS 3D 卡片与 Python 数据无缝衔接的产品美学。")
            st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_1']} 00:01:45]**：没错，左导航架构稳定、右内容视觉密度高，非常适合极客的大量数字资产索引。")

# ------------------------------------------
# 菜单 7：🎲 资产多维激活原力
# ------------------------------------------
elif menu_selection == "🎲 资产多维激活原力":
    st.header("🎲 沉睡资产多维激活原力场")
    st.caption("打破选择瘫痪，激活您的阅读热情与社交媒体分发大图引流冲动。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_f_l, col_f_r = st.columns([1, 1])
    
    # 7.1 随机盲盒摇号
    with col_f_l:
        st.markdown("### 🔮 电子书随机抽取激活盲盒")
        if st.button("🎰 开启随机摇号！冲破选择瘫痪", type="primary", use_container_width=True):
            st.session_state.current_book = random.choice(MOCK_BOOKS_DB)
            # 【Python 3.11 安全换行处理】
            b_intro = st.session_state.current_book['intro']
            b_age = st.session_state.current_book['age']
            st.session_state.current_book['ai_vibe'] = f"🔥 一句话击中：{b_intro}\n\n💡 智能年龄评级：`{b_age}`\n\n🪝 悬念钩子：顺着 Obsidian 思想双链探索未知的极客认知边界。"
            st.session_state.book_rolled = True
            
        if st.session_state.book_rolled:
            st.markdown(f"## 📖 今日摇中藏品：{st.session_state.current_book['title']}")
            st.info(st.session_state.current_book['ai_vibe'])
            if st.button("📌 立即投递卡片至今日 Obsidian 盲盒随笔中", use_container_width=True):
                st.toast("写入本地 Vault/Inbox/ 成功！")

    # 7.2 社交爆款引流长图渲染 (参考大图指南)
    with col_f_r:
        st.markdown("### 🖼️ 移动端引流高燃长图实时绑定分发")
        p_title = st.text_input("长图标题动态绑定", value="乱翻书 Vol.83：大厂做不对硬件的隐秘核心", key="p_t_input")
        p_hook = st.text_area("自测题悬念配置区", value="1. 为什么雷军说做硬件必须有“亏死五个亿”的觉悟？\n2. 纯纯的互联网思维去做智能手机，为什么必然沦为堆砌料件的组装厂？", key="p_h_input")
        
        # 【Python 3.11 安全换行处理】
        p_hook_html = p_hook.replace('\n', '<br>')
        
        # 实时渲染 375px 移动端极其紧凑、平铺的爆款引流长图组件
        preview_html = f"""
        <div style="background-color: #0f172a; color: #f8fafc; padding: 22px; font-family: sans-serif; border-radius: 14px; width: 330px; margin: auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #1e293b;">
            <div style="background-color: #3b82f6; color: white; padding: 4px 8px; font-size: 10px; font-weight: bold; border-radius: 4px; display: inline-block; margin-bottom: 8px;">🎙️ INFLOW · 智能分发引擎</div>
            <h4 style="margin: 0 0 10px 0; font-size: 14px; line-height: 1.4; color: #f1f5f9;">{p_title}</h4>
            <hr style="border-color: #1e293b; margin-bottom: 12px;">
            <p style="color: #38bdf8; font-size: 11px; font-weight: bold; margin: 0 0 6px 0;">🪝 爆款高燃悬念自测题</p>
            <div style="font-size: 11px; color: #cbd5e1; line-height: 1.6; background-color: #0b0f19; padding: 12px; border-radius: 8px; border: 1px solid #1f293d;">
                {p_hook_html}
            </div>
            <div style="margin-top: 14px; text-align: center; border: 2px dashed #1e293b; padding: 10px; border-radius: 8px; background: #0b0f19;">
                <span style="font-size: 18px;">🔲</span>
                <p style="font-size: 9px; color: #64748b; margin: 2px 0 0 0;">长按扫码 · 听觉时空缝隙精准锚点跳转</p>
            </div>
        </div>
        """
        st.components.v1.html(preview_html, height=335)
        st.button("📥 一键切片并导出无损 PNG", use_container_width=True)