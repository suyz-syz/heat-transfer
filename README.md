# 水泥窑窑衬传热计算（Cement Kiln Heat Transfer）

多层圆筒壁一维稳态传热计算器 —— 面向**回转水泥窑窑衬**热工设计与分析。

本项目的核心算法从工程实践代码重构而来，物理模型经过基准校验，并提供三种使用方式：
Kivy 跨平台移动端（Android APK）、FastAPI RESTful API（Docker 部署）、纯 Python 核心库。

## 功能特性

- **多层圆筒壁稳态传热**：以单位长度热功率 Q'（W/m）为守恒量，圆筒壁对数分布精确解。
- **内侧换热**：管内强制对流（Gnielinski + 入口效应修正）+ 烟气辐射（Hottel/Leckner 灰气体，分压 P·L 计）。
- **外侧换热**：水平圆柱自然对流（Churchill-Chu）或外掠强制对流（Zhukauskas）+ 外壳辐射。
- **物性温度相关**：Sutherland 拟合；内/外壁温双侧耦合迭代求解（自适应松弛，稳定收敛）。
- **可扩展性**：计算核心 `kiln_ht/` 零 UI 依赖，可嵌入任意应用。

## 技术栈

| 组件 | 技术 |
|---|---|
| 计算核心 | Python + NumPy |
| 移动端 UI | Kivy（Android / iOS / 桌面） |
| API 服务 | FastAPI + Uvicorn |
| 容器化 | Docker（多架构镜像发布至 GitHub Packages / ghcr.io） |
| 持续集成 | GitHub Actions（APK 编译 / Docker 发布） |

## 目录结构

```
cement-kiln-heat-transfer/
├── kiln_ht/                  # 核心计算库（无 UI / 服务依赖）
│   ├── __init__.py
│   └── calc.py               # 传热算法：对流/辐射/耦合迭代/温度曲线
├── tests/                    # 单元测试（pytest）
│   └── test_calc.py
├── main.py                   # Kivy 移动端入口
├── server.py                 # FastAPI 服务入口
├── Dockerfile                # API 服务容器镜像
├── buildozer.spec            # Android APK 打包配置
├── requirements.txt          # 完整依赖（核心 + API + Kivy + 测试）
├── requirements-server.txt   # Docker 镜像精简依赖（不含 Kivy）
├── .github/workflows/
│   ├── build-apk.yml         # 自动编译 Android APK
│   └── docker-publish.yml    # 自动构建并发布 Docker 镜像
└── .gitignore
```

## 本地运行

### 1. 计算核心（直接调用）

```bash
pip install numpy
python -c "
from kiln_ht import Layer, KilnParams, solve_wall
layers = [Layer('硅酸铝纤维', 0.150, 0.10),
          Layer('轻质砖',     0.100, 0.30),
          Layer('高铝砖',     0.080, 1.50),
          Layer('钢壳',       0.012, 45.0)]
sol = solve_wall(layers, KilnParams())
print(sol.as_dict())
"
```

### 2. Kivy 桌面端（调试 UI）

```bash
pip install -r requirements.txt
python main.py
```

### 3. FastAPI 服务

```bash
pip install -r requirements-server.txt
uvicorn server:app --host 0.0.0.0 --port 8000
# 或 python server.py
```

交互式 API 文档：<http://localhost:8000/docs>

示例请求：

```bash
curl -X POST http://localhost:8000/solve \
     -H "Content-Type: application/json" \
     -d '{"layers":[{"name":"纤维","thickness":0.15,"k":0.1},
                     {"name":"钢壳","thickness":0.012,"k":45}],
          "params":{"T_gas":1523.15}}'
```

## 单元测试

```bash
pip install pytest numpy
python -m pytest tests/ -v
```

## Android APK 下载与构建

### 方式一：GitHub Actions 自动编译（推荐）

1. 将本仓库推送到 GitHub 后，在 **Actions → Build Android APK** 中手动触发
   `workflow_dispatch`，或推送形如 `v1.0.0` 的 git tag 自动触发。
2. 构建完成后：
   - **Artifacts** 页签可下载 `kilnheat-apk` 压缩包（含 debug/release APK）；
   - 推送 tag 时还会自动创建 **GitHub Release**，可直接下载安装。

安装：手机开启“允许安装未知来源应用”，下载 APK 后直接安装即可。

### 方式二：本地 buildozer 构建

```bash
# 仅 Linux / WSL 支持，安装 buildozer 与系统依赖
pip install buildozer cython
sudo apt-get install -y libffi-dev libssl-dev python3-dev autoconf automake libtool pkg-config zlib1g-dev gettext cmake

buildozer android debug      # 生成 bin/kilnheat-*.apk
buildozer android release    # 生成签名发布包（需配置 keystore）
```

## Docker 部署

### 拉取预构建镜像（GitHub Packages）

推送到主分支或打 tag 后，`docker-publish.yml` 会自动构建 `linux/amd64,linux/arm64`
双架构镜像并推送到 `ghcr.io/<你的用户名>/cement-kiln-heat-transfer:latest`。

```bash
docker pull ghcr.io/<你的用户名>/cement-kiln-heat-transfer:latest
docker run --rm -p 8000:8000 ghcr.io/<你的用户名>/cement-kiln-heat-transfer:latest
```

### 本地构建镜像

```bash
docker build -t cement-kiln-heat-transfer .
docker run --rm -p 8000:8000 cement-kiln-heat-transfer
```

部署后访问：
- 健康检查：`GET http://localhost:8000/health`
- API 文档：`http://localhost:8000/docs`

## 物理模型依据

- 回转窑烟气辐射 / 内侧对流：`mptutvt/rotaryPyrolysis`（Tscheng-Watkinson 模型）
- 水泥窑壳散热：`mvoggu/heat_simulation`
- 传热学关联式：Gnielinski、Churchill-Chu、Zhukauskas、Hottel/Leckner

## 许可

[MIT](LICENSE)
