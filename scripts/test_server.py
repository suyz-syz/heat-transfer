# -*- coding: utf-8 -*-
"""FastAPI 服务进程内集成测试（使用 fastapi.testclient.TestClient）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 项目根目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
import server

client = TestClient(server.app)

# 1. 健康检查
r = client.get("/health")
assert r.status_code == 200 and r.json()["status"] == "ok"
print("[PASS] GET /health")

# 2. /solve POST（默认参数）
payload = {
    "layers": [
        {"name": "纤维", "thickness": 0.150, "k": 0.10},
        {"name": "轻质砖", "thickness": 0.100, "k": 0.30},
        {"name": "高铝砖", "thickness": 0.080, "k": 1.50},
        {"name": "钢壳", "thickness": 0.012, "k": 45.0},
    ],
}
r = client.post("/solve", json=payload)
assert r.status_code == 200
data = r.json()
assert data["Qprime"] > 0
assert data["T_w1"] > data["T_wN"]
assert data["T_iface"][-1] == data["T_wN"]  # 自洽性
print(f"[PASS] POST /solve: Q'={data['Qprime']:.1f} W/m, "
      f"T_w1={data['T_w1']-273.15:.1f}℃, T_wN={data['T_wN']-273.15:.1f}℃")

# 3. /solve POST（自定义参数覆盖）
r = client.post("/solve", json={
    "layers": [{"name": "钢壳", "thickness": 0.010, "k": 45.0}],
    "params": {"T_gas": 1773.15, "v_gas": 5.0, "P_total": 5.0, "CO2": 0.3, "H2O": 0.1},
})
assert r.status_code == 200
print("[PASS] POST /solve (params 覆盖)")

# 4. /temperature-curve POST
r = client.post("/temperature-curve", json=payload, params={"n_points": 200})
assert r.status_code == 200
data = r.json()
assert len(data["x_mm"]) == 200 and len(data["T_c"]) == 200
assert data["T_c"][0] > data["T_c"][-1]
print(f"[PASS] POST /temperature-curve: {len(data['x_mm'])} 点, "
      f"内壁{data['T_c'][0]:.1f}℃ → 外壁{data['T_c'][-1]:.1f}℃")

# 5. 参数校验：非法输入应返回 400
r = client.post("/solve", json={"layers": [{"name": "x", "thickness": 0.05, "k": -1.0}]})
assert r.status_code == 422          # pydantic 层拒绝负数导热系数
print("[PASS] 非法 k<0 -> 422 (pydantic 校验)")
r = client.post("/solve", json={"layers": [{"name": "x", "thickness": 0.05, "k": 1.0}],
                                "params": {"v_gas": 0.0}})
assert r.status_code in (400, 422)   # 核心校验抛 ValueError -> 400
print("[PASS] v_gas=0 -> 400/422")

print("=== ALL API TESTS PASSED ===")
