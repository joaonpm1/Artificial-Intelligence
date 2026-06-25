import json
import random
from datetime import datetime, timedelta

CITY_JSON = "input/city.json"
OUT_TAXIS = "input/taxis.json"
OUT_PEDIDOS = "input/pedidos.json"


def weighted_choice(items):
    # items = [(obj, weight), ...]
    total = sum(w for _, w in items)
    r = random.random() * total
    acc = 0.0
    for obj, w in items:
        acc += w
        if r <= acc:
            return obj
    return items[-1][0]

def load_zones(city_path):
    with open(city_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    zones = [z["id"] for z in data]
    neighbors = {z["id"]: list(z.get("accessible_zones", [])) for z in data}
    traffic = {z["id"]: z.get("traffic_level", "medium") for z in data}
    station = {z["id"]: bool(z.get("station", False)) for z in data}
    return zones, neighbors, traffic, station

import random

def calc_autonomia_combustivel_km(nivel_l: float, consumo_l_100km: float) -> float:
    return (nivel_l / max(consumo_l_100km, 0.1)) * 100.0

def calc_autonomia_bateria_km(nivel_kwh: float, consumo_kwh_100km: float) -> float:
    return (nivel_kwh / max(consumo_kwh_100km, 0.1)) * 100.0

def generate_taxis(n_taxis, zones, traffic_level):
    taxis = []

    # Distribuição por tipo (ajusta se quiseres)
    tipo_dist = [("diesel", 0.45), ("hibrido", 0.30), ("eletrico", 0.25)]

    # Mais táxis em zonas "high"
    zone_weights = []
    for z in zones:
        tl = traffic_level.get(z, "medium")
        w = 3.0 if tl == "high" else (2.0 if tl == "medium" else 1.0)
        zone_weights.append((z, w))

    def weighted_choice(items):
        total = sum(w for _, w in items)
        r = random.random() * total
        acc = 0.0
        for obj, w in items:
            acc += w
            if r <= acc:
                return obj
        return items[-1][0]

    for i in range(1, n_taxis + 1):
        tipo = weighted_choice(tipo_dist)
        pos = weighted_choice(zone_weights)

        capacidade = random.choice([4, 4, 4, 6])
        velocidade = random.choice([55, 60, 65])

        if tipo == "eletrico":
            # Valores tipo os teus: 45–55 kWh, 16–20 kWh/100km
            cap_bat = random.choice([45.0, 50.0, 55.0])
            consumo = random.choice([16.0, 17.0, 18.0, 19.0, 20.0])

            # não começa sempre a 100% (mais realista)
            nivel_bat = round(cap_bat * random.uniform(0.70, 1.00), 1)

            autonomia_max = round(calc_autonomia_bateria_km(cap_bat, consumo), 1)
            autonomia_atual = round(calc_autonomia_bateria_km(nivel_bat, consumo), 1)

            taxi = {
                "id": f"T{i}",
                "tipo": "eletrico",
                "posicao": pos,
                "autonomia_max_km": autonomia_max,
                "autonomia_atual_km": autonomia_atual,
                "velocidade": random.choice([50, 55, 60]),
                "capacidade": capacidade,
                "custo_km": round(random.uniform(0.17, 0.20), 2),
                "consumo_100km": consumo,  # kWh/100km
                "capacidade_bateria_kwh": cap_bat,
                "nivel_bateria_kwh": nivel_bat,
                "capacidade_deposito_l": None,
                "nivel_deposito_l": None,
                "tempo_carga": random.choice([25, 30, 35, 40])
            }

        elif tipo == "hibrido":
            # Depósito 38–45 L, consumo 6–7.5 L/100km (cidade/misto)
            cap_dep = random.choice([38.0, 40.0, 43.0, 45.0])
            consumo = random.choice([6.0, 6.5, 7.0, 7.5])

            # nível inicial 60–100%
            nivel_dep = round(cap_dep * random.uniform(0.60, 1.00), 1)

            autonomia_max = round(calc_autonomia_combustivel_km(cap_dep, consumo), 1)
            autonomia_atual = round(calc_autonomia_combustivel_km(nivel_dep, consumo), 1)

            taxi = {
                "id": f"T{i}",
                "tipo": "hibrido",
                "posicao": pos,
                "autonomia_max_km": autonomia_max,
                "autonomia_atual_km": autonomia_atual,
                "velocidade": velocidade,
                "capacidade": capacidade,
                "custo_km": round(random.uniform(0.20, 0.26), 2),
                "consumo_100km": consumo,  # L/100km
                "capacidade_bateria_kwh": None,
                "nivel_bateria_kwh": None,
                "capacidade_deposito_l": cap_dep,
                "nivel_deposito_l": nivel_dep,
                "tempo_carga": 0
            }

        else:  # diesel
            # Depósito 40–55 L, consumo 7–9 L/100km (mais realista em cidade)
            cap_dep = random.choice([40.0, 45.0, 50.0, 55.0])
            consumo = random.choice([7.0, 7.5, 8.0, 8.5, 9.0])

            nivel_dep = round(cap_dep * random.uniform(0.60, 1.00), 1)

            autonomia_max = round(calc_autonomia_combustivel_km(cap_dep, consumo), 1)
            autonomia_atual = round(calc_autonomia_combustivel_km(nivel_dep, consumo), 1)

            taxi = {
                "id": f"T{i}",
                "tipo": "diesel",
                "posicao": pos,
                "autonomia_max_km": autonomia_max,
                "autonomia_atual_km": autonomia_atual,
                "velocidade": velocidade,
                "capacidade": capacidade,
                "custo_km": round(random.uniform(0.22, 0.30), 2),
                "consumo_100km": consumo,  # L/100km
                "capacidade_bateria_kwh": None,
                "nivel_bateria_kwh": None,
                "capacidade_deposito_l": cap_dep,
                "nivel_deposito_l": nivel_dep,
                "tempo_carga": 0
            }

        taxis.append(taxi)

    return taxis


def generate_pedidos(n_pedidos, zones, neighbors, station, day="2025-01-10", seed=123):
    random.seed(seed)

    pedidos = []
    base_date = datetime.fromisoformat(day + " 00:00:00")

    # pesos por hora (picos manhã/tarde)
    hour_weights = []
    for h in range(24):
        if 7 <= h <= 10:
            w = 4.0
        elif 17 <= h <= 20:
            w = 4.5
        elif 11 <= h <= 16:
            w = 2.0
        elif 0 <= h <= 6:
            w = 0.3
        else:
            w = 1.0
        hour_weights.append((h, w))

    # pesos para escolher origens (estações mais prováveis)
    origin_weights = []
    for z in zones:
        w = 3.0 if station.get(z, False) else 1.0
        origin_weights.append((z, w))

    for i in range(1, n_pedidos + 1):
        h = weighted_choice(hour_weights)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        hora_pedido = base_date + timedelta(hours=h, minutes=minute, seconds=second)

        origem = weighted_choice(origin_weights)

        # destino: preferir destinos acessíveis; se não houver, escolhe qualquer diferente
        opts = neighbors.get(origem, [])
        if opts:
            destino = random.choice(opts)
        else:
            destino = random.choice([z for z in zones if z != origem])

        # passageiros
        n_pass = weighted_choice([(1, 0.45), (2, 0.30), (3, 0.15), (4, 0.10)])

        # premium
        prioridade = 1 if random.random() < 0.15 else 0

        # prefere verde
        prefere_verde = (random.random() < 0.40)

        pedidos.append({
            "id": f"P{i}",
            "origem": origem,
            "destino": destino,
            "n_passageiros": n_pass,
            "prioridade": prioridade,
            "hora_pedido": hora_pedido.strftime("%Y-%m-%d %H:%M:%S"),
            "prefere_verde": prefere_verde
        })

    # ordenar por data/hora e premium primeiro no mesmo instante
    pedidos.sort(key=lambda p: (p["hora_pedido"], -p["prioridade"]))

    # Renumerar IDs por ordem temporal (P1, P2, ...)
    for i, p in enumerate(pedidos, start=1):
        p["id"] = f"P{i}"

    return pedidos

if __name__ == "__main__":
    zones, neighbors, traffic, station = load_zones(CITY_JSON)

    # Ajusta aqui os números
    taxis = generate_taxis(n_taxis=4, zones=zones, traffic_level=traffic)
    pedidos = generate_pedidos(n_pedidos=10, zones=zones, neighbors=neighbors, station=station, day="2025-01-10", seed=42)

    with open(OUT_TAXIS, "w", encoding="utf-8") as f:
        json.dump(taxis, f, ensure_ascii=False, indent=2)

    with open(OUT_PEDIDOS, "w", encoding="utf-8") as f:
        json.dump(pedidos, f, ensure_ascii=False, indent=2)

    print(f"✅ Gerado {OUT_TAXIS} com {len(taxis)} táxis")
    print(f"✅ Gerado {OUT_PEDIDOS} com {len(pedidos)} pedidos")
