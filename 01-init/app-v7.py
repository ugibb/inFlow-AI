import streamlit as st
import time
import random

# ==========================================
# 0. 全局视窗配置与 aa-v2.html / 精英暗黑主题注入
# ==========================================
st.set_page_config(
    page_title="inFlow / Cogno 跨模态资产控制塔",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 强力注入精细化 CSS 控制流：完美复刻图1、图2、图3的面板布局与 3D 透视悬停质感
st.markdown("""
<style>
    /* 引入极客专享 FontAwesome 6.4.0 全套图标生态 */
    @import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css');

    /* 1. 劫持全局底色 */
    .stApp {
        background-color: #0b0f19 !important;
        color: #e2e8f0 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }
    
    /* 2. 左侧常驻 SaaS 级黑金垂直大导航栏样式重写 */
    section[data-testid="stSidebar"] {
        background-color: #080c14 !important;
        border-right: 1px solid #1e293b !important;
        width: 280px !important;
    }
    
    /* 3. 核心 3D 悬浮发光容器 - 严格复刻 aa-v2.html 的视觉阻尼感 */
    div[data-testid="stVerticalBlockBorderReady"] {
        background: linear-gradient(145deg, #0f172a, #0b0f19) !important;
        border: 1px solid #1e293d !important;
        border-radius: 14px !important;
        padding: 20px !important;
        perspective: 1200px !important;
        transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4) !important;
    }
    div[data-testid="stVerticalBlockBorderReady"]:hover {
        transform: translateY(-4px) scale(1.01) !important;
        border-color: #3b82f6 !important;
        box-shadow: 0 12px 30px rgba(59, 130, 246, 0.18) !important;
    }
    
    /* 4. 图1 专享：电子书实体化硬核毛玻璃微章 */
    .media-badge {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 3px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-family: monospace;
        color: #38bdf8;
    }
    
    /* 5. 图2 专享：有声播放器进度轴、动态频振与角色对谈流 */
    .player-vibe-box {
        background: #070a12;
        border-radius: 12px;
        padding: 16px;
        border: 1px solid #1e293b;
    }
    .waveform-visualizer {
        display: flex;
        align-items: flex-end;
        height: 28px;
        gap: 3px;
    }
    .wave-pulse {
        width: 3px;
        background: linear-gradient(to top, #3b82f6, #60a5fa);
        border-radius: 2px;
        animation: waveJump 0.6s infinite alternate;
    }
    @keyframes waveJump {
        0% { height: 4px; }
        100% { height: 26px; }
    }
    .transcript-line {
        padding: 10px 14px;
        border-radius: 8px;
        margin-bottom: 8px;
        background: rgba(255, 255, 255, 0.02);
        border-left: 3px solid #3b82f6;
    }
    
    /* 6. 图3 专享：16:9 宽幅超维流媒体视窗与切割章节线 */
    .cinema-viewport {
        aspect-ratio: 16 / 9;
        background: linear-gradient(135deg, #1e293b, #020617);
        border-radius: 12px;
        border: 1px dashed #475569;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        position: relative;
    }
    .chapter-node {
        border-bottom: 1px solid #1e293b;
        padding: 10px 0;
    }

    /* 7. 全局原生按钮统一赋能磨砂质感 */
    .stButton>button {
        background: rgba(255, 255, 255, 0.04) !important;
        color: #f1f5f9 !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
        font-size: 13px !important;
        transition: all 0.3s ease !important;
    }
    .stButton>button:hover {
        background: #2563eb !important;
        border-color: #60a5fa !important;
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3) !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 初始化持久化会话交互状态
# ==========================================
if 'speaker_mappings' not in st.session_state:
    st.session_state.speaker_mappings = {"Speaker_0": "主持小张", "Speaker_1": "嘉宾李教授"}
if 'book_rolled' not in st.session_state:
    st.session_state.book_rolled = False
if 'current_book' not in st.session_state:
    st.session_state.current_book = {}

# Mock 数据库高贴合实体定义
MOCK_BOOKS = [
    {"id": "b1", "title": "《失控》", "author": "凯文·凯利", "format": "EPUB", "size": "4.2MB", "status": "🟢 已清洗归仓", "age": "🧒 儿童合规", "desc": "全面探讨机器、系统与生物联网的自发涌现演化启示录。"},
    {"id": "b2", "title": "《黑客与画家》", "author": "保罗·格雷厄姆", "format": "EPUB", "size": "1.8MB", "status": "🟢 已清洗归仓", "age": "🧒 儿童合规", "desc": "硅谷创业教父写给极客的自由创作者宣言。"},
    {"id": "b3", "title": "《当下的力量》", "author": "埃克哈特·托利", "format": "PDF", "size": "2.1MB", "status": "🟡 待人工微调", "age": "🔞 成人限制", "desc": "深度剖析时间幻相，彻底粉碎心理内耗与多维焦虑。"},
    {"id": "b4", "title": "《大明王朝1566排版集》", "author": "刘和平", "format": "MOBI", "size": "12.5MB", "status": "🔴 原始非结构化", "age": "⏳ 未审计", "desc": "硬核历史政治小说，亟待大模型抽取多维双链标签。"}
]

# ==========================================
# 2. 【左侧常驻导航菜单栏 (SaaS Web Console)】
# ==========================================
with st.sidebar:
    st.markdown("<h2 style='color:#3b82f6; font-size:24px; font-weight:800; margin-bottom:0;'>🧠 inFlow / Cogno</h2>", unsafe_allow_html=True)
    st.caption("跨模态全物理资产调配大盘")
    st.markdown("---")
    
    # 严格遵循用户指令：将三大物理实体资产栏目完全升级并常驻在左侧一级树状菜单中
    menu_selection = st.radio(
        "资产路由切换轴",
        [
            "📊 中央数据大盘", 
            "📚 3D立体书架", 
            "🎙️ 播客声纹声学墙", 
            "🎬 影院级公开课", 
            "⚡ 洗洗流水线", 
            "🛠️ 人机协同控制舱", 
            "🎲 资产随机激活场"
        ],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    st.markdown("⚙️ **基础设施网关**")
    st.success("● Calibre SQLite: 已挂载")
    st.success("● Audiobookshelf: 已互通")
    st.success("● Jellyfin Proxy: 联通")
    st.markdown("---")
    st.caption("⏳ 2026-06-30 08:54:42 · 本地工作流已就绪")

# ==========================================
# 3. 【右侧主视窗内容分发区 (Canvas Matrix)】
# ==========================================

# ------------------------------------------
# 3.1 📊 中央数据大盘
# ------------------------------------------
if menu_selection == "📊 中央数据大盘":
    st.title("📊 数字化资产大盘监控与系统 telemetry")
    st.caption("总览当前第二大脑物理硬盘存储基底与核心自动化 Webhook 击发开销。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📚 硬盘标准物理书量", "102,481 册", "+12 册 (今日清洗)")
    c2.metric("🎙️ 播客声纹高结构化底座", "482 小时", "Groq LPU 并行加速")
    c3.metric("🎬 视频硬核拆分章节", "142 个章节")
    c4.metric("💰 今日 AI 综合算力消耗", "$0.58")
    
    st.markdown("<br><h3>🔄 Webhook 集成集群一键调度</h3>", unsafe_allow_html=True)
    with st.container(border=True):
        st.write("点击下方核心组件，直接联动本地常驻控制台脚本执行物理文件级别批量重洗：")
        mac1, mac2 = st.columns(2)
        if mac1.button("🔥 击发全量电子书年龄智能合规合流打标", use_container_width=True):
            st.toast("任务发送成功！正在后台扫描 Calibre `metadata.db` ...")
        if mac2.button("🎵 一键提取全量原始音频词级时间戳 json", use_container_width=True):
            st.toast("已拉起 Groq Whisper Turbo 并行处理进程...")

# ------------------------------------------
# 3.2 📚 3D立体书架 (对齐参考图1规范)
# ------------------------------------------
elif menu_selection == "📚 3D立体书架":
    st.title("📚 3D 立体数字虚拟书架")
    st.caption("严格对接本地 Calibre 藏馆。右侧卡片矩阵具备 hover 立体平移与清洗状态霓虹发光提示。")
    
    search_b = st.text_input("🔍 输入书籍标题、作者或核心简介进行高密度智能检索...", "")
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 采用高品质两列布局，模拟图1卡片墙
    grid_b1, grid_b2 = st.columns(2)
    for idx, book in enumerate(MOCK_BOOKS):
        if search_b.lower() not in book["title"].lower() and search_b.lower() not in book["author"].lower():
            continue
        target_grid = grid_b1 if idx % 2 == 0 else grid_b2
        
        with target_grid:
            with st.container(border=True):
                head_l, head_r = st.columns([3, 1])
                head_l.markdown(f"### 📖 {book['title']}")
                head_r.write(f"`{book['status']}`")
                
                st.markdown(f"**元数据作者：** `{book['author']}`")
                st.markdown(f"<p style='color:#94a3b8; font-size:13px; font-style:italic;'>{book['desc']}</p>", unsafe_allow_html=True)
                
                # 渲染玻璃态标签组
                b1_html = f"<span class='media-badge'>格式: {book['format']}</span> &nbsp; <span class='media-badge'>体积: {book['size']}</span> &nbsp; <span class='media-badge'>审计: {book['age']}</span>"
                st.markdown(b1_html, unsafe_allow_html=True)
                st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
                
                # 功能动作闭环按钮组
                act_b1, act_b2, act_b3 = st.columns(3)
                act_b1.button("👁️ 预览高燃卡", key=f"pre_{book['id']}", use_container_width=True)
                act_b2.button("📌 投递Obsidian", key=f"ob_{book['id']}", use_container_width=True)
                if act_b3.button("🚀 远端推向设备", key=f"dev_{book['id']}", use_container_width=True):
                    st.toast(f"全链路打通！{book['title']} 已由本地邮件网关无感投递至外网 Kindle/电子纸设备。")

# ------------------------------------------
# 3.3 🎙️ 播客声纹声学墙 (对齐参考图2规范)
# ------------------------------------------
elif menu_selection == "🎙️ 播客声纹声学墙":
    st.title("🎙️ 播客时间轨声纹声学墙")
    st.caption("基于 Groq Whisper API 提取的 verbose_json。包含声音轴锚点、频振仪与多人对谈流。")
    
    # 模拟图2有声交互播放器控制盘
    st.markdown("### 🎛️ 正在播出的声音资产综合控制盘")
    with st.container(border=True):
        p_col_info, p_col_wave = st.columns([3, 1])
        with p_col_info:
            st.markdown("#### 乱翻书 Vol.83：大厂做不对硬件的隐秘核心")
            st.caption("📻 频道：乱翻书  |  ⏱️ 当前进度：`34:12 / 84:00`")
        with p_col_wave:
            # 动态律动跳跃，复刻有声界面频振感
            wave_html = """
            <div class='waveform-visualizer'>
                <div class='wave-pulse' style='animation-delay:0.1s;'></div>
                <div class='wave-pulse' style='animation-delay:0.4s;'></div>
                <div class='wave-pulse' style='animation-delay:0.2s;'></div>
                <div class='wave-pulse' style='animation-delay:0.5s;'></div>
                <div class='wave-pulse' style='animation-delay:0.3s;'></div>
            </div>
            """
            st.markdown(wave_html, unsafe_allow_html=True)
        
        # 模拟图2的逐字稿伴随声音锚点异步流布局
        st.markdown("<br>🗣️ **三轨并行多角色实时逐字稿流（带句级声音锚点跳转）**", unsafe_allow_html=True)
        
        t_line1 = f"<b>[{st.session_state.speaker_mappings['Speaker_0']} 00:34:12]</b> <span style='color:#38bdf8;'>(⚡情绪标签: 激动)</span>：做硬件最忌讳的就是用纯互联网思维，雷军说过做手机得有亏死五个亿的觉悟。"
        t_line2 = f"<b>[{st.session_state.speaker_mappings['Speaker_1']} 00:34:45]</b> <span style='color:#10b981;'>(⚡情绪标签: 赞同)</span>：确实，供应链的库存周转是个无底洞，稍微出点错货砸在手里就是灭顶之灾。"
        
        st.markdown(f"<div class='transcript-line'>{t_line1}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='transcript-line' style='border-left-color:#10b981;'>{t_line2}</div>", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        p_ctrl1, p_ctrl2, p_ctrl3 = st.columns(3)
        p_ctrl1.button("🔊 播放此声音片段", use_container_width=True)
        p_ctrl2.button("✂️ 截取该论点作为灵感卡片", use_container_width=True)
        p_ctrl3.button("📝 批注当下的灵光一闪", use_container_width=True)

# ------------------------------------------
# 3.4 🎬 影院级公开课 (对齐参考图3规范)
# ------------------------------------------
elif menu_selection == "🎬 影院级公开课":
    st.title("🎬 影院级硬核公开课/纪录片多维底座")
    st.caption("高画幅 16:9 影院级卡片。完美融合流媒体跳转、FFmpeg 后台音轨剥离与大模型智能切片。")
    
    with st.container(border=True):
        vid_col_view, vid_col_meta = st.columns([2, 3])
        
        with vid_col_view:
            # 严格参考图3，搭建一个精致带有暗黑呼吸感的 16:9 流媒体大核心视窗
            st.markdown("""
            <div class='cinema-viewport'>
                <span style='font-size:48px; color:#60a5fa;'>🎬</span>
                <p style='font-size:11px; color:#64748b; margin-top:8px;'>Jellyfin Local Mount Engine Active</p>
                <div style='position:absolute; bottom:10px; right:10px; font-family:monospace; font-size:10px; background:rgba(0,0,0,0.6); padding:2px 6px; border-radius:4px;'>1080P HEVC</div>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            st.button("🚀 唤醒 Jellyfin 深度链接无感跳转播放", use_container_width=True)
            
        with vid_col_meta:
            st.markdown("#### BBC.人类星球.Human.Planet.Ep01.mkv")
            st.write("🧬 **大模型智能化章节（Chapters）分割切片流：**")
            
            # 错落排列的视频切片线，对齐图3精细元数据流
            st.markdown("<div class='chapter-node'>⏳ <b>[00:00 - 08:15]</b> 北极圈极端严寒下的捕猎智慧：冰层钻孔与生存竞争。</div>", unsafe_allow_html=True)
            st.markdown("<div class='chapter-node'>⏳ <b>[08:15 - 19:40]</b> 震撼全场：近距离远洋捕鲸的多维协作机制。</div>", unsafe_allow_html=True)
            st.markdown("<div class='chapter-node'>⏳ <b>[19:40 - end]</b> 生态反思：人类对非结构化自然的降维改造。</div>", unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            v_act1, v_act2 = st.columns(2)
            v_act1.button("✂️ FFmpeg 离线剥离视频轨并编译", use_container_width=True)
            v_act2.button("📺 推送全屋多媒体电视墙翻牌", use_container_width=True)

# ------------------------------------------
# 3.5 ⚡ 洗洗流水线
# ------------------------------------------
elif menu_selection == "⚡ 洗洗流水线":
    st.title("⚡ 异步任务清洗管道控制中心")
    st.caption("透明化透视并监控后台正在并行清洗、拉取元数据、提取声纹的排队集群。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    with st.container(border=True):
        col_p1, col_p2, col_p3 = st.columns([2, 5, 1])
        col_p1.markdown("🎙️ **[播客清洗中]** <br>声东击西 Vol.210.mp3", unsafe_allow_html=True)
        col_p2.progress(72, text="Groq Whisper 正在并行提取 verbose_json 词级高能时间戳 (72%)...")
        if col_p3.button("熔断管道", key="abort_p_gal"):
            st.error("执行进程已被强制挂起。")

# ------------------------------------------
# 3.6 🛠️ 人机协同控制舱
# ------------------------------------------
elif menu_selection == "🛠️ 人机协同控制舱":
    st.title("🛠️ 人机协同声纹矫正控制舱")
    st.caption("AI 负责自动化重洗，您进行最后的 5% 终审校对，完美避免脏数据对 Obsidian 本地 Vault 造成双链污染。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_h_l, col_h_r = st.columns(2)
    with col_h_l:
        with st.container(border=True):
            st.markdown("##### 👤 快捷声纹角色重映射表单")
            in_s0 = st.text_input("AI 判定 [Speaker_0] ──► 全局重命名为：", value=st.session_state.speaker_mappings["Speaker_0"])
            in_s1 = st.text_input("AI 判定 [Speaker_1] ──► 全局重命名为：", value=st.session_state.speaker_mappings["Speaker_1"])
            if st.button("💾 执行映射变更并重新编译逐字稿", type="primary", use_container_width=True):
                st.session_state.speaker_mappings["Speaker_0"] = in_s0
                st.session_state.speaker_mappings["Speaker_1"] = in_s1
                st.success("声纹重写底座成功！")
                
    with col_h_r:
        with st.container(border=True):
            st.markdown("##### 🔍 写入 Obsidian 的 Markdown 三轨并行文本即时预览")
            st.write(f"**[{st.session_state.speaker_mappings['Speaker_0']}]**：欢迎收听本期，今天大模型和个人资产是核心。")
            st.write(f"**[{st.session_state.speaker_mappings['Speaker_1']}]**：没错，左导航稳定、右侧视觉高密度，正是极客所需要的。")

# ------------------------------------------
# 3.7 🎲 资产随机激活场
# ------------------------------------------
elif menu_selection == "🎲 资产随机激活场":
    st.title("🎲 沉睡资产随机激活盲盒")
    st.caption("利用随机涌现阻断选择瘫痪，支持一键配置并渲染小红书/朋友圈高燃爆款引流长图。")
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_a_l, col_a_r = st.columns([1, 1])
    with col_a_l:
        st.markdown("### 🔮 书籍随机盲盒抽取")
        if st.button("🎰 摇一摇！唤醒阅读热情", type="primary", use_container_width=True):
            st.session_state.current_book = random.choice(MOCK_BOOKS)
            b_intro = st.session_state.current_book['desc']
            b_age = st.session_state.current_book['age']
            st.session_state.current_book['ai_vibe'] = f"🔥 一句话击中：{b_intro}\n\n💡 智能年龄分级：`{b_age}`\n\n🪝 悬念钩子：顺着 Obsidian 神经双链网络探索未知的思想边界。"
            st.session_state.book_rolled = True
            
        if st.session_state.book_rolled:
            st.markdown(f"## 📖 今日藏品：{st.session_state.current_book['title']}")
            st.info(st.session_state.current_book['ai_vibe'])
            if st.button("📌 投递此盲盒至今日 Obsidian 随笔中", use_container_width=True):
                st.toast("写入 Vault/Inbox 成功！")

    with col_a_r:
        st.markdown("### 🖼️ 爆款社交引流大图动态平铺预览")
        p_title = st.text_input("海报标题联动绑定", value="乱翻书 Vol.83：大厂做不对硬件的隐秘核心", key="p_v3")
        p_hook = st.text_area("自测题悬念动态绑定", value="1. 为什么雷军说做硬件必须有“亏死五个亿”的觉悟？\n2. 纯纯的互联网思维去做智能手机，为什么必然沦为堆砌料件的组装厂？", key="h_v3")
        
        # 安全处理换行，向下完美兼容 Python 3.11
        p_hook_html = p_hook.replace('\n', '<br>')
        
        # 精准呈现一个 375px 的高燃大图移动端视窗
        poster_html = f"""
        <div style="background-color:#0f172a; color:#f8fafc; padding:20px; font-family:sans-serif; border-radius:12px; width:320px; margin:auto; box-shadow:0 10px 25px rgba(0,0,0,0.5); border:1px solid #1e293b;">
            <div style="background-color:#3b82f6; color:white; padding:3px 6px; font-size:10px; font-weight:bold; border-radius:4px; display:inline-block; margin-bottom:8px;">🎙️ INFLOW · 智能分发引擎</div>
            <h4 style="margin:0 0 10px 0; font-size:13px; line-height:1.4; color:#f1f5f9;">{p_title}</h4>
            <hr style="border-color:#1e293b; margin-bottom:10px;">
            <p style="color:#38bdf8; font-size:11px; font-weight:bold; margin:0 0 6px 0;">🪝 爆款高燃悬念自测题</p>
            <div style="font-size:11px; color:#cbd5e1; line-height:1.5; background-color:#0b0f19; padding:10px; border-radius:6px; border:1px solid #1f293d;">
                {p_hook_html}
            </div>
            <div style="margin-top:12px; text-align:center; border:2px dashed #1e293b; padding:8px; border-radius:6px; background:#0b0f19;">
                <span style="font-size:16px;">🔲</span>
                <p style="font-size:9px; color:#64748b; margin:2px 0 0 0;">长按扫码 · 听觉时空缝隙精准锚点跳转</p>
            </div>
        </div>
        """
        st.components.v1.html(poster_html, height=320)
        st.button("📥 一键切片无损导出社交高清 PNG", use_container_width=True)