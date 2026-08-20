"""inflow-core — inFlow 共享引擎。

schema + 全流程 pipeline 的唯一事实来源，云端 server 与本地 worker 共用：

    core      配置 / 数据库 / 模型 / 迁移 / 存储约定 / 日志
    ingest    s1 采集（orchestrator 状态机 + 各平台 adapter）
    parse     s2 解析（正文抽取、chapters、模板）
    display   s3 展示（阅读视图渲染）
    compose   s4 组合（精华卡渲染）
    publish   s5 发布
    prompts   LLM prompt 模板与卡片主题资源（load_prompt）
"""

__version__ = "1.0.0"
