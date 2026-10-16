# -*- coding: utf-8 -*-
"""
FastAPI RESTful API 服务入口（多层圆筒壁一维稳态传热）。

本地运行：
    uvicorn server:app --host 0.0.0.0 --port 8000
或直接：
    python server.py
Docker 运行：见 Dockerfile 与 README。

示例请求：
    curl -X POST http://localhost:8000/solve \\
         -H "Content-Type: application/json" \\
         -d '{"layers": [{"name":"纤维","thickness":0.15,"k":0.1},
                         {"name":"钢壳","thickness":0.012,"k":45}],
              "params": {"T_gas": 1523.15}}'
"""

from typing import List, Literal, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from kiln_ht.conductivity import ConductivityModel
from kiln_ht.config_schema import validate_kiln_params

from kiln_ht import (
    KilnParams,
    Layer,
    compute_temperature_curve,
    solve_wall,
    gas_fractions_for_mode,
    solve_kiln,
)

app = FastAPI(
    title="Cement Kiln Heat Transfer API",
    description="回转窑窑衬多层圆筒壁一维稳态传热计算服务",
    version="1.0.0",
)


# ============ 请求模型（Pydantic 校验） ============
class LayerIn(BaseModel):
    name: str = Field("层", description="层名称")
    thickness: float = Field(..., gt=0, description="厚度 (m)")
    k: Optional[float] = Field(None, gt=0, description="导热系数 (W/m·K)，兼容旧客户端")
    k_coef: Optional[List[float]] = Field(
        None, min_length=3, max_length=3, description="k(T)=a+bT+cT² 系数 (T 单位 ℃)")
    Rc: float = Field(0.0, ge=0, description="层间接触热阻 (m²·K/W)")
    thermal_conductivity: Optional[dict] = Field(None, description="v2 导热模型：constant/polynomial/table；插值表温度单位 K")


class KilnParamsIn(BaseModel):
    N_total: int = Field(100, ge=10, le=5000, description="温度曲线取点数")
    T_gas: float = Field(1523.15, gt=0, description="烟气温度 (K)")
    v_gas: float = Field(3.0, gt=0, description="烟气流速 (m/s)")
    L_char: float = Field(4.0, gt=0, description="窑内径 (m)")
    L_kiln: float = Field(60.0, gt=0, description="窑长 (m)")
    P_total: float = Field(1.01325, gt=0, description="窑内压力 (bar)")
    CO2: float = Field(0.20, ge=0, lt=1, description="CO2 体积分数")
    H2O: float = Field(0.08, ge=0, lt=1, description="H2O 体积分数")
    eps_wall: float = Field(0.85, gt=0, le=1, description="内壁发射率")
    T_env: float = Field(298.15, gt=0, description="环境温度 (K)")
    v_amb: float = Field(2.0, ge=0, description="环境风速 (m/s)")
    eps_shell: float = Field(0.85, gt=0, le=1, description="外壳发射率")
    radiation_model: Literal["leckner", "wsgg", "hitemp_grid"] = Field(
        "leckner", description="辐射模型；hitemp_grid 为带限实验模型，超出标定域将拒绝计算")
    gas_mode: Literal["combustion", "hot_air"] = Field(
        "combustion", description="气相模式：常规燃烧烟气或洁净热空气")


class SolveRequest(BaseModel):
    layers: List[LayerIn] = Field(..., min_length=1, description="衬里结构层")
    params: Optional[KilnParamsIn] = Field(None, description="工况参数（可省略）")


class AxialSolveRequest(SolveRequest):
    n_cells: int = Field(20, ge=1, le=5000, description="轴向控制体数量")
    mass_flow_kg_s: float = Field(10.0, gt=0)
    cp_gas_j_kg_k: float = Field(1150.0, gt=0)
    inlet_gas_temperature_k: Optional[float] = Field(None, gt=0)
    bed_inlet_temperature_k: Optional[float] = Field(None, gt=0)
    bed_mass_flow_kg_s: Optional[float] = Field(None, gt=0)
    cp_bed_j_kg_k: Optional[float] = Field(None, gt=0)
    gas_bed_h_w_m2_k: Optional[float] = Field(None, gt=0)
    wall_bed_h_w_m2_k: Optional[float] = Field(None, gt=0)
    gas_bed_area_per_length_m: Optional[float] = Field(None, ge=0)
    wall_bed_contact_per_length_m: Optional[float] = Field(None, ge=0)
    bed_geometry: Optional[dict] = Field(None, description="可选圆形截面床层几何辅助配置；默认关闭")
    bed_flow_direction: Literal["co-current", "counter-current"] = Field("counter-current")
    coupling_max_iterations: int = Field(100, ge=1)
    coupling_tolerance_k: float = Field(1.0e-5, gt=0)
    wall_iteration_mode: Literal["semi_nonlinear", "linearized"] = Field(
        "semi_nonlinear", description="轴向壁面求解：半非线性局部迭代或线性化对照模式")
    local_wall_tolerance_k: float = Field(1.0e-5, gt=0)
    local_wall_max_iterations: int = Field(48, ge=1, le=200)


def _to_domain(req: SolveRequest):
    """将 API 请求模型转换为核心计算的数据类。"""
    layers = []
    for l in req.layers:
        if l.k_coef is None:
            # 兼容旧客户端：用 k（若提供）或默认 1.0
            k = l.k if l.k is not None else 1.0
            k_coef = (k, 0.0, 0.0)
        else:
            k_coef = (l.k_coef[0], l.k_coef[1], l.k_coef[2])
        model = None
        tc = l.thermal_conductivity
        if tc is not None:
            mode = str(tc.get("mode", "constant")).lower()
            if mode == "constant":
                kval = float(tc.get("value", l.k if l.k is not None else k_coef[0]))
                model = ConductivityModel.constant(kval)
                k_coef = (kval, 0.0, 0.0)
            elif mode == "polynomial":
                model = ConductivityModel.polynomial(
                    tc.get("coefficients", l.k_coef or [l.k or 1.0, 0.0, 0.0]),
                    tc.get("temperature_unit", "degC"))
                k_coef = tuple(model.coefficients)
            elif mode == "table":
                model = ConductivityModel.table(tc.get("points", []))
            else:
                raise ValueError(f"不支持的导热系数模式: {mode}")
        layers.append(Layer(name=l.name, thickness=l.thickness,
                            k_coef=k_coef, Rc=l.Rc, conductivity_model=model))
    if req.params:
        values = req.params.model_dump(exclude={"gas_mode"})
        values.update(gas_fractions_for_mode(
            values["CO2"], values["H2O"], mode=req.params.gas_mode
        ))
        params = KilnParams(**values)
    else:
        params = KilnParams()
    validate_kiln_params(vars(params))
    return layers, params


# ============ 端点 ============
@app.get("/")
def root():
    return {
        "service": "cement-kiln-heat-transfer",
        "version": "1.0.0",
        "endpoints": ["/solve", "/axial-solve", "/temperature-curve", "/health"],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/solve")
def solve(req: SolveRequest):
    """求解稳态传热，返回单位长度热功率、热流密度与各分界面温度等。"""
    try:
        layers, params = _to_domain(req)
        result = solve_wall(layers, params).as_dict()
        result["model_semantics"] = {
            "result": "radial steady-state wall baseline",
            "three_phase_wall_model": "linearized network approximation (not returned by this endpoint)",
            "wsgg_status": "provisional",
            "industrial_design_or_absolute_thermal_stress_guarantee": False,
        }
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/axial-solve")
def axial_solve(req: AxialSolveRequest):
    """Return axial states, radial baseline wall solutions, and convergence diagnostics."""
    try:
        layers, params = _to_domain(req)
        solution = solve_kiln(
            layers,
            params,
            n_cells=req.n_cells,
            mass_flow_kg_s=req.mass_flow_kg_s,
            cp_gas_j_kg_k=req.cp_gas_j_kg_k,
            inlet_gas_temperature_k=req.inlet_gas_temperature_k,
            bed_inlet_temperature_k=req.bed_inlet_temperature_k,
            bed_mass_flow_kg_s=req.bed_mass_flow_kg_s,
            cp_bed_j_kg_k=req.cp_bed_j_kg_k,
            gas_bed_h_w_m2_k=req.gas_bed_h_w_m2_k,
            wall_bed_h_w_m2_k=req.wall_bed_h_w_m2_k,
            gas_bed_area_per_length_m=req.gas_bed_area_per_length_m,
            wall_bed_contact_per_length_m=req.wall_bed_contact_per_length_m,
            bed_flow_direction=req.bed_flow_direction,
            coupling_max_iterations=req.coupling_max_iterations,
            coupling_tolerance_k=req.coupling_tolerance_k,
            wall_iteration_mode=req.wall_iteration_mode,
            local_wall_tolerance_k=req.local_wall_tolerance_k,
            local_wall_max_iterations=req.local_wall_max_iterations,
            bed_geometry=req.bed_geometry,
        )
        return solution.as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail={
            "reason": str(exc),
            "diagnostics": {
                "iteration_count": None,
                "max_temperature_change_k": None,
                "max_energy_residual_w": None,
                "converged": False,
            },
        })


@app.post("/temperature-curve")
def temperature_curve(req: SolveRequest, n_points: int = 500):
    """求解并返回沿壁厚方向的温度分布曲线（x 单位 mm，T 单位 ℃）。"""
    if n_points < 10:
        raise HTTPException(status_code=400, detail="n_points 不能低于 10")
    try:
        layers, params = _to_domain(req)
        params.N_total = min(int(n_points), 5000)
        sol = solve_wall(layers, params)
        x_mm, T_c = compute_temperature_curve(layers, sol, n_points=params.N_total)
        return {
            "x_mm": list(x_mm),
            "T_c": list(T_c),
            "solution": sol.as_dict(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
