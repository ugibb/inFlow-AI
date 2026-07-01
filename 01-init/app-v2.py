import streamlit as st
import time
import random

# ==========================================
# 0. 全局配置与状态初始化
# ==========================================
st.set_page_config(
    page_title="inFlow / Cogno 资产大脑控制中心",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化一些模拟的 session_state 用于保持前端交互状态
if 'book_rolled' not in st.session_state:
    st.session_state.book_rolled = False
if 'current_book' not in st.session_state:
    st.session_state.current_book = {}
if 'speaker_mappings' not in st.session_state:
    st.session_state.speaker_mappings = {"Speaker_0": "Speaker_0", "Speaker_1": "Speaker_1"}

# 模拟图书资产池
MOCK_BOOKS = [
    {"title": "《失控》", "author": "凯文·凯利", "ai_vibe": "🔥 一句话击中：这是一本关于机器、系统与生物联网的未来启示录。\n\n💡 3个颠覆观点：\n1. 真正的智能是由无数无意识的微个体自发涌现出来的。\n2. 未来最成功的控制是学会放弃控制，让系统自我演化。\n3. 机器正在生物化，而生物正在机器化。\n\n🪝 悬念钩子：为什么说人类最好的未来，是向没有灵魂的自然界交出管理权？"},
    {"title": "《黑客与画家》", "author": "保罗·格雷宏", "ai_vibe": "🔥 一句话击中：硅谷创业教父写给所有极客的自由主义宣言。\n\n💡 3个颠覆观点：\n1. 黑客不是破坏者，黑客是和画家一样的“创作者”。\n2. 要想发财，你必须身处一个能产生高杠杆率、且成果易于衡量的环境。\n3. 编程语言的演进其实是一场关于“表达能力”的军备竞赛。\n\n🪝 悬念钩子：为什么那些在高中最不受欢迎的呆子，最终统治了世界的财富？"},
    {"title": "《当下的力量》", "author": "埃克哈特·托利", "ai_vibe": "🔥 一句话击中：彻底击碎心理内耗、焦虑与时间瘫痪的内在指南。\n\n💡 3个颠覆观点：\n1. 痛苦的本质，是你对“当下”这一刻无意识的抗拒。\n2. 你的思维并不是真正的你，它只是一个被过去的记忆所绑架的工具。\n3. 时间是一个幻相，你唯一拥有的东西就是“现在”。\n\n🪝 悬念钩子：如何在面临巨大危机时，靠一秒钟的意识转变抽离所有痛苦？"}
]

# ==========================================
# 1. 侧边栏：核心硬件与 API 状态
# ==========================================
with st.sidebar:
    st.title("🧠 inFlow / Cogno")
    st.caption("v1.0.0-Beta · 个人资产大脑控制台")
    st.markdown("---")
    
    st.subheader("📡 基础设施网关")
    st.success("● Calibre DB (Connected)")
    st.success("● Audiobookshelf (Connected)")
    st.success("● Jellyfin Stream (Connected)")
    
    st.subheader("💰 AI 能力层开销 (今日)")
    col_sb1, col_sb2 = st.columns(2)
    with col_sb1:
        st.metric(label="Groq Token", value="4.2M")
    with col_sb2:
        st.metric(label="花费金额", value="$0.58", delta="-$0.12")
        
    st.markdown("---")
    st.info("💡 提示：这是一个高保真原型页面，所有开关、按钮和输入框均可直接点击交互。")

# ==========================================
# 2. 主页面：多标签页设计 (Tabs)
# ==========================================
st.title("📟 资产大脑核心工作台")
tab1, tab2, tab3 = st.tabs([
    "📂 任务流水线控制塔 (Pipeline Tower)", 
    "👥 人机协同校对舱 (Human-in-the-Loop Hub)", 
    "🎲 资产多维激活原力场 (Activation Lounge)"
])

# ------------------------------------------
# TAB 1：任务流水线控制塔
# ------------------------------------------
with tab1:
    st.subheader("⚡ 异步清洗管道监控")
    
    # 模拟正在运行的流水线任务
    with st.expander("🔄 正在处理的任务 (1 个)", expanded=True):
        col1, col2, col3 = st.columns([2, 5, 1])
        with col1:
            st.text("🎙️ [播客] 乱翻书 Vol.102.mp3")
        with col2:
            st.progress(72, text="Groq Whisper 正在抽取 verbose_json (72%)...")
        with col3:
            if st.button("熔断中断", key="btn_abort"):
                st.warning("任务已手动中断")
                
    # 模拟等待/完成列表
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
                st.button("一键强制重试", key=item["资产名称"])
            else:
                st.button("查看日志", key=item["资产名称"])

# ------------------------------------------
# TAB 2：人机协同校对舱
# ------------------------------------------
with tab2:
    st.subheader("🛠️ AI 粗活检测 ➡️ 人工精准终审")
    
    col_edit_l, col_edit_r = st.columns(2)
    
    with col_edit_l:
        st.markdown("#### 🎙️ 播客声纹快捷纠偏 (Speaker Mapping)")
        st.caption("原生 Groq Whisper 不支持声纹日志，此表为大模型根据语义语境推断的角色标签，请校对映射：")
        
        # 交互映射输入
        spk0 = st.text_input("AI 检测到 [Speaker_0] (占对话 65%)，真实人名映射为：", value="主持小张")
        spk1 = st.text_input("AI 检测到 [Speaker_1] (占对话 35%)，真实人名映射为：", value="嘉宾李教授")
        
        if st.button("💾 确认映射并批量替换文本底座", type="primary"):
            st.session_state.speaker_mappings["Speaker_0"] = spk0
            st.session_state.speaker_mappings["Speaker_1"] = spk1
            st.success(f"成功！已将底座中的角色名一键替换。就绪交付给 Obsidian 三轨笔记结构！")
            
        st.markdown("##### 🔍 实时预览校对片段：")
        st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_0']} 00:01:12]**：欢迎收听本期节目，今天我们聊聊人工智能的下半场。")
        st.markdown(f"**[{st.session_state.speaker_mappings['Speaker_1']} 00:01:45]**：其实下半场的本质不是算法的内卷，而是如何跟像 Obsidian 这样的本地资产做无缝联动。")

    with col_edit_r:
        st.markdown("#### 📚 十万册电子书年龄合规过滤抽检")
        st.caption("大模型自动扫描简介并判定的年龄分级标签。若 AI 发生误判，请在此一键强制推翻：")
        
        books_review = [
            {"title": "《查拉图斯特拉如是说》", "ai_tag": "#成人 (晦涩哲学)", "real_status": True},
            {"title": "《格林童话排版精选集》", "ai_tag": "#儿童 (健康安全)", "real_status": False},
            {"title": "《荒诞派戏剧与现代小说研究》", "ai_tag": "#成人 (含暗黑暗示)", "real_status": True},
        ]
        
        for b in books_review:
            box_col1, box_col2, box_col3 = st.columns([3, 2, 2])
            box_col1.write(f"**{b['title']}**")
            box_col2.warning(f"AI 判定：{b['ai_tag']}")
            with box_col3:
                # 交互开关
                is_child_safe = st.toggle("儿童防误触隐藏", value=b['real_status'], key=b['title']+"_toggle")
                if is_child_safe:
                    st.caption("🧒 儿童端 Calibre-Web 已物理隔离隐藏")
                else:
                    st.caption("🔓 所有人全账号可见")

# ------------------------------------------
# TAB 3：资产多维激活原力场
# ------------------------------------------
with tab3:
    st.subheader("🎲 唤醒沉睡资产，打破选择瘫痪")
    
    col_act_l, col_act_r = st.columns([1, 1])
    
    # 左侧：电子书随机盲盒
    with col_act_l:
        st.markdown("### 🔮 电子书随机激活盲盒")
        st.caption("从 10 万册吃灰图书中随机摇号，并直接拉取大模型编译的 30s 渐进式暴露卡片。")
        
        if st.button("🎰 摇一摇！打破选择瘫痪", type="primary", use_container_width=True):
            with st.spinner("正在从 Calibre 数据库疯狂检索并注入大模型原力..."):
                time.sleep(0.8) # 模拟跑马灯滚动
                st.session_state.current_book = random.choice(MOCK_BOOKS)
                st.session_state.book_rolled = True
                
        if st.session_state.book_rolled:
            st.markdown(f"## 📖 今日摇中书目：{st.session_state.current_book['title']}")
            st.markdown(f"**作者**：`{st.session_state.current_book['author']}`")
            
            # 高保真渲染大模型高燃安利卡片
            st.info(st.session_state.current_book['ai_vibe'])
            
            c_btn1, c_btn2 = st.columns(2)
            if c_btn1.button("📌 投递到今日 Obsidian 盲盒笔记", use_container_width=True):
                st.toast("已成功写入本地 Vault/Inbox/Today_Blindbox.md！")
            if c_btn2.button("❌ 没感觉，重新摇一本", use_container_width=True):
                st.session_state.book_rolled = False
                st.rerun()

    # 右侧：社交长图分发器
    with col_act_r:
        st.markdown("### 🖼️ 社交媒体引流长图分发控制")
        st.caption("基于 Tailwind CSS 驱动的高紧凑、平铺移动端长图生成。")
        
        podcast_title = st.text_input("播客单集名称", value="乱翻书 Vol.83：大厂做不对硬件的隐秘核心")
        hook_text = st.text_area("自定义引流悬念钩子 (Hook)", value="1. 为什么雷军说做硬件必须有“亏死五个亿”的觉悟？\n2. 纯纯的互联网思维去做智能手机，为什么必然沦为堆砌料件的组装厂？")
        
        st.markdown("##### 📱 移动端长图实时渲染预览 (375px Width Mock):")
        
        # 【修复 Python 3.11 报错核心】在外侧提前处理反斜杠换行符替换
        hook_html_content = hook_text.replace('\n', '<br>')
        
        # 用 HTML/TailwindCSS 渲染一个高保真的长图预览组件
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
        
        if st.button("📥 导出无损 PNG (一键发朋友圈/小红书)", use_container_width=True):
            st.toast("已经通过网页切片引擎自动转换为 inflow_podcast_share.png 并开始下载！")