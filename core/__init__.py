# -*- coding: utf-8 -*-
"""pushnote 核心包。

把「本地笔记 txt → GitHub 仓库（可选生成文档站）」这条链路拆成可独立测试的模块：

    config.py      绑定关系的读写与校验
    envprobe.py    子进程环境净化 / 代理探测
    ghauth.py      GitHub 账号认证（OAuth Device Flow）
    secretstore.py 访问令牌的加密存储（Windows DPAPI）
    gitops.py      git 调用、凭据、重试
    convert.py     txt → Markdown（参数化）
    site.py        Markdown → docsify 站点
    pipeline.py    串联以上步骤，供 GUI 与命令行调用
"""
