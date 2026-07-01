import streamlit as st
import time
import random

# ==========================================
# 0. 全局配置与状态初始化
# ==========================================
st.set_page_config(
    page_title="inFlow / Cogno 全资产大脑控制中心",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化一些模拟的 session_state 用于保持全资产交互状态
if 'book_rolled' not in st.session_state:
    st.session_state.book_rolled = False
if 'current_book' not in st.session_state:
    st.session_state.current_book = {}
if 'speaker_mappings' not in st.session_state:
    st.session_state.speaker_mappings = {"Speaker_0": "Speaker_0", "Speaker_1": "Speaker_1"}

# ==========================================
# 1. 模拟全量资产动态数据库 (Mock Central Asset DB)
# ==========================================
MOCK_BOOKS_DB = [
    {"id": "b1", "title": "《失控》", "author": "凯文·凯利", "size": "4.2MB", "ai_status": "🟢 已归仓", "age_tag": "#成人", "intro": "系统自我演化启示录。"},
    {"id": "b2", "title": "《黑客与画家》", "author": "保罗·格雷厄姆", "size": "1.8MB", "ai_status": "🟢 已归仓", "age_tag": "#科普", "intro": "硅谷极客自由主义宣言。"},
    {"id": "b3", "title": "《当下的力量》", "author": "埃克哈特·托利", "size": "2.1MB", "ai_status": "🟡 待校对", "age_tag": "#成人", "intro": "击碎心理内耗的内在指南。"},
    {"id": "b4", "title": "《大明王朝1566排版集》", "author": "刘和平", "size": "12.5MB", "ai_status": "🔴 原始", "age_tag": "未打标", "intro": "历史正剧硬核非结构化小说。"},
    {"id": "b5", "title": "《小王子 (插图珍藏版)》", "author": "圣埃克苏佩里", "size": "35.1MB", "ai_status": "🟢 已归仓", "age_tag": "#儿童", "intro": "适合全年龄阅读的纯真童话。"}
]

MOCK_PODCASTS_DB = [
    {"id": "p1", "title": "乱翻书 Vol.83：大厂做不对硬件的隐秘核心", "show": "乱翻书", "duration": "01:24:12", "ai_status": "🟢 已生成verbose_json", "obsidian": "已同步"},
    {"id": "p2", "title": "知行小酒馆 E64：普通人如何配置第一份个人资产", "show": "知行小酒馆", "duration": "00:58:30", "ai_status": "🟢 已生成verbose_json", "obsidian": "已同步"},
    {"id": "p3", "title": "声东击西 Vol.210：硅谷AI淘金热下的真实生态", "show": "声东击西", "duration": "02:05:11", "ai_status": "🟡 抽取中(72%)", "obsidian": "未同步"},
    {"id": "p4", "title": "疯投圈 Vol.50：消费品行业的下半场突围", "show": "疯投圈", "duration": "01:12:00", "ai_status": "🔴 原始音频", "obsidian": "未同步"}
]

MOCK_VIDEOS_DB = [
    {"id": "v1", "title": "BBC.人类星球.Human.Planet.Ep01.mkv", "source": "家庭 NAS", "size": "4.2GB", "audio_extract": "🟢 已分离", "ai_chapters": "🟢 已拆分章节 (12个)"},
    {"id": "v2", "title": "陆奇最新公开课：大模型时代的创业机会.mp4", "source": "本地下载", "size": "850MB", "audio_extract": "🟢 已分离", "ai_chapters": "🔴 未拆分"},
    {"id": "v3", "title": "OpenAI Sora 官方生成高燃视频剪辑.mp4", "source": "微信暂存", "size": "120MB", "audio_extract": "🔴 未分离", "ai_chapters": "🔴 未拆分"}
]

# ==========================================
# 2. 侧边栏：核心数据量监控 & API 状态
# ==========================================
with st.sidebar:
    st.title("🧠 inFlow / Cogno")
    st.caption("v1.1.0-Alpha · 资产大脑控制台")
    st.markdown("---")
    
    st.subheader("📊 资产数字库大盘统计")
    st.metric(label="📚 电子书标准化总数", value="102,481 册", delta="+12 册 (今日清洗)")
    st.metric(label="🎙️ 播客转录总时长", value="482 小时")
    st.metric(label="🎬 视频硬核拆分章节", value="142 个")
    
    st.markdown("---")
    st.subheader("📡 能力网关开销")
    col_sb1, col_sb2 = st.columns(2)
    with col_sb1:
        st.metric(label="Groq Token", value="4.2M")
    with col_sb2:
        st.metric(label="今日金额", value="$0.58")
    st.success("● 存储网关: NAS 正常")

# ==========================================
# 3. 主工作台页面
# ==========================================
st.title("📟 资产大脑全景控制中心")

# 重新组织 4 大 Tabs 闭环，将“全量资产管理大盘”提到最核心的 Tab 1
tab_vault, tab_pipeline, tab_hitl, tab_activate = st.tabs([
    "𗃞 全量资产中央数字藏馆 (Central Asset Vault)",
    "📂 任务流水线控制塔 (Pipeline Tower)", 
    "👥 人机协同校对舱 (Human-in-the-Loop Hub)", 
    "🎲 资产多维激活原力场 (Activation Lounge)"
])

# ------------------------------------------
# TAB 1：全量资产中央数字藏馆 (新增加的核心管理页面)
# ------------------------------------------
with tab_vault:
    st.subheader("🏛️ 您名下的数字化资产统一透视与管理")
    
    # 搜索与过滤组合拳组件
    col_search, col_filter = st.columns([3, 1])
    with col_search:
        search_query = st.text_input("🔍 输入关键词在全球资产库中进行跨模态语义检索...", "")
    with col_filter:
        filter_status = st.selectbox("资产清洗状态过滤", ["全部状态", "🟢 已完成归仓", "🟡 正在AI处理/待校对", "🔴 纯原始未处理"])
        
    # 按多媒体类型分子标签呈现资产墙
    v_tab_books, v_tab_podcasts, v_tab_videos = st.tabs(["📚 电子书库 (Calibre DB)", "🎙️ 播客库 (Audiobookshelf)", "🎬 视频资产墙 (Jellyfin Proxy)"])
    
    # 1.1 电子书中央控制表
    with v_tab_books:
        st.markdown("##### 📥 Calibre 本地挂载的电子书资产记录")
        # 表头
        h1, h2, h3, h4, h5, h6 = st.columns([2, 1.5, 1, 1, 3, 2.5])
        h1.markdown("**书名**")
        h2.markdown("**作者**")
        h3.markdown("**文件大小**")
        h4.markdown("**AI 清洗状态**")
        h5.markdown("**AI 年龄标签/简介提炼**")
        h6.markdown("**主控交互动作**")
        st.markdown("---")
        
        for book in MOCK_BOOKS_DB:
            # 简单的模糊搜索模拟
            if search_query.lower() not in book["title"].lower() and search_query.lower() not in book["author"].lower():
                continue
            
            c1, c2, c3, c4, c5, c6 = st.columns([2, 1.5, 1, 1, 3, 2.5])
            c1.write(book["title"])
            c2.write(book["author"])
            c3.caption(book["size"])
            
            # 状态高亮渲染
            if book["ai_status"] == "🟢 已归仓":
                c4.success(book["ai_status"])
                c5.write(f"`{book['age_tag']}` {book['intro']}")
            elif book["ai_status"] == "🟡 待校对":
                c4.warning(book["ai_status"])
                c5.write(f"⚠️ 标签 `{book['age_tag']}` 待人工确认")
            else:
                c4.error(book["ai_status"])
                c5.write("❌ 尚无 AI 多维标签，请下达处理指令")
                
            with c6:
                cc1, cc2 = st.columns(2)
                if book["ai_status"] == "🔴 原始":
                    cc1.button("🤖 批量打标", key=f"act_run_{book['id']}", type="primary")
                else:
                    cc1.button("👁️ 预览卡片", key=f"act_view_{book['id']}")
                cc2.button("📌 同步Vault", key=f"act_sync_{book['id']}")

    # 1.2 播客中央控制表
    with v_tab_podcasts:
        st.markdown("##### 📻 RSS 监听与 Audiobookshelf 音频转录资产")
        hp1, hp2, hp3, hp4, hp5, hp6 = st.columns([3, 1.5, 1, 2, 1, 2])
        hp1.markdown("**播客单集名称**")
        hp2.markdown("**所属节目**")
        hp3.markdown("**音频时长**")
        hp4.markdown("**Groq 转录底座 (verbose_json)**")
        hp5.markdown("**Obsidian**")
        hp6.markdown("**主控交互动作**")
        st.markdown("---")
        
        for pod in MOCK_PODCASTS_DB:
            if search_query.lower() not in pod["title"].lower():
                continue
            cp1, cp2, cp3, cp4, cp5, cp6 = st.columns([3, 1.5, 1, 2, 1, 2])
            cp1.write(pod["title"])
            cp2.write(pod["show"])
            cp3.caption(pod["duration"])
            
            if "🟢" in pod["ai_status"]:
                cp4.success(pod["ai_status"])
                cp5.success(pod["obsidian"])
            elif "🟡" in pod["ai_status"]:
                cp4.warning(pod["ai_status"])
                cp5.warning(pod["obsidian"])
            else:
                cp4.error(pod["ai_status"])
                cp5.error(pod["obsidian"])
                
            with cp6:
                if "🔴" in pod["ai_status"]:
                    st.button("🚀 唤醒 Groq 极速转录", key=f"pod_run_{pod['id']}", type="primary", use_container_width=True)
                else:
                    st.button("🛠️ 矫正声纹角色", key=f"pod_edit_{pod['id']}", use_container_width=True)

    # 1.3 视频中央控制表
    with v_tab_videos:
        st.markdown("##### 🎬 家庭影音网关挂载的硬核公开课/纪录片资产")
        hv1, hv2, hv3, hv4, hv5, hv6 = st.columns([3, 1, 1, 1.5, 2, 2])
        hv1.markdown("**视频文件名称**")
        hv2.markdown("**物理资产源**")
        hv3.markdown("**视频大小**")
        hv4.markdown("**FFmpeg 音频抽离**")
        hv5.markdown("**AI 章节深度拆分 (Chapters)**")
        hv6.markdown("**主控交互动作**")
        st.markdown("---")
        
        for vid in MOCK_VIDEOS_DB:
            if search_query.lower() not in vid["title"].lower():
                continue
            cv1, cv2, cv3, cv4, cv5, cv6 = st.columns([3, 1, 1, 1.5, 2, 2])
            cv1.write(vid["title"])
            cv2.write(vid["source"])
            cv3.caption(vid["size"])
            
            if "🟢" in vid["audio_extract"]:
                cv4.success(vid["audio_extract"])
            else:
                cv4.error(vid["audio_extract"])
                
            if "🟢" in vid["ai_chapters"]:
                cv5.success(vid["ai_chapters"])
            else:
                cv5.error(vid["ai_chapters"])
                
            with cv6:
                v_btn1, v_btn2 = st.columns(2)
                if "🔴" in vid["audio_extract"]:
                    v_btn1.button("✂️ 剥离音轨", key=f"v_ext_{vid['id']}", type="primary")
                else:
                    v_btn1.button("🤖 拆分章节", key=f"v_chp_{vid['id']}", disabled=("🟢" in vid["ai_chapters"]))
                v_btn2.button("🔗 复制DeepLink", key=f"v_link_{vid['id']}")

# ------------------------------------------
# TAB 2：任务流水线控制塔 (原 Tab 1 顺延)
# ------------------------------------------
with tab_pipeline:
    st.subheader("⚡ 异步清洗管道监控")
    with st.expander("🔄 正在处理的任务 (1 个)", expanded=True):
        col1, col2, col3 = st.columns([2, 5, 1])
        with col1:
            st.text("🎙️ [播客] 乱翻书 Vol.102.mp3")
        with col2:
            st.progress(72, text="Groq Whisper 正在抽取 verbose_json (72%)...")
        with col3:
            if st.button("熔断中断", key="btn_abort"):
                st.warning("任务已手动中断")
                
    st.markdown("### 📋 管道队列流水记录")
    queue_data = [
        {"资产名称": "🎬 [视频] BBC.人类星球.Ep01.mkv", "阶段": "FFmpeg音频轨剥离", "状态": "排队中...", "耗时": "0s"},
        {"资产名称": "📚 [图书] 1823910.epub (未知ISBN)", "阶段": "LLM 批量合规与年龄打标", "状态": "异常挂起", "耗时": "4.2s"},
        {"资产名称": "🎙️ [播客] 知行小酒馆.E64.mp3", "阶段": "Obsidian 三轨笔记生成", "状态": "已完成", "耗时": "12.8s"},
    ]
    for item in queue_data:
        c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 1])
        c1.write(item["资产名称"])
        c2.info(item["阶段"])
        if item["状态"] == "已完成":
            c3.success(item["状态"])
        elif item["状态"] == "异常挂起":
            c3.error(item["状态"])
        else:
            c3.warning(item["状态"])
        c4.write(item["耗时"])
        with c5:
            if item["状态"] == "异常挂起":
                st.button("一键强制重试", key=item["资产名称"]+"_p_retry")
            else:
                st.button("查看日志", key=item["资产名称"]+"_p_log")

# ------------------------------------------
# TAB 3：人机协同校对舱 (原 Tab 2 顺延)
# ------------------------------------------
with tab_hitl:
    st.subheader("🛠️ AI 粗活检测 ➡️ 人工精准终审")
    col_edit_l, col_edit_r = st.columns(2)
    
    with col_edit_l:
        st.markdown("#### 🎙️ 播客声纹快捷纠偏 (Speaker Mapping)")
        spk0 = st.text_input("AI 检测到 [Speaker_0] (占对话 65%)，真实人名映射为：", value="主持小张")
        spk1 = st.text_input("AI 检测到 [Speaker_1] (占对话 35%)，真实人名映射为：", value="嘉宾李教授")
        
        if st.button("💾 确认映射并批量替换文本底座", type="primary"):
            st.session_state.speaker_mappings["Speaker_0"] = spk0
            st.session_state.speaker_mappings["Speaker_1"] = spk1
            st.success(f"成功！已交付给 Obsidian 三轨笔记结构！")
            
        st.markdown("##### 🔍 实时预览校对片段：")
        st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_0']} 00:01:12]**：欢迎收听本期节目，今天我们聊聊人工智能的下半场。")
        st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_1']} 00:01:45]**：其实下半场的本质不是算法的内卷，而是如何跟像 Obsidian 这样的本地资产做无缝联动。")

    with col_edit_r:
        st.markdown("#### 📚 十万册电子书年龄合规过滤抽检")
        books_review = [
            {"title": "《查拉图斯特拉如是说》", "ai_tag": "#成人 (晦涩哲学)", "real_status": True},
            {"title": "《格林童话排版精选集》", "ai_tag": "#儿童 (健康安全)", "real_status": False},
        ]
        for b in books_review:
            box_col1, box_col2, box_col3 = st.columns([3, 2, 2])
            box_col1.write(f"**{b['title']}**")
            box_col2.warning(f"AI 判定：{b['ai_tag']}")
            with box_col3:
                is_child_safe = st.toggle("儿童防误触隐藏", value=b['real_status'], key=b['title']+"_hitl_toggle")
                if is_child_safe:
                    st.caption("🧒 儿童端 Calibre-Web 已物理隔离隐藏")
                else:
                    st.caption("🔓 所有人全账号可见")

# ------------------------------------------
# TAB 4：资产多维激活原力场 (原 Tab 3 顺延)
# ------------------------------------------
with tab_activate:
    st.subheader("🎲 唤醒沉睡资产，打破选择瘫痪")
    col_act_l, col_act_r = st.columns([1, 1])
    
    with col_act_l:
        st.markdown("### 🔮 电子书随机激活盲盒")
        if st.button("🎰 摇一摇！打破选择瘫痪", type="primary", use_container_width=True):
            with st.spinner("正在从 Calibre 数据库检索中..."):
                time.sleep(0.5)
                st.session_state.current_book = random.choice(MOCK_BOOKS_DB)
                # 兼容旧卡片格式的渲染文本
                st.session_state.current_book['ai_vibe'] = f"🔥 一句话击中：此书已被 inFlow 索引。它的核心是：{st.session_state.current_book['intro']}\n\n💡 AI 建议标签：`{st.session_state.current_book['age_tag']}`\n\n🪝 悬念钩子：打开 Obsidian，探索属于你的第二大脑知识地图。"
                st.session_state.book_rolled = True
                
        if st.session_state.book_rolled:
            st.markdown(f"## 📖 今日摇中书目：{st.session_state.current_book['title']}")
            st.markdown(f"**作者**：`{st.session_state.current_book['author']}`")
            st.info(st.session_state.current_book['ai_vibe'])
            
            c_btn1, c_btn2 = st.columns(2)
            if c_btn1.button("📌 投递到今日 Obsidian 盲盒笔记", use_container_width=True, key="sync_box_btn"):
                st.toast("已成功写入本地 Vault/Inbox/Today_Blindbox.md！")
            if c_btn2.button("❌ 没感觉，重新摇一本", use_container_width=True, key="reroll_box_btn"):
                st.session_state.book_rolled = False
                st.rerun()

    with col_act_r:
        st.markdown("### 🖼️ 社交媒体引流长图分发控制")
        podcast_title = st.text_input("播客单集名称", value="乱翻书 Vol.83：大厂做不对硬件的隐秘核心", key="p_title_input")
        hook_text = st.text_area("自定义引流悬念钩子 (Hook)", value="1. 为什么雷军说做硬件必须有“亏死五个亿”的觉悟？\n2. 纯纯的互联网思维去做智能手机，为什么必然沦为堆砌料件的组装厂？", key="p_hook_input")
        
        st.markdown("##### 📱 移动端长图实时渲染预览 (375px Width Mock):")
        
        # 【Python 3.11 兼容性处理】
        hook_html_content = hook_text.replace('\n', '<br>')
        
        preview_html = f"""
        <div style="background-color: #0f172a; color: #f8fafc; padding: 20px; font-family: sans-serif; border-radius: 12px; width: 350px; margin: auto; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);">
            <div style="background-color: #3b82f6; color: white; padding: 4px 8px; font-size: 11px; font-weight: bold; border-radius: 4px; display: inline-block; margin-bottom: 8px;">🎙️ INFLOW · COGNO DETECTED</div>
            <h3 style="margin: 0 0 12px 0; font-size: 16px; line-height: 1.4;">{podcast_title}</h3>
            <hr style="border-color: #334155; margin-bottom: 12px;">
            <p style="color: #38bdf8; font-size: 13px; font-weight: bold; margin: 0 0 6px 0;">🪝 爆款高燃悬念钩子</p>
            <div style="font-size: 12px; color: #cbd5e1; line-height: 1.6; background-color: #1e293b; padding: 10px; border-radius: 6px;">
                {hook_html_content}
            </div>
            <div style="margin-top: 16px; text-align: center; border: 2px dashed #334155; padding: 12px; border-radius: 8px;">
                <span style="font-size: 24px;">🔲</span>
                <p style="font-size: 10px; color: #94a3b8; margin: 4px 0 0 0;">长按扫码 · 声音时间轴精准锚点跳转</p>
            </div>
        </div>
        """
        st.components.v1.html(preview_html, height=340)
        
        if st.button("📥 导出无损 PNG (一键发朋友圈/小红书)", use_container_width=True, key="download_png_btn"):
            st.toast("已经通过网页切片引擎自动转换为 inflow_podcast_share.png 并开始下载！")