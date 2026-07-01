import streamlit as st
import time
import random

# ==========================================
# 0. 全局配置与极客暗黑主题注入
# ==========================================
st.set_page_config(
    page_title="inFlow / Cogno 资产画廊控制中心",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入自定义精心设计的 CSS，全面复刻并升华用户在 aa-v2.html 中的 3D 浮动与状态发光心智
st.markdown("""
<style>
    /* 劫持全局暗黑背景 */
    .stApp {
        background-color: #0b0f19 !important;
        color: #cbd5e1 !important;
    }
    
    /* 强力改造 Streamlit 的 border container 变成高级 3D 悬浮卡片 */
    div[data-testid="stVerticalBlockBorderReady"] {
        background: linear-gradient(145deg, #111827, #0b132b) !important;
        border: 1px solid #1f293d !important;
        border-radius: 20px !important;
        padding: 24px !important;
        transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.6) !important;
    }
    
    /* 鼠标 Hover 卡片形变与发光特效 */
    div[data-testid="stVerticalBlockBorderReady"]:hover {
        transform: translateY(-6px) scale(1.02) !important;
        border-color: #3b82f6 !important;
        box-shadow: 0 12px 40px rgba(59, 130, 246, 0.25) !important;
    }
    
    /* 模拟音频波形动画 */
    .waveform-bar {
        display: inline-block;
        width: 3px;
        background-color: #38bdf8;
        margin-right: 2px;
        border-radius: 2px;
        animation: bounce 1s infinite alternate;
    }
    @keyframes bounce {
        0% { height: 5px; }
        100% { height: 25px; }
    }
    
    /* 玻璃质感微章 */
    .glass-badge {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 4px 10px;
        border-radius: 8px;
        font-size: 12px;
        font-family: monospace;
        color: #94a3b8;
    }
</style>
""", unsafe_allow_html=True)

# 初始化交互状态
if 'book_rolled' not in st.session_state:
    st.session_state.book_rolled = False
if 'current_book' not in st.session_state:
    st.session_state.current_book = {}
if 'speaker_mappings' not in st.session_state:
    st.session_state.speaker_mappings = {"Speaker_0": "主持小张", "Speaker_1": "嘉宾李教授"}

# ==========================================
# 1. 模拟全量高动态资产库 (Mock Dynamic Rich Database)
# ==========================================
MOCK_BOOKS_DB = [
    {"id": "b1", "title": "《失控》", "author": "凯文·凯利", "format": "EPUB", "size": "4.2MB", "status": "🟢 已归仓", "glow": "rgba(16,185,129,0.1)", "age": "🧒 儿童安全", "intro": "全面探讨机器、系统与生物联网的自发涌现演化启示录。"},
    {"id": "b2", "title": "《黑客与画家》", "author": "保罗·格雷厄姆", "format": "EPUB", "size": "1.8MB", "status": "🟢 已归仓", "glow": "rgba(16,185,129,0.1)", "age": "🧒 儿童安全", "intro": "硅谷创业教教父写给极客的自由创作者宣言，揭示财富密码。"},
    {"id": "b3", "title": "《当下的力量》", "author": "埃克哈特·托利", "format": "PDF", "size": "2.1MB", "status": "🟡 待校对", "glow": "rgba(245,158,11,0.15)", "age": "🔞 成人限制", "intro": "深度剖析时间幻相，彻底粉碎心理内耗与多维焦虑的内在指南。"},
    {"id": "b4", "title": "《大明王朝1566排版集》", "author": "刘和平", "format": "MOBI", "size": "12.5MB", "status": "🔴 原始", "glow": "rgba(239,68,68,0.15)", "age": "⏳ 未审计", "intro": "高密度硬核非结构化历史政治小说，亟待大模型抽取多维标签。"}
]

MOCK_PODCASTS_DB = [
    {"id": "p1", "title": "乱翻书 Vol.83：大厂做不对硬件的隐秘核心", "show": "乱翻书", "time": "84 分钟", "status": "🟢 转录完成", "wave_delay": "0.2s"},
    {"id": "p2", "title": "知行小酒馆 E64：普通人如何安全配置第一份资产", "show": "知行小酒馆", "time": "58 分钟", "status": "🟢 转录完成", "wave_delay": "0.5s"},
    {"id": "p3", "title": "声东击西 Vol.210：硅谷AI淘金热下的真实生态", "show": "声东击西", "time": "125 分钟", "status": "🟡 抽取中(72%)", "wave_delay": "0.8s"},
    {"id": "p4", "title": "疯投圈 Vol.50：消费品行业的下半场突围战", "show": "疯投圈", "time": "72 分钟", "status": "🔴 纯净音频", "wave_delay": "0s"}
]

MOCK_VIDEOS_DB = [
    {"id": "v1", "title": "BBC.人类星球.Human.Planet.Ep01.mkv", "source": "家庭 NAS", "size": "4.2GB", "chapters": "🟢 已拆分 12 章节", "desc": "包含 00:12 捕鲸震撼场面跳转链接"},
    {"id": "v2", "title": "陆奇最新公开课：大模型时代的创业机会.mp4", "source": "本地下载", "size": "850MB", "chapters": "🔴 未分离视频轨", "desc": "纯非结构化视频，需要 FFmpeg 一键剥离音轨并唤醒 Groq"}
]

# ==========================================
# 2. 侧边栏：大盘统计与硬件看板
# ==========================================
with st.sidebar:
    st.title("🧠 inFlow / Cogno")
    st.caption("v1.2.0-Gallery · 视觉全景数字控制台")
    st.markdown("---")
    
    st.subheader("🏛️ 中央藏馆总储量")
    st.markdown("##### 📚 电子书：`102,481` 册")
    st.markdown("##### 🎙️ 播客转录：`482` 小时")
    st.markdown("##### 🎬 视频拆分：`142` 个章节")
    
    st.markdown("---")
    st.subheader("📡 网关与 API 开销")
    st.success("● Calibre SQLite: 已挂载")
    st.success("● Audiobookshelf: 联通")
    st.metric(label="Groq LPU 今日开销", value="$0.58", delta="高效无感转录")

# ==========================================
# 3. 主界面：四大高交互功能分区
# ==========================================
st.title("🖥️ 资产大脑多维视觉工作台")

tab_vault, tab_pipeline, tab_hitl, tab_activate = st.tabs([
    "🎨 全量资产数字院墙 (Central Asset Gallery)",
    "📂 任务流水线控制塔 (Pipeline Tower)", 
    "👥 人机协同校对舱 (Human-in-the-Loop Hub)", 
    "🎲 资产多维激活原力场 (Activation Lounge)"
])

# ------------------------------------------
# TAB 1：全量资产数字院墙（全新视觉卡片流）
# ------------------------------------------
with tab_vault:
    # 全局搜索和状态过滤
    sc1, sc2 = st.columns([3, 1])
    with sc1:
        search_query = st.text_input("🔍 输入灵感关键词进行跨模态语义检索...", "", key="gallery_search")
    with sc2:
        filter_status = st.selectbox("视窗过滤器", ["全部资产", "精选已同步", "待清洗加工"])
        
    v_tab_b, v_tab_p, v_tab_v = st.tabs(["📚 3D 立体书架", "🎙️ 播客声纹声学墙", "🎬 16:9 影院公开课"])
    
    # 1.1 3D立体书架页面
    with v_tab_b:
        st.markdown("<br>", unsafe_allow_html=True)
        # 采用两列排布的高密度大卡片墙
        grid_b1, grid_b2 = st.columns(2)
        
        for idx, book in enumerate(MOCK_BOOKS_DB):
            if search_query.lower() not in book["title"].lower() and search_query.lower() not in book["author"].lower():
                continue
            
            # 交错塞入两个卡片网格列
            target_grid = grid_b1 if idx % 2 == 0 else grid_b2
            
            with target_grid:
                # 使用 Streamlit container + 注入的 CSS 实现 3D Card 效果
                with st.container(border=True):
                    # 卡片头部状态区
                    head1, head2 = st.columns([3, 1])
                    head1.markdown(f"### {book['title']}")
                    if "🟢" in book["status"]:
                        head2.markdown(f"<span class='status-badge-green'>{book['status']}</span>", unsafe_allow_html=True)
                    elif "🟡" in book["status"]:
                        head2.markdown(f"<span class='status-badge-amber'>{book['status']}</span>", unsafe_allow_html=True)
                    else:
                        head2.markdown(f"<span class='status-badge-red'>{book['status']}</span>", unsafe_allow_html=True)
                    
                    st.markdown(f"**作者：** `{book['author']}`")
                    st.markdown(f"*{book['intro']}*")
                    
                    # 标签栏
                    st.markdown(f"<span class='glass-badge'>{book['format']}</span> &nbsp; <span class='glass-badge'>{book['size']}</span> &nbsp; <span class='glass-badge'>{book['age']}</span>", unsafe_allow_html=True)
                    st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
                    
                    # 极具交互性的卡片内部动作栏
                    act1, act2, act3 = st.columns(3)
                    with act1:
                        if book["status"] == "🔴 原始":
                            st.button("🤖 召唤LLM打标", key=f"btn_ai_{book['id']}", type="primary", use_container_width=True)
                        else:
                            st.button("👁️ 预览安利卡", key=f"btn_preview_{book['id']}", use_container_width=True)
                    with act2:
                        st.button("📌 同步Obsidian", key=f"btn_sync_ob_{book['id']}", use_container_width=True)
                    with act3:
                        st.button("🚀 投递Kindle", key=f"btn_kindle_{book['id']}", use_container_width=True)

    # 1.2 播客声纹声学墙页面
    with v_tab_p:
        st.markdown("<br>", unsafe_allow_html=True)
        grid_p1, grid_p2 = st.columns(2)
        
        for idx, pod in enumerate(MOCK_PODCASTS_DB):
            if search_query.lower() not in pod["title"].lower():
                continue
            target_grid = grid_p1 if idx % 2 == 0 else grid_p2
            
            with target_grid:
                with st.container(border=True):
                    # 模拟动态波形动画的前端展示
                    p_head1, p_head2 = st.columns([4, 1])
                    with p_head1:
                        st.markdown(f"#### {pod['title']}")
                        st.caption(f"📻 节目频道： {pod['show']}  |  ⏱️ 时长： {pod['time']}")
                    with p_head2:
                        # 灌入纯 HTML CSS 的波形动效，打破死板展示
                        wave_html = f"""
                        <div style='display:flex; align-items:flex-end; height:30px; justify-content:flex-end;'>
                            <div class='waveform-bar' style='animation-delay:0.1s; height:12px;'></div>
                            <div class='waveform-bar' style='animation-delay:0.4s; height:22px;'></div>
                            <div class='waveform-bar' style='animation-delay:0.2s; height:18px;'></div>
                            <div class='waveform-bar' style='animation-delay:0.6s; height:8px;'></div>
                        </div>
                        """
                        st.markdown(wave_html, unsafe_allow_html=True)
                    
                    st.markdown("---")
                    p_act1, p_act2 = st.columns(2)
                    with p_act1:
                        if "🔴" in pod["status"]:
                            st.button("⚡ Groq 10秒极速转录", key=f"btn_groq_{pod['id']}", type="primary", use_container_width=True)
                        else:
                            st.button("🔊 唤醒交互式声音锚点", key=f"btn_anchor_{pod['id']}", use_container_width=True)
                    with p_act2:
                        st.button("👥 校对多人对谈声纹", key=f"btn_hitl_{pod['id']}", use_container_width=True)

    # 1.3 视频影院宽画幅墙
    with v_tab_v:
        st.markdown("<br>", unsafe_allow_html=True)
        for vid in MOCK_VIDEOS_DB:
            if search_query.lower() not in vid["title"].lower():
                continue
            with st.container(border=True):
                v_col_img, v_col_info = st.columns([1, 2])
                with v_col_img:
                    # 渲染一个极具科技感的 16:9 模拟流媒体卡片视窗
                    st.markdown(f"""
                    <div style='background:linear-gradient(135deg, #1e293b, #0f172a); border-radius:12px; height:130px; display:flex; flex-direction:column; justify-content:center; align-items:center; border:1px dashed #334155;'>
                        <span style='font-size:36px;'>🎬</span>
                        <span style='font-size:11px; color:#64748b; margin-top:4px;'>{vid['source']} ({vid['size']})</span>
                    </div>
                    """, unsafe_allow_html=True)
                with v_col_info:
                    st.markdown(f"#### {vid['title']}")
                    st.write(f"🧬 **大模型章节切片：** `{vid['chapters']}`")
                    st.caption(f"💡 {vid['desc']}")
                    
                    # 动作栏
                    v_act1, v_act2 = st.columns(2)
                    with v_act1:
                        if "🔴" in vid["chapters"]:
                            st.button("✂️ FFmpeg 抽离音轨并编译章节", key=f"btn_v_ffmpeg_{vid['id']}", type="primary")
                        else:
                            st.button("🔗 复制 Plex / Jellyfin 深度跳转链接", key=f"btn_v_link_{vid['id']}", use_container_width=True)
                    with v_act2:
                        st.button("📥 推送至大电视卡片墙", key=f"btn_v_tv_{vid['id']}", use_container_width=True)

# ------------------------------------------
# TAB 2：任务流水线控制塔 (继承流畅动效)
# ------------------------------------------
with tab_pipeline:
    st.subheader("⚡ 异步清洗管道监控")
    with st.container(border=True):
        col1, col2, col3 = st.columns([2, 5, 1])
        col1.write("🎙️ **[播客转录中]** 乱翻书 Vol.102.mp3")
        col2.progress(72, text="Groq Whisper 正在并行提取 Word-level 时间戳 json (72%)...")
        if col3.button("强制熔断", key="btn_abort_g"):
            st.warning("管道已锁定")

# ------------------------------------------
# TAB 3：人机协同校对舱 (实时可感知交互)
# ------------------------------------------
with tab_hitl:
    st.subheader("🛠️ 声纹对谈多角色快捷映射")
    col_l, col_r = st.columns(2)
    with col_l:
        with st.container(border=True):
            st.markdown("##### 👤 角色快速重映射表单")
            in_spk0 = st.text_input("AI 推断 [Speaker_0] ──► 映射为：", value=st.session_state.speaker_mappings["Speaker_0"])
            in_spk1 = st.text_input("AI 推断 [Speaker_1] ──► 映射为：", value=st.session_state.speaker_mappings["Speaker_1"])
            if st.button("💾 执行全本替换并归仓", type="primary"):
                st.session_state.speaker_mappings["Speaker_0"] = in_spk0
                st.session_state.speaker_mappings["Speaker_1"] = in_spk1
                st.success("声纹映射已重写！")
    with col_r:
        with st.container(border=True):
            st.markdown("##### 🔍 逐字稿声音锚点实时动态预览")
            st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_0']} 00:01:12]**：欢迎收听本期，今天大模型和个人资产是核心。")
            st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_1']} 00:01:45]**：没错，前端交互性是第一生产力。")

# ------------------------------------------
# TAB 4：资产多维激活原力场 (Tailwind 长图分发)
# ------------------------------------------
with tab_activate:
    st.subheader("🎲 唤醒沉睡资产，打破选择瘫痪")
    col_act_l, col_act_r = st.columns([1, 1])
    
    with col_act_l:
        st.markdown("### 🔮 电子书随机激活盲盒")
        if st.button("🎰 摇一摇！打破选择瘫痪", type="primary", use_container_width=True, key="btn_shuffle"):
            st.session_state.current_book = random.choice(MOCK_BOOKS_DB)
            # 【修复 Python 3.11 换行问题】提前计算好文本变量
            raw_intro = st.session_state.current_book['intro']
            raw_age = st.session_state.current_book['age']
            st.session_state.current_book['ai_vibe'] = f"🔥 一句话击中：{raw_intro}\n\n💡 智能分级：`{raw_age}`\n\n🪝 悬念钩子：打开 Obsidian，顺着双链探索未知的思想边界。"
            st.session_state.book_rolled = True
                
        if st.session_state.book_rolled:
            st.markdown(f"## 📖 今日摇中书目：{st.session_state.current_book['title']}")
            st.info(st.session_state.current_book['ai_vibe'])
            st.button("📌 投递到今日 Obsidian 随笔中", use_container_width=True)

    with col_act_r:
        st.markdown("### 🖼️ 爆款引流长图实时分发")
        podcast_title = st.text_input("长图标题联动绑定", value="乱翻书 Vol.83：大厂做不对硬件的隐秘核心", key="p_title_gallery")
        hook_text = st.text_area("高燃自测题文案配置", value="1. 为什么雷军说做硬件必须有“亏死五个亿”的觉悟？\n2. 纯纯的互联网思维去做智能手机，为什么必然沦为堆砌料件的组装厂？", key="p_hook_gallery")
        
        # 【Python 3.11 兼容性处理】在外侧将换行符安全替换为 HTML 换行标签
        hook_html_content = hook_text.replace('\n', '<br>')
        
        # 渲染极具手机即视感的高保真移动端长图卡片预览
        preview_html = f"""
        <div style="background-color: #0f172a; color: #f8fafc; padding: 24px; font-family: sans-serif; border-radius: 16px; width: 340px; margin: auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #1e293b;">
            <div style="background-color: #3b82f6; color: white; padding: 4px 8px; font-size: 10px; font-weight: bold; border-radius: 4px; display: inline-block; margin-bottom: 10px;">🎙️ INFLOW · 智能分发引擎</div>
            <h4 style="margin: 0 0 12px 0; font-size: 15px; line-height: 1.4; color: #f1f5f9;">{podcast_title}</h4>
            <hr style="border-color: #1e293b; margin-bottom: 12px;">
            <p style="color: #38bdf8; font-size: 12px; font-weight: bold; margin: 0 0 6px 0;">🪝 爆款高燃悬念自测题</p>
            <div style="font-size: 11px; color: #cbd5e1; line-height: 1.6; background-color: #0b0f19; padding: 12px; border-radius: 8px; border: 1px solid #1f293d;">
                {hook_html_content}
            </div>
            <div style="margin-top: 16px; text-align: center; border: 2px dashed #1e293b; padding: 12px; border-radius: 8px; background: #0b0f19;">
                <span style="font-size: 20px;">🔲</span>
                <p style="font-size: 9px; color: #64748b; margin: 4px 0 0 0;">长按扫码 · 听觉时空缝隙精准锚点跳转</p>
            </div>
        </div>
        """
        st.components.v1.html(preview_html, height=350)
        st.button("📥 一键导出 PNG 发送朋友圈", use_container_width=True)