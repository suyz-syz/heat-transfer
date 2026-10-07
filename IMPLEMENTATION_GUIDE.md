# GUI 重构实施指南

> **状态**: ✅ 设计完成，核心代码已输出  
> **下一步**: 集成到现有项目，分阶段测试

---

## 一、已完成的工作

### 1. 设计文档

📄 **`docs/GUI_REDESIGN_SPEC.md`**  
- 完整的架构设计
- 交互流程图
- 主题色系定义
- 实施优先级规划

### 2. 核心代码模块

#### Streamlit Web 端

📄 **`streamlit_enhanced.py`** (新文件，840 行)  
包含：
- ✅ Material Design 3 暗色主题 CSS
- ✅ 三档参数分组（必填/常用/高级）
- ✅ 工况模板系统（含衬层结构）
- ✅ 智能验证系统（厚度/Fourier/梯度检查）
- ✅ 历史对比功能（最多5条记录）
- ✅ 数据结构：`CalculationRecord`
- ⚠️ 部分功能标记为"复用原 app.py"（需集成）

**缺失部分**（需从原 `app.py` 迁移）：
- 衬层编辑 UI 完整实现（表格模式/逐层模式）
- 温度曲线增强版绘图（探针/Colorbar）
- 计算结果页完整布局
- 收敛过程可视化

#### Kivy 移动端

📄 **`kivy_enhanced_widgets.py`** (新文件，650 行)  
增强组件库：
- ✅ `StepperRow`: +/- 步进器（含震动反馈）
- ✅ `LayerCard`: 可滑动删除的衬层卡片
- ✅ `SafetyMetricCard`: 安全状态指标卡（绿/橙/红）
- ✅ `AccordionSection`: 折叠参数分组
- ✅ `FAB`: Material Design 浮动操作按钮
- ✅ `trigger_haptic()`: Android 震动反馈

📄 **`kivy_enhanced_app.py`** (新文件，550 行)  
主应用框架：
- ✅ `InputScreen`: 参数输入屏（Accordion 折叠）
- ✅ `LayerManagerScreen`: 衬层管理独立页（列表+FAB）
- ✅ `ResultScreen`: 结果屏（安全状态语义色）
- ✅ `AppState`: 全局状态管理（单例）
- ⚠️ 温度曲线绘图未实现（需补充）
- ⚠️ 参数实际读取逻辑待完善（当前硬编码）

---

## 二、集成到现有项目的步骤

### 阶段 1：备份与环境准备（10 分钟）

```bash
# 1. 备份现有代码
cd F:\工作文件\水泥窑小组\python\cement-kiln-heat-transfer
cp app.py app_backup_$(date +%Y%m%d).py
cp kivy_app/main.py kivy_app/main_backup_$(date +%Y%m%d).py

# 2. 确认依赖
pip install streamlit>=1.30 plotly kivy>=2.3.0

# 3. 测试增强版（独立运行）
streamlit run streamlit_enhanced.py  # Web 端
python kivy_enhanced_app.py          # 移动端（桌面测试）
```

### 阶段 2：Streamlit Web 端集成（2-3 小时）

#### 2.1 迁移衬层编辑 UI

**任务**：将 `app.py` 的 `_view_layers()` 完整逻辑复制到 `streamlit_enhanced.py:_view_layers()`

**关键点**：
- 保留表格编辑模式（`st.data_editor`）
- 保留逐层编辑模式（含材料库选择）
- 添加智能验证调用（已在增强版中实现）

**文件位置**：
- 源代码：`app.py` 第 200-350 行（估计）
- 目标位置：`streamlit_enhanced.py` 第 450 行附近

#### 2.2 增强温度曲线

**任务**：用 `_build_figure_with_probe()` 替换原有的 Plotly 绘图

**改进点**：
- 固定 Colorbar（右侧独立坐标）
- 探针跟随（鼠标悬停显示数值）
- 界面标注箭头

**文件位置**：
- 增强版模板：`streamlit_enhanced.py` 第 280-340 行
- 原始代码：`app.py` 温度曲线绘图部分

#### 2.3 完善计算结果页

**任务**：复制原 `_view_results()` 的指标卡布局，保留收敛过程展示

**文件位置**：
- 源代码：`app.py` 结果页部分
- 目标位置：`streamlit_enhanced.py` 第 620 行附近（当前占位符）

#### 2.4 测试与切换

```bash
# 测试增强版
streamlit run streamlit_enhanced.py

# 确认无误后，替换主入口
mv app.py app_legacy.py
mv streamlit_enhanced.py app.py
```

### 阶段 3：Kivy 移动端集成（3-4 小时）

#### 3.1 参数实际读取

**任务**：将 `InputScreen` 的硬编码参数改为从 `StepperRow` 实际读取

**方法**：
```python
# 当前（硬编码）
params = KilnParams(T_gas=1250 + 273.15, ...)

# 改为（实际读取）
self.stepper_T_gas = StepperRow("烟气温度", "°C", 1250, 10, 500, 2000)
# ... 计算时 ...
params = KilnParams(
    T_gas=self.stepper_T_gas.value + 273.15,
    # ... 其他参数 ...
)
```

**文件位置**：
- `kivy_enhanced_app.py:InputScreen.__init__()` 第 80-120 行
- `kivy_enhanced_app.py:InputScreen._start_calculation()` 第 170-200 行

#### 3.2 衬层编辑页实现

**任务**：实现点击 `LayerCard` 后跳转的编辑页（输入层名/厚度/k系数）

**建议**：
- 新增 `LayerEditScreen`（参考 `InputScreen` 的 Accordion 布局）
- 使用 `StepperRow` 输入数值
- 保存时更新 `AppState.layers`

#### 3.3 温度曲线绘制

**任务**：在 `ResultScreen` 增加温度曲线 Tab

**方法**：
- 使用 Kivy `Graph` 组件（`kivy.garden.graph`）
- 或使用 `matplotlib` 嵌入（需 `kivy.garden.matplotlib`）
- 实现手势缩放/平移（`ScatterLayout`）

**参考资源**：
- Kivy Graph: https://github.com/kivy-garden/graph
- Matplotlib 嵌入: https://kivy.org/doc/stable/api-kivy.garden.matplotlib.html

#### 3.4 Android 打包测试

```bash
# 1. 配置 buildozer.spec
cp buildozer.spec buildozer_enhanced.spec
# 修改 source.main = kivy_enhanced_app.py

# 2. 打包
buildozer android debug

# 3. 安装到设备
adb install -r bin/*.apk

# 4. 测试关键功能
# - Accordion 折叠/展开
# - +/- 步进器震动反馈
# - 衬层卡片滑动删除
# - FAB 浮动按钮
# - 安全状态颜色显示
```

---

## 三、功能验证清单

### Streamlit Web 端

- [ ] **工况参数三档分组**
  - [ ] 必填/常用/高级分别折叠
  - [ ] 默认展开状态正确
  - [ ] 参数验证实时生效

- [ ] **工况模板系统**
  - [ ] 加载模板（参数+衬层）
  - [ ] 保存自定义模板
  - [ ] 模板持久化（JSON）

- [ ] **智能验证**
  - [ ] 厚度异常警告
  - [ ] 温度梯度提示
  - [ ] 导热系数合理性检查

- [ ] **历史对比**
  - [ ] 最多保留5条记录
  - [ ] 多项选择对比（2-3项）
  - [ ] 温度曲线叠加显示

- [ ] **温度曲线增强**
  - [ ] 固定 Colorbar 显示
  - [ ] 探针悬浮数值
  - [ ] 界面标注箭头

- [ ] **收敛过程**
  - [ ] 迭代历史曲线
  - [ ] 残差显示

### Kivy 移动端

- [ ] **Accordion 折叠**
  - [ ] 展开/折叠动画流畅
  - [ ] 单屏可见3-4个分组

- [ ] **+/- 步进器**
  - [ ] 增减按钮生效
  - [ ] 震动反馈触发（Android）
  - [ ] 手动输入范围限制

- [ ] **衬层管理页**
  - [ ] 列表显示所有衬层
  - [ ] FAB 添加新衬层
  - [ ] 滑动删除（震动反馈）
  - [ ] 点击编辑（跳转编辑页）

- [ ] **安全状态**
  - [ ] 外壁温度：绿(< 80)/橙(80-120)/红(> 120)
  - [ ] 热损失：绿(< 500)/橙(500-1000)/红(> 1000)
  - [ ] 左侧状态条颜色同步

- [ ] **手势交互**
  - [ ] 温度曲线缩放/平移
  - [ ] 列表滚动流畅

---

## 四、常见问题

### Q1: Streamlit 版本不兼容？

**症状**：`st.segmented_control` 未定义  
**解决**：
```python
# streamlit_enhanced.py 已内置兼容处理
seg = getattr(st, "segmented_control", None)
if seg is None:
    view = st.radio(...)  # 降级为 radio
```

### Q2: Kivy 震动无响应？

**原因**：需要 Android 权限  
**解决**：在 `buildozer.spec` 添加：
```ini
android.permissions = VIBRATE
```

### Q3: 自定义模板无法保存？

**原因**：文件写入权限不足  
**解决**：
```python
# 改为用户目录
from pathlib import Path
template_path = Path.home() / ".kiln_ht" / "custom_templates.json"
template_path.parent.mkdir(exist_ok=True)
```

### Q4: 历史对比内存占用过大？

**原因**：温度曲线数据点过多（N_total=1000）  
**优化**：
```python
# 存储前降采样
x_mm_sampled = x_mm[::10]  # 每10个点取1个
T_c_sampled = T_c[::10]
```

---

## 五、性能优化建议

### Streamlit

1. **缓存计算结果**
```python
@st.cache_data(ttl=600)
def solve_wall_cached(layers_json, params_json):
    layers = [Layer(**l) for l in json.loads(layers_json)]
    params = KilnParams(**json.loads(params_json))
    return solve_wall(layers, params)
```

2. **延迟加载历史对比**
```python
if view == "历史对比" and _ss.calc_history:
    # 仅在该 Tab 激活时加载
    _view_history_compare()
```

### Kivy

1. **RecycleView 虚拟滚动**（衬层 > 20 层时）
```python
from kivy.uix.recycleview import RecycleView

class LayerRecycleView(RecycleView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = [{"text": l["name"]} for l in APP_STATE.layers]
```

2. **Canvas 绘制优化**（温度曲线）
```python
# 限制节点数
if len(x_mm) > 100:
    step = len(x_mm) // 100
    x_mm = x_mm[::step]
    T_c = T_c[::step]
```

---

## 六、后续扩展方向

### 短期（1-2 周）

- [ ] 多语言支持（中文/英文切换）
- [ ] 导出功能增强（PDF 报告含历史对比）
- [ ] 云端同步（历史记录/自定义模板）

### 中期（1-2 月）

- [ ] 非稳态计算可视化（时间序列动画）
- [ ] 参数敏感性分析（一键批量计算）
- [ ] 协同编辑（多人共享工况配置）

### 长期（3-6 月）

- [ ] AI 辅助优化（基于历史数据推荐最优衬层）
- [ ] 3D 窑体模型可视化（Three.js / VTK）
- [ ] 与现场 DCS 数据对接（实时监控）

---

## 七、联系与支持

**技术问题**：请在项目 Issue 区提交  
**功能建议**：欢迎 Pull Request  
**设计反馈**：可直接修改 `GUI_REDESIGN_SPEC.md`

---

**文档版本**: v1.0  
**最后更新**: 2026-10-07  
**维护者**: Claude Code AI  
