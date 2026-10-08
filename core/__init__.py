# -*- coding: utf-8 -*-
"""pushnote 核心包。

把「本地笔记 txt → GitHub 仓库（可选生成文档站）」这条链路拆成可独立测试的模块：

    config.py     绑定关系的读写与校验
    envprobe.py   子进程环境净化 / 代理探测
    gitops.py     git 调用、凭据、重试
    convert.py    txt → Markdown（参数化）
    site.py       Markdown → docsify 站点
    pipeline.py   串联以上步骤，供 GUI 与命令行调用
"""
