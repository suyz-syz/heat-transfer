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

from typing import List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from kiln_ht import (
    KilnParams,
    Layer,
    compute_temperature_curve,
    solve_wall,
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


class KilnParamsIn(BaseModel):
    N_total: int = Field(100, ge=10, le=5000, description="温度曲线取点数")
    T_gas: float = Field(1523.15, gt=0, description="烟气温度 (K)")
    v_gas: float = Field(3.0, gt=0, description="烟气流速 (m/s)")
    L_char: float = Field(4.0, gt=0, description="窑内径 (m)")
    L_kiln: float = Field(60.0, gt=0, description="窑长 (m)")
    P_total: float = Field(1.01325, gt=0, description="窑内压力 (bar)")
    CO2: float = Field(0.20, gt=0, lt=1, description="CO2 体积分数")
    H2O: float = Field(0.08, gt=0, lt=1, description="H2O 体积分数")
    eps_wall: float = Field(0.85, gt=0, le=1, description="内壁发射率")
    T_env: float = Field(298.15, gt=0, description="环境温度 (K)")
    v_amb: float = Field(2.0, ge=0, description="环境风速 (m/s)")
    eps_shell: float = Field(0.85, gt=0, le=1, description="外壳发射率")


class SolveRequest(BaseModel):
    layers: List[LayerIn] = Field(..., min_length=1, description="衬里结构层")
    params: Optional[KilnParamsIn] = Field(None, description="工况参数（可省略）")


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
        layers.append(Layer(name=l.name, thickness=l.thickness,
                            k_coef=k_coef, Rc=l.Rc))
    params = KilnParams(**req.params.model_dump()) if req.params else KilnParams()
    return layers, params


# ============ 端点 ============
@app.get("/")
def root():
    return {
        "service": "cement-kiln-heat-transfer",
        "version": "1.0.0",
        "endpoints": ["/solve", "/temperature-curve", "/health"],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/solve")
def solve(req: SolveRequest):
    """求解稳态传热，返回单位长度热功率、热流密度与各分界面温度等。"""
    try:
        layers, params = _to_domain(req)
        return solve_wall(layers, params).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
