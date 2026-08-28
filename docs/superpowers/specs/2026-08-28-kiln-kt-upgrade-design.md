# 水泥窑窑衬传热计算核心升级设计文档（k(T) + 接触热阻 + 材料库）

日期：2026-08-28
作者：水泥窑小组 / Claude Code
状态：待审阅

## 1. 背景与目标

### 1.1 现状

项目根目录 `F:\工作文件\水泥窑小组\python` 下散落大量传热计算脚本变体：

- 桌面 GUI：`Heat_tr.py`（圆筒壁 + 辐射模型）、`传热gui.py`（平板模型，旧）
- 命令行/交互：`传热.py`、`传热copilot.py`、`传热copilot2.py`、`传热google.py`、`传热计算插值（缩放）.py`、`传热计算/`
- 温度相关导热系数版：`HC.py`（k(T) 二项式 + scipy brentq 迭代）
- ANSYS 对接：`apdl.py`、`apdl传热.py`、`AnsysGen.cs` 及 `.exe`、多个 `.inp`
- 颗粒堆积（主题不同）：`紧密堆积.py`、`最紧密堆积.py`、`Modified Andreasen.py`
- 测试：`test_Heat_tr_review.py`（无 pytest 集成）

**核心子项目** `cement-kiln-heat-transfer/`（有 git、pytest、Docker、CI、Streamlit/Kivy/FastAPI 三种入口）：
- `kiln_ht/calc.py` —— 多层圆筒壁一维稳态传热计算核心（纯标准库，零第三方依赖）
- `kiln_ht/__init__.py`、`app.py`（Streamlit）、`server.py`（FastAPI）、`main.py`（Kivy）
- `tests/test_calc.py`、`tests/test_ui.py`、`tests/test_web_ui.py`

### 1.2 问题

1. **物理模型不一致**：同一物理问题被实现了至少 4 种模型（平板、圆筒壁、圆筒壁+辐射、k(T) 二项式），数值结果互相对不上。
2. **计算逻辑重复内联**：多个 GUI 类里手写 h_in 等，无法统一维护。
3. **缺失 k(T)**：`calc.py` 目前只有常数 k，而 `HC.py` 已实现温度相关导热系数（更贴近真实耐火材料行为），但未集成。
4. **目录混乱**：大量 `- 副本`、`copilot` 变体，无版本管理。

### 1.3 目标（方案 A：渐进式重构）

- 以 `cement-kiln-heat-transfer/` 为唯一主项目，`kiln_ht/calc.py` 为唯一计算核心。
- 核心升级为 **k(T) 温度相关导热系数** + **层间接触热阻 R_c**。
- 新增 **内置耐火材料库**（k(T) 系数来自耐火材料手册/国标工程数据）。
- 三个 GUI 入口（Streamlit / Kivy / FastAPI）适配新数据结构。
- 根目录遗留脚本归档到 `Archive/`，不再维护。
- 全程 TDD：先写测试，再改核心，保证物理数值正确。

## 2. 物理模型设计

### 2.1 模型范围

保持 calc.py 现有的多层圆筒壁一维稳态模型框架，仅升级物性与新增接触热阻：

- 内侧：管内强制对流（Gnielinski + 入口效应修正）+ 烟气辐射（Hottel/Leckner 灰气体）
- 外侧：水平圆柱自然对流（Churchill-Chu）或外掠强制对流（Zhukauskas）+ 外壳辐射
  - calc.py 现用 Churchill-Usagi 组合（指数 3.5）平滑自然/强制对流过渡（保留）
- **新增**：每层导热系数 k(T) 随温度变化；层间接触热阻 R_c
- 温度曲线：圆筒壁内对数分布精确解（保留），但层内 k 用积分平均

### 2.2 温度相关导热系数 k(T)

每层用二项式：

```
k(T) = a + b·T + c·T²     （T 单位：℃）
```

- 常数 k 用户：设 `k_coef = (k, 0.0, 0.0)`。
- 层内 k 采用 **积分平均导热系数**（同 HC.py 的 `get_k_mean` 思路）：

```
k_avg = ( a·(Th-Tc) + (b/2)·(Th²-Tc²) + (c/3)·(Th³-Tc³) ) / (Th - Tc)
```

其中 Th、Tc 为该层热面/冷面温度（℃）。当 Th≈Tc 时退化为 `a + b·T + c·T²`。

### 2.3 层间接触热阻 R_c

- 每层新增可选字段 `Rc`（m²·K/W），默认 0（无接触热阻）。
- 物理含义：层与层界面（砖缝/浇注料与钢壳间隙）的界面热阻。
- 折算为单位长度圆筒热阻：

```
R_contact_i' = Rc / (2π · r_interface_i)
```

其中 `r_interface_i` 为第 i 层与第 i+1 层界面半径。
- 该热阻插入相邻两层热阻之间（等效为第 i 层热阻的一部分）。
- 用户可选指定；不指定即为 0，完全兼容旧数据。

### 2.4 求解迭代策略

`solve_wall()` 需处理 **双层耦合**：

1. **外层**：壁温耦合迭代（现有，自适应松弛）。
2. **内层**：每个迭代步内，各层 k(T) 依赖该层冷热面温度（上一步界面温度），计算积分平均 k 后代入热阻网络。

实现方式（保持现有迭代结构）：
- 每次迭代时，用**当前界面温度**计算各层 `k_avg`，构建热阻网络。
- 更新界面温度。
- 收敛判定沿用现有 `WALL_TOL` + 自适应松弛。
- 由于 k(T) 随温度缓变，现有迭代在绝大多数工况下可收敛；极端情况（厚保温层）需确保迭代不发散（可用 under-relaxation 或对 k_avg 也做阻尼）。

### 2.5 材料库

新增 `kiln_ht/materials.py`，内置常用耐火材料 k(T) 系数（**工程验证数据，来自耐火材料手册/国标**）：

| 材料名 | a | b | c | 来源/说明 |
|---|---|---|---|---|
| 硅酸铝纤维 | 0.08 | 1.2e-4 | 0.0 | 手册标准式 `0.08+0.00012T`，0–1200℃ |
| 轻质砖 | 0.32 | 1.8e-4 | 0.0 | `0.32+0.00018T`，0–1200℃ |
| 高铝砖 | 1.05 | 1.5e-4 | 0.0 | `1.05+0.00015T`，0–1400℃ |
| 重质高铝浇注料 | 1.2 | 4.5e-4 | -1.2e-7 | 与 HC.py `[1.2,4.5e-4,-1.2e-7]` 一致 |
| 钢壳 | 45.0 | 0.0 | 0.0 | 常数（近似） |

- 每个材料条目：`name`、`k_coef`、`valid_range_c`（℃）、可选 `density`/`max_service_temp`（元数据）。
- 材料库仅提供系数预设，计算核心不强制依赖（GUI 层调用）。

## 3. 数据结构设计

### 3.1 `kiln_ht/calc.py` 改动

```python
@dataclass(frozen=True)
class Layer:
    name: str = "层"
    thickness: float = 0.05       # m
    k_coef: Tuple[float, float, float] = (1.0, 0.0, 0.0)  # a, b, c for k(T)=a+bT+cT² (T in ℃)
    Rc: float = 0.0               # 层间接触热阻 (m²·K/W)，0 = 无

    def __post_init__(self):
        # 旧 k 字段兼容：若仅提供 k（k_coef 为默认值），自动转 k_coef=(k,0,0)
        ...

    @property
    def k_const(self) -> float:
        """兼容常数 k 场景：返回 a（当 b=c=0 时即常数 k）。"""
        return self.k_coef[0]

    def k_at(self, T_c: float) -> float:
        a, b, c = self.k_coef
        return a + b * T_c + c * T_c * T_c
```

- **兼容策略**：`Layer` 增加可选 `k_coef` 字段；**保留旧 `k` 字段**。若调用方只提供 `k`（`k_coef` 为默认 `(1,0,0)` 且被显式跳过），自动转为 `k_coef=(k,0,0)`。实现细节：
  - `Layer(name=..., thickness=..., k=0.10)` → `k_coef=(0.10,0,0)`（旧代码无缝迁移）
  - `Layer(name=..., thickness=..., k_coef=(0.08,1.2e-4,0.0))` → 直接使用
  - 若同时提供 k 与 k_coef，以 k_coef 为准（k 仅作兼容回退）
- 提供 `k_const` 便捷属性，常数 k 场景等价。
- `solve_wall()` 内部统一取 `k_coef` 计算，不直接读 `k`。

### 3.2 `kiln_ht/materials.py`（新增）

```python
# 材料库：name -> {k_coef, valid_range_c, note}
MATERIALS = {
    "硅酸铝纤维":     {"k_coef": (0.08, 1.2e-4, 0.0), "valid_range_c": (0, 1200)},
    "轻质砖":         {"k_coef": (0.32, 1.8e-4, 0.0), "valid_range_c": (0, 1200)},
    "高铝砖":         {"k_coef": (1.05, 1.5e-4, 0.0), "valid_range_c": (0, 1400)},
    "重质高铝浇注料":  {"k_coef": (1.2, 4.5e-4, -1.2e-7), "valid_range_c": (0, 1400)},
    "钢壳":           {"k_coef": (45.0, 0.0, 0.0), "valid_range_c": (0, 500)},
}

def get_material(name: str) -> dict:
    """按名称获取材料，未知名称抛 KeyError/ValueError。"""
    ...
```

### 3.3 求解函数签名（保留）

`solve_wall(layers, params)` 与 `compute_temperature_curve(layers, sol)` 签名不变，内部适配新 Layer 字段。

## 4. API / GUI 适配

### 4.1 FastAPI `server.py`

- `LayerIn` Pydantic 模型：`name`、`thickness`、`k_coef`（可省略，默认 `(1,0,0)`）、`Rc`（可省略，默认 0）。
- **兼容旧客户端**：保留 `k` 字段作为可选输入；若提供 `k` 且未提供 `k_coef`，则自动转为 `k_coef=(k,0,0)`（与 Layer 兼容策略一致）。
- `KilnParamsIn` 不变。
- 新增可选材料库端点（后续版本）：`GET /materials`。

### 4.2 Streamlit `app.py`

- 衬层编辑：材料名下拉（从材料库加载，选中自动填充 k_coef）+ 可覆盖 a/b/c + 可选 Rc 输入框。
- 预设工况 PRESETS 更新为 k_coef 格式。
- 指标展示：增加"层平均导热系数 k_avg"显示（可选）。

### 4.3 Kivy `main.py`

- 衬层输入：材料下拉 + a/b/c/Rc 输入（或最小改动：仅支持 k_coef 三个输入框 + Rc）。
- 保持 Kivy 布局风格。

## 5. 测试计划（TDD）

### 5.1 新增/更新测试

**`tests/test_calc.py`（更新）**
- 常数 k 回归：`k_coef=(k,0,0)` 与旧 `k` 行为等价（能量守恒、温度界内）。
- k(T) 积分平均正确性：单层、已知 Th/Tc，手工计算 k_avg 对比。
- k(T) 单调性：温度沿径向递减仍成立。
- 接触热阻：Rc>0 时界面温差增大，Q' 减小；Rc=0 与旧行为一致。
- 极端工况收敛：厚纤维单层（k(T) 下仍收敛）。

**`tests/test_materials.py`（新增）**
- 材料库条目完整（非空、k_coef 为 3 元组、数值有限）。
- `get_material` 已知名/未知名行为。
- 材料 k(T) 在有效温度范围内为正值。

**`tests/test_ui.py` / `test_web_ui.py`（更新）**
- Streamlit/FastAPI 输入模型接受 k_coef、Rc 字段。

### 5.2 验证基准

- 用 `Archive/old_scripts/HC.py` 的基准算例（brentq 迭代结果）作为 k(T) 的交叉验证基准（数值应在合理容差内一致）。
- 用现有 `test_calc.py` 的辐射/对流算例做回归。

## 6. 归档与目录清理

```
python/
├── cement-kiln-heat-transfer/      # 唯一主项目
├── Archive/
│   ├── old_scripts/                # 传热.py、传热gui.py、传热copilot*.py、传热google.py、
│   │                               # 传热计算插值（缩放）.py、Heat_tr.py、Heat_tr-副本.py、
│   │                               # test_Heat_tr_review.py 等
│   ├── ansys/                      # apdl*.py、AnsysGen*.cs、*.inp、HeatCalc*.*
│   └── particle/                   # 紧密堆积.py、最紧密堆积.py、Modified Andreasen.py
├── Heat_tr.build/ Heat_tr.dist/    # 删除（打包产物）
├── *.exe                           # 保留在 Archive/ansys/ 或删除（有 git 可恢复）
└── 传热计算/                        # 保留（若仍在使用）或归档
```

- 归档前先初始化 git（若根目录无 git），提交当前状态作为回滚点。
- 归档后所有 Python 脚本只做移动，不改内容。

## 7. 实施顺序（阶段划分）

1. **阶段 0**：初始化根目录 git，提交基线（安全回滚点）。
2. **阶段 1**：核心升级 `calc.py`（Layer 字段 + solve_wall 迭代 + k_avg）+ `materials.py` + 测试。
3. **阶段 2**：FastAPI `server.py` 适配 + 测试。
4. **阶段 3**：Streamlit `app.py` 适配。
5. **阶段 4**：Kivy `main.py` 适配。
6. **阶段 5**：归档遗留脚本 + 清理打包产物。
7. **阶段 6**：全量回归测试 + README 更新。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| k(T) 迭代不收敛（极端保温工况） | k_avg 阻尼 / under-relaxation；扩大 MAX_WALL_ITER |
| 破坏性变更影响现有客户端 | 保留 `k` 兼容输入（server.py）；README 迁移说明 |
| 材料系数与实测偏差 | 系数以手册/国标为准，标注来源与有效温度范围；GUI 允许手动覆盖 |
| 归档误删 | 先 git 提交基线，归档只移动不删除 |

## 9. 待确认项

- [x] k_coef 字段名（`k_coef` vs `k_t` vs `kabc`）——已定 `k_coef`
- [x] 接触热阻输入单位（m²·K/W）——已定
- [x] 是否保留 `k` 兼容输入——**保留**（已确认）
- [x] 材料库是否允许用户自定义保存——仅内置预设，自定义通过手动填系数实现（已确认）
- [ ] 接触热阻 Rc 单位是否明确标注为 m²·K/W（设计中已明确）
- [ ] GUI 中材料下拉 + 手动覆盖的交互细节（待实施阶段确认）
