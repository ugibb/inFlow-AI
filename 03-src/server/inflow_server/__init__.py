"""inflow-server — inFlow 云端服务。

两个进程共用本包（部署见 deploy/cloud/）：

    main         FastAPI 应用（uvicorn inflow_server.main:app）
    routers      API 路由
    extensions   wechat bot / obsidian / research / review

重计算 pipeline 由 inflow-core 引擎提供（-e ../core 安装）。
"""
