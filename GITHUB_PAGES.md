# 发布到个人 GitHub Pages

运行：

```bash
python main.py
```

程序会在更新 PT、PD 数据和分析表后生成：

```text
site/pgm/index.html
```

把本项目的 `site/pgm` 文件夹复制到
`yiqing-cheung.github.io` 仓库根目录，最终结构为：

```text
yiqing-cheung.github.io/
└── pgm/
    └── index.html
```

提交并推送后，报告地址为：

```text
https://yiqing-cheung.github.io/pgm/
```

网页数据已经嵌入 `index.html`。每天重新运行 `main.py` 后，只需要更新
个人主页仓库中的 `pgm/index.html`。

网页的交互图使用 Plotly CDN，因此访问时需要能够连接
`cdn.plot.ly`。如果希望完全离线，可以把 Plotly JavaScript 下载到
`pgm/assets/`，并把 `index.html` 中的 CDN 地址改为本地文件路径。
