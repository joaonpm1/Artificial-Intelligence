import json
import os
import copy
import random
from datetime import timedelta

from map.city_map import CityMap
from models.taxi import Taxi
from models.pedido import Pedido
from search.astar_taxi import AStarTaxi
from search.ucs_taxi import UCSTaxi
from collections import Counter

# ==========================
#   DEBUG
# ==========================
DEBUG = False  # True para ver detalhes por pedido

def log_debug(msg: str):
    if DEBUG:
        print(msg)


METEO_EMOJI = {
    "sun": "☀️ Sol",
    "rain": "🌧️ Chuva",
    "fog": "🌫️ Nevoeiro",
    "storm": "⛈️ Tempestade"
}

def resumo_meteorologia_trajeto(graph, path):
    c = Counter()
    for i in range(len(path) - 1):
        edge = graph[path[i]][path[i + 1]]
        c[edge.get("weather", "sun")] += 1
    return c



# ==========================
#   (TXT)
# ==========================
def log_write(f, msg: str):
    """Escreve uma linha no ficheiro de log e faz flush."""
    if f is None:
        return
    f.write(msg + "\n")
    f.flush()

def log_header(f, titulo: str):
    log_write(f, "")
    log_write(f, "=" * 80)
    log_write(f, titulo.center(80))
    log_write(f, "=" * 80)



CO2_KG_POR_LITRO = {
    "diesel": 2.68,
    "hibrido": 2.00,
    "eletrico": 0.0
}

# Baselines (para comparação)co2 poupado em preferencia verde
BASELINE_DIESEL_CONSUMO_100KM = 5.5
BASELINE_DIESEL_CO2_KG_POR_LITRO = 2.68


# ==========================
#   LOADERS
# ==========================
def carregar_taxis(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    taxis = []
    for t in data:
        taxis.append(Taxi(
            id=t["id"],
            tipo=t["tipo"],
            posicao=t["posicao"],
            autonomia_max_km=t["autonomia_max_km"],
            autonomia_atual_km=t["autonomia_atual_km"],
            velocidade=t["velocidade"],
            capacidade=t["capacidade"],
            custo_km=t["custo_km"],
            consumo_100km=t.get("consumo_100km"),
            capacidade_bateria_kwh=t.get("capacidade_bateria_kwh"),
            nivel_bateria_kwh=t.get("nivel_bateria_kwh"),
            capacidade_deposito_l=t.get("capacidade_deposito_l"),
            nivel_deposito_l=t.get("nivel_deposito_l"),
            tempo_carga=t.get("tempo_carga", 0)
        ))
    print(f"[DEBUG] {len(taxis)} táxis carregados")
    return taxis

def carregar_pedidos(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pedidos = []
    for p in data:
        pedidos.append(Pedido(
            id=p["id"],
            origem=p["origem"],
            destino=p["destino"],
            n_passageiros=p["n_passageiros"],
            prioridade=p["prioridade"],
            hora_pedido=p["hora_pedido"],
            prefere_verde=p.get("prefere_verde", False)
        ))
    print(f"[DEBUG] {len(pedidos)} pedidos carregados")
    return pedidos

# ==========================
#   SEARCHER FACTORY
# ==========================
def make_searcher(graph, algoritmo: str):
    if algoritmo == "astar":
        return AStarTaxi(graph)
    if algoritmo == "ucs":
        return UCSTaxi(graph)
    raise ValueError("algoritmo tem de ser 'astar' ou 'ucs'")

# ==========================
#   STATS / ENERGY HELPERS
# ==========================
def quilometros_reais(graph, path):
    km = 0.0
    for i in range(len(path) - 1):
        edge = graph[path[i]][path[i + 1]]
        km += edge.get("distance", edge.get("weight", 0.0))
    return km

def energia_gasta_com_trafego(graph, path, consumo_100km):
    if not consumo_100km:
        return 0.0

    energia = 0.0
    for i in range(len(path) - 1):
        edge = graph[path[i]][path[i + 1]]
        distancia = edge.get("distance", edge.get("weight", 0.0))
        traf = edge.get("traffic_factor", 1.0)
        weather = edge.get("weather_factor", 1.0)
        km_equiv = distancia * traf * weather
        energia += km_equiv * consumo_100km / 100.0
    return energia

# ==========================
#   ESTAÇÕES / CARREGAR
# ==========================
def estacoes_disponiveis(graph):
    return [node for node, data in graph.nodes(data=True) if data.get("station", False)]

def estacao_mais_proxima(taxi, graph, algoritmo="astar"):
    estacoes = estacoes_disponiveis(graph)
    if not estacoes:
        log_debug("[DEBUG] Nenhuma estação disponível.")
        return None

    searcher = make_searcher(graph, algoritmo)

    melhor_custo = float("inf")
    melhor_estacao = None

    for estacao in estacoes:
        path, cost, _ = searcher.search(taxi.posicao, estacao)
        if path is None:
            continue
        if cost < melhor_custo:
            melhor_custo = cost
            melhor_estacao = estacao

    if melhor_estacao is None:
        return None

    return melhor_estacao, melhor_custo

def tentar_recarregar_taxi(taxi, hora_inicio, graph, estacoes_estado, flog=None, algoritmo="astar"):
    """Agenda recarga para 1 táxi a partir de hora_inicio (normalmente taxi.livre_apos)."""
    if not taxi.precisa_recarregar():
        return False, 0.0, 0.0, 0.0

    resultado = estacao_mais_proxima(taxi, graph, algoritmo=algoritmo)
    if resultado is None:
        log_write(flog, f"[{hora_inicio.strftime('%H:%M')}] RECARGA - {taxi.id} | Sem estação disponível.")
        return False, 0.0, 0.0, 0.0

    estacao_id, cost_estacao = resultado

    velocidade = taxi.velocidade if taxi.velocidade > 0 else 1.0
    tempo_min_ate = (cost_estacao / velocidade) * 60.0

    hora_chegada = hora_inicio + timedelta(minutes=tempo_min_ate)

    livre_apos_estacao = estacoes_estado.get(estacao_id)  # datetime ou None
    inicio_carga = hora_chegada
    espera_min = 0.0

    if livre_apos_estacao is not None and hora_chegada < livre_apos_estacao:
        espera_min = (livre_apos_estacao - hora_chegada).total_seconds() / 60.0
        inicio_carga = livre_apos_estacao

    tempo_carga_min = (taxi.tempo_carga or 0) if taxi.tipo == "eletrico" else 5.0
    hora_fim = inicio_carga + timedelta(minutes=tempo_carga_min)

    # reservar estação
    estacoes_estado[estacao_id] = hora_fim

    # atualizar táxi
    taxi.posicao = estacao_id
    taxi.livre_apos = hora_fim
    taxi.disponivel = False
    taxi.abastecer()

    # logs
    tipo = (taxi.tipo or "").strip().lower()

    if tipo == "eletrico":
        titulo = "🔋 RECARGA"
    else:
        titulo = "⛽ ABASTECIMENTO (BOMBA)"

    log_write(flog, "") 
    log_write(flog, f"[{hora_inicio.strftime('%H:%M')}] {titulo} (auto pós-viagem) - {taxi.id}")
    log_write(flog, f"    • Estação: {estacao_id}")
    log_write(flog, f"    • Deslocação: {cost_estacao:.2f} km | {tempo_min_ate:.1f} min")
    if espera_min > 0:
        log_write(flog, f"    • Espera: {espera_min:.1f} min (ocupada)")
    log_write(flog, f"    • Carga/abastecimento: {tempo_carga_min:.1f} min")
    log_write(flog, f"    • Livre às: {hora_fim.strftime('%H:%M:%S')}")
    log_write(flog, "  --------------------------------------------")
    log_write(flog, "")

    return True, tempo_min_ate, espera_min, tempo_carga_min

def carros_a_carregar(taxis, hora_atual, graph, estacoes_estado, flog=None, algoritmo="astar"):
    for taxi in taxis:
        # Só manda carregar táxis que estejam livres neste momento
        if taxi.livre_apos is not None and hora_atual < taxi.livre_apos:
            continue

        if not taxi.precisa_recarregar():
            continue

        resultado = estacao_mais_proxima(taxi, graph, algoritmo=algoritmo)
        if resultado is None:
            print(f"[⚠️  {taxi.id}] Sem estação disponível para recarregar.")
            continue

        estacao_id, cost_estacao = resultado

        # Tempo até chegar à estação
        velocidade = taxi.velocidade if taxi.velocidade > 0 else 1.0
        tempo_min_ate = (cost_estacao / velocidade) * 60.0

        # Hora base = agora (porque garantimos que está livre)
        hora_base = hora_atual
        hora_chegada = hora_base + timedelta(minutes=tempo_min_ate)

        # Ver se a estação está ocupada
        livre_apos_estacao = estacoes_estado.get(estacao_id)  # datetime ou None

        inicio_carga = hora_chegada
        espera_min = 0.0

        if livre_apos_estacao is not None and hora_chegada < livre_apos_estacao:
            espera_min = (livre_apos_estacao - hora_chegada).total_seconds() / 60.0
            inicio_carga = livre_apos_estacao  # espera até estar livre

        # Tempo de carga/abastecimento
        tempo_carga_min = (taxi.tempo_carga or 0) if taxi.tipo == "eletrico" else 5.0
        hora_fim = inicio_carga + timedelta(minutes=tempo_carga_min)

        # Marcar estação ocupada até hora_fim
        estacoes_estado[estacao_id] = hora_fim

        # Atualizar estado do táxi: vai para a estação e fica indisponível até terminar
        taxi.posicao = estacao_id
        taxi.livre_apos = hora_fim
        taxi.disponivel = False

        # Repor energia (considera que a reposição só fica efetiva após o carregamento)
        taxi.abastecer()

        print()
        print(f"🔋 {taxi.id} vai recarregar")
        print(f"   • Estação: {estacao_id}")
        print(f"   • Distância até à estação: {cost_estacao:.2f} km")
        print(f"   • Tempo até à estação: {tempo_min_ate:.1f} min")
        if espera_min > 0:
            print(f"   • Espera na estação: {espera_min:.1f} min (estação ocupada)")
        print(f"   • Tempo de carga/abastecimento: {tempo_carga_min:.1f} min")
        print(f"   • Voltará a estar operacional às {hora_fim.strftime('%H:%M:%S')}")
        print()

        log_write(flog, f"[{hora_atual.strftime('%H:%M')}] RECARGA - {taxi.id}")
        log_write(flog, f"  Estação: {estacao_id}")
        log_write(flog, f"  Distância até estação: {cost_estacao:.2f} km | Tempo até estação: {tempo_min_ate:.1f} min")
        if espera_min > 0:
            log_write(flog, f"  Espera na estação: {espera_min:.1f} min (ocupada)")
        log_write(flog, f"  Tempo carga/abastecimento: {tempo_carga_min:.1f} min")
        log_write(flog, f"  Livre às: {hora_fim.strftime('%H:%M:%S')}")




def print_estado_taxis(taxis):
    print("\n" + "=" * 85)
    print(" ESTADO DOS TÁXIS ".center(85, "="))
    print("=" * 85)

    print(f"{'Táxi':<6} {'Posição':<15} {'Autonomia':<12} {'Depósito/Bat':<15} {'Modo':<12} {'Livre após'}")
    print("-" * 85)

    for t in taxis:
        if t.tipo in ("hibrido", "diesel"):
            energia = f"{(t.nivel_deposito_l or 0):.1f} L"
        else:
            energia = f"{(t.nivel_bateria_kwh or 0):.1f} kWh"

        livre = t.livre_apos.strftime("%H:%M:%S") if t.livre_apos else "-"

        if t.disponivel:
            modo = "Livre"
        else:
            if t.precisa_recarregar():
                modo = "Carregar"
            else:
                modo = "Ocupado"

        print(f"{t.id:<6} {t.posicao:<15} {t.autonomia_atual_km:>7.1f} km   "
              f"{energia:<15} {modo:<12} {livre}")

    print("=" * 85 + "\n")

# ==========================
#   ESCOLHER MELHOR TÁXI (A* ou UCS)
# ==========================
def escolher_melhor_taxi(pedido, taxis, graph, algoritmo="astar"):
    searcher = make_searcher(graph, algoritmo)

    # grafo sem tráfego para calcular km físicos mínimos (stats)
    city_map_instance = CityMap("input/city.json")
    graph_sem_trafego = city_map_instance.load_city(0)

    melhor_taxi = None
    melhor_custo = float("inf")
    melhor_score = float("inf")
    melhor_path_to = None
    melhor_path_trip = None
    melhor_expanded = 0

    for taxi in taxis:

        # Preferência verde: só considera elétrico e híbrido
        if pedido.prefere_verde and taxi.tipo not in ("eletrico", "hibrido"):
            continue

        # ocupado?
        if taxi.livre_apos is not None and pedido.hora_pedido < taxi.livre_apos:
            continue

        taxi.disponivel = True

        if taxi.capacidade < pedido.n_passageiros:
            continue

        path1, cost1, exp1 = searcher.search(taxi.posicao, pedido.origem)
        path2, cost2, exp2 = searcher.search(pedido.origem, pedido.destino)

        if path1 is None or path2 is None:
            continue

        km_necessarios_equiv = cost1 + cost2

        if km_necessarios_equiv > taxi.autonomia_atual_km:
            continue

        # km físicos para stats/debug
        km_reais_to = quilometros_reais(graph_sem_trafego, path1)
        km_reais_trip = quilometros_reais(graph_sem_trafego, path2)
        _km_min_total = km_reais_to + km_reais_trip

        # custo real €
        custo_total = km_necessarios_equiv * taxi.custo_km

        # tempo até ao cliente
        velocidade = taxi.velocidade if taxi.velocidade > 0 else 1.0
        tempo_min_to = (cost1 / velocidade) * 60.0

        # prioridade
        if pedido.is_premium:
            alpha, beta = 0.7, 0.3
        else:
            alpha, beta = 0.4, 0.6

        score = alpha * tempo_min_to + beta * custo_total


        if score < melhor_score:
            melhor_score = score
            melhor_custo = custo_total
            melhor_taxi = taxi
            melhor_path_to = path1
            melhor_path_trip = path2
            melhor_expanded = exp1 + exp2

    return melhor_taxi, melhor_path_to, melhor_path_trip, melhor_custo, melhor_expanded

# ==========================
#   APLICAR VIAGEM (energia, autonomia, tempo, prints)
# ==========================
def aplicar_viagem(pedido, taxi, path_to, path_trip, graph):
    # km equivalentes (trânsito+meteo)
    km_equiv_total = 0.0
    for i in range(len(path_to) - 1):
        km_equiv_total += graph[path_to[i]][path_to[i + 1]]["weight"]
    for i in range(len(path_trip) - 1):
        km_equiv_total += graph[path_trip[i]][path_trip[i + 1]]["weight"]

    # km físicos reais
    km_reais_to = quilometros_reais(graph, path_to)
    km_reais_trip = quilometros_reais(graph, path_trip)
    km_reais_total = km_reais_to + km_reais_trip

    # energia gasta
    path_total = path_to + path_trip[1:]
    energia_gasta = energia_gasta_com_trafego(graph, path_total, taxi.consumo_100km)

     # --------------------------
    # CO2 estimado (kg)
    # --------------------------
    co2_kg = 0.0
    if taxi.tipo in ("diesel", "hibrido"):
        # aqui "energia_gasta" está em litros (porque consumo_100km é L/100km)
        litros = energia_gasta
        co2_kg = litros * CO2_KG_POR_LITRO.get(taxi.tipo, 0.0)
    elif taxi.tipo == "eletrico":
        # emissões locais = 0
        co2_kg = 0.0

    # --------------------------
    # Baseline para pedidos "verdes":
    # quanto CO2 emitiria se fosse feito por um diesel de referência?
    # --------------------------
    co2_baseline_green_kg = 0.0
    if pedido.prefere_verde:
        litros_baseline = energia_gasta_com_trafego(graph, path_total, BASELINE_DIESEL_CONSUMO_100KM)
        co2_baseline_green_kg = litros_baseline * BASELINE_DIESEL_CO2_KG_POR_LITRO



    autonomia_antes_km = taxi.autonomia_atual_km

    if taxi.consumo_100km is not None and energia_gasta > 0:
        if taxi.tipo == "eletrico":
            antes = taxi.nivel_bateria_kwh
            taxi.nivel_bateria_kwh = max(0.0, (taxi.nivel_bateria_kwh or 0.0) - energia_gasta)
            taxi.autonomia_atual_km = (taxi.nivel_bateria_kwh / taxi.consumo_100km) * 100.0

        

        elif taxi.tipo in ("hibrido", "diesel"):
            antes = taxi.nivel_deposito_l
            taxi.nivel_deposito_l = max(0.0, (taxi.nivel_deposito_l or 0.0) - energia_gasta)
            taxi.autonomia_atual_km = (taxi.nivel_deposito_l / taxi.consumo_100km) * 100.0

            
    
    print(f"Táxi escolhido: {taxi.id} ({taxi.tipo})")

    if taxi.tipo == "eletrico":
        print(
            f"Bateria: {antes:.2f} kWh -> {taxi.nivel_bateria_kwh:.2f} kWh "
            f"(capacidade máx: {taxi.capacidade_bateria_kwh:.2f} kWh)"
        )
    elif taxi.tipo in ("hibrido", "diesel"):
        print(
            f"Depósito: {antes:.2f} L -> {taxi.nivel_deposito_l:.2f} L "
            f"(capacidade máx: {taxi.capacidade_deposito_l:.2f} L)"
        )

    print("Caminho táxi -> origem:", " -> ".join(path_to))
    print("Caminho origem -> destino:", " -> ".join(path_trip))
    print(f"Distância física total: {km_reais_total:.2f} km")
    print(
        f"Autonomia (Tendo em conta condiçoes externas): {autonomia_antes_km:.2f} km -> "
        f"{taxi.autonomia_atual_km:.2f} km"
    )

    taxi.posicao = pedido.destino
    print(f"Nova posição do táxi {taxi.id}: {taxi.posicao}")

    # tempo total
    velocidade = taxi.velocidade if taxi.velocidade > 0 else 1.0
    tempo_min = (km_equiv_total / velocidade) * 60.0
    if taxi.tipo == "eletrico" and taxi.tempo_carga:
        tempo_min += taxi.tempo_carga

    taxi.livre_apos = pedido.hora_pedido + timedelta(minutes=tempo_min)
    taxi.disponivel = False

    print(
        f"Táxi {taxi.id} ficará livre às {taxi.livre_apos.strftime('%H:%M:%S')} "
        f"(viagem de ~{tempo_min:.1f} min)"
    )

    # para métricas: km vazio e km com passageiro
    return km_reais_to, km_reais_trip, tempo_min, co2_kg, co2_baseline_green_kg


# ==========================
#   SIMULAÇÃO (uma por algoritmo)
# ==========================
def run_simulation(algoritmo: str, city_path: str, taxis_path: str, pedidos_path: str, flog=None):
    city = CityMap(city_path)

    taxis0 = carregar_taxis(taxis_path)
    pedidos0 = carregar_pedidos(pedidos_path)
    pedidos0.sort(key=lambda p: (p.hora_pedido, 0 if p.is_premium else 1))

    taxis = copy.deepcopy(taxis0)
    pedidos = copy.deepcopy(pedidos0)
    log_header(flog, f"LOG DA SIMULAÇÃO - {algoritmo.upper()}")
    log_write(flog, f"Total táxis: {len(taxis0)} | Total pedidos: {len(pedidos0)}")

    # ===============================
    # Estatísticas por táxi    
    # ===============================
    stats = {}
    for t in taxis:
        stats[t.id] = {
            "tipo": t.tipo,
            "km_vazio": 0.0,
            "km_pass": 0.0,
            "custo_total": 0.0,
            "co2_kg": 0.0,
            "abastecimentos": 0,
            "min_a_andar": 0.0,
            "min_parado": 0.0,
        }



    # Estação -> datetime quando fica livre (None = livre)
    estacoes_estado = {}


    atendidos = 0
    falhados = 0
    custo_total = 0.0
    tempo_resposta_total = 0.0
    expanded_total = 0

    km_vazio_total = 0.0
    km_passageiro_total = 0.0
    co2_total_kg = 0.0
    co2_green_real_kg = 0.0
    co2_green_baseline_diesel_kg = 0.0



    for pedido in pedidos:
        # 🔄 Atualizar estado temporal dos táxis
        for t in taxis:
            if t.livre_apos is not None and pedido.hora_pedido >= t.livre_apos:
                t.livre_apos = None
                t.disponivel = True

        print("\n" + "=" * 55)
        print(f"PEDIDO {pedido.id}".center(55))
        print("=" * 55)
        print(f"Hora do pedido: {pedido.hora_pedido.strftime('%Y-%m-%d %H:%M')}")
        print(f"Tipo: {'premium' if pedido.is_premium else 'normal'}")
        print(f"Origem -> Destino: {pedido.origem} -> {pedido.destino}")
       
        print("-" * 55)

        graph = city.load_city(1, hora=pedido.hora_pedido)

        log_header(flog, f"PEDIDO {pedido.id} - {pedido.hora_pedido.strftime('%Y-%m-%d %H:%M')}")
        log_write(flog, f"Tipo: {'premium' if pedido.is_premium else 'normal'} | Prefere verde: {pedido.prefere_verde}")
        log_write(flog, f"Origem -> Destino: {pedido.origem} -> {pedido.destino} | Passageiros: {pedido.n_passageiros}")

        
        # Inicializar estado das estações (na 1ª vez que aparecem)
        for node, data in graph.nodes(data=True):
            if data.get("station", False) and node not in estacoes_estado:
                estacoes_estado[node] = None
  

        taxi, path_to, path_trip, custo, expanded = escolher_melhor_taxi(pedido, taxis, graph, algoritmo=algoritmo)

        if taxi is None:
            falhados += 1
            print("Nenhum táxi consegue satisfazer o pedido.")
            log_write(flog, "RESULTADO: FALHADO (nenhum táxi consegue satisfazer o pedido).")
            continue

        searcher = make_searcher(graph, algoritmo)
        _, cost_to_equiv, _ = searcher.search(taxi.posicao, pedido.origem)

        tempo_resposta_pedido = (cost_to_equiv / max(taxi.velocidade, 1.0)) * 60.0

        # ===== Meteorologia REAL do trajeto =====
        path_total = path_to + path_trip[1:]
        meteo_contagem = resumo_meteorologia_trajeto(graph, path_total)

        # Terminal
        print("Meteorologia no trajeto:")
        for cond, n in meteo_contagem.items():
            print(f"  {METEO_EMOJI.get(cond, cond)} ({n} arestas)")
        print()

        # TXT (log)
        log_write(flog, "Meteorologia no trajeto:")
        for cond, n in meteo_contagem.items():
            log_write(flog, f"  - {METEO_EMOJI.get(cond, cond)}: {n} arestas")


        # tempo de resposta = tempo taxi->origem (com o algoritmo atual)
        searcher = make_searcher(graph, algoritmo)
        _, cost_to_equiv, _ = searcher.search(taxi.posicao, pedido.origem)
        tempo_resposta_total += (cost_to_equiv / max(taxi.velocidade, 1.0)) * 60.0

        atendidos += 1
        custo_total += custo
        expanded_total += expanded

        if DEBUG:
            print(f"[DEBUG][{algoritmo}] {pedido.id} -> taxi={taxi.id} custo={custo:.2f} expanded={expanded}")

          # ===== Estado ANTES da viagem (para log) =====
        autonomia_antes = taxi.autonomia_atual_km

        if taxi.tipo == "eletrico":
            energia_label = "Bateria"
            energia_unit = "kWh"
            energia_antes = taxi.nivel_bateria_kwh
            energia_cap = taxi.capacidade_bateria_kwh
        else:
            energia_label = "Depósito"
            energia_unit = "L"
            energia_antes = taxi.nivel_deposito_l
            energia_cap = taxi.capacidade_deposito_l


        km_vazio, km_pass, _tempo_min, co2_kg, co2_baseline_green_kg = aplicar_viagem(pedido, taxi, path_to, path_trip, graph)

        # =========================
        # stats por táxi (viagem)
        # =========================
        s = stats[taxi.id]
        s["km_vazio"] += km_vazio
        s["km_pass"] += km_pass
        s["custo_total"] += custo
        s["co2_kg"] += co2_kg
        s["min_a_andar"] += _tempo_min


        # ===== Estado energético DEPOIS da viagem (para log) =====
        autonomia_depois = taxi.autonomia_atual_km

        if taxi.tipo == "eletrico":
            energia_depois = taxi.nivel_bateria_kwh
        else:
            energia_depois = taxi.nivel_deposito_l



        # LOG DA VIAGEM
        log_write(flog, f"Táxi escolhido: {taxi.id} ({taxi.tipo})")
        log_write(flog,f"Tempo de resposta ao pedido: {tempo_resposta_pedido:.1f} min")
        log_write(flog, f"{energia_label}: {energia_antes:.2f} {energia_unit} -> {energia_depois:.2f} {energia_unit} (cap máx: {energia_cap:.2f} {energia_unit})")
        log_write(flog, f"Autonomia: {autonomia_antes:.2f} km -> {autonomia_depois:.2f} km")
        log_write(flog, f"Km vazio (taxi->origem): {km_vazio:.2f} km")
        log_write(flog, f"Km com passageiro (origem->destino): {km_pass:.2f} km")
        log_write(flog, f"Custo estimado da viagem: {custo:.2f} €")
        log_write(flog, f"Tempo total estimado: {_tempo_min:.1f} min | Livre às {taxi.livre_apos.strftime('%H:%M:%S')}")
        log_write(flog, f"CO2 emitido nesta viagem: {co2_kg:.2f} kg")


        if pedido.prefere_verde:
            log_write(flog, f"CO2 baseline diesel (se fosse diesel): {co2_baseline_green_kg:.2f} kg")
            poupado = max(0.0, co2_baseline_green_kg - co2_kg)
            log_write(flog, f"CO2 poupado por ser 'verde': {poupado:.2f} kg")

        # Auto-recarga imediatamente após terminar a viagem (se necessário)
        hora_fim_viagem = taxi.livre_apos  # já foi definido dentro de aplicar_viagem

        fez, min_andar_est, min_espera, min_carga = tentar_recarregar_taxi(taxi, hora_fim_viagem, graph, estacoes_estado, flog, algoritmo=algoritmo)

        if fez:
            s = stats[taxi.id]
            s["abastecimentos"] += 1
            s["min_a_andar"] += min_andar_est
            s["min_parado"] += (min_espera + min_carga)



        km_vazio_total += km_vazio
        km_passageiro_total += km_pass
        # CO2 total (todos os pedidos)
        co2_total_kg += co2_kg
        # CO2 "green": real vs baseline diesel
        if pedido.prefere_verde:
            co2_green_real_kg += co2_kg
            co2_green_baseline_diesel_kg += co2_baseline_green_kg


        carros_a_carregar(taxis, pedido.hora_pedido, graph, estacoes_estado, flog, algoritmo=algoritmo)
        print_estado_taxis(taxis)

    total = atendidos + falhados
    log_header(flog, "RESUMO FINAL POR TÁXI")

    for tid, s in stats.items():
        km_total = s["km_vazio"] + s["km_pass"]

        h_andar = int(s["min_a_andar"] // 60)
        m_andar = int(s["min_a_andar"] % 60)

        h_parado = int(s["min_parado"] // 60)
        m_parado = int(s["min_parado"] % 60)

        log_write(flog, f"{tid} | tipo={s['tipo']}")
        log_write(flog, f"  • Km com cliente: {s['km_pass']:.2f} km")
        log_write(flog, f"  • Km sem cliente: {s['km_vazio']:.2f} km")
        log_write(flog, f"  • Km totais: {km_total:.2f} km")
        log_write(flog, f"  • Faturação do dia: {s['custo_total']:.2f} €")
        log_write(flog, f"  • CO2 emitido: {s['co2_kg']:.2f} kg")
        log_write(flog, f"  • Abastecimentos/recargas: {s['abastecimentos']}")
        log_write(flog, f"  • Tempo a andar: {h_andar}h{m_andar:02d}")
        log_write(flog, f"  • Tempo Gasto em Recargas/Abastecimentos: {h_parado}h{m_parado:02d}")
        log_write(flog, "")


    return {
        "algoritmo": algoritmo,
        "total_pedidos": total,
        "atendidos": atendidos,
        "falhados": falhados,
        "taxa_sucesso": (atendidos / total) if total else 0.0,
        "custo_total": custo_total,
        "tempo_resposta_medio_min": (tempo_resposta_total / atendidos) if atendidos else float("inf"),
        "expanded_medio": (expanded_total / atendidos) if atendidos else float("inf"),
        "km_vazio_total": km_vazio_total,
        "km_passageiro_total": km_passageiro_total,
        "co2_total_kg": co2_total_kg,
        "co2_medio_por_pedido_kg": (co2_total_kg / atendidos) if atendidos else float("inf"),
        "co2_green_real_kg": co2_green_real_kg,
        "co2_green_baseline_diesel_kg": co2_green_baseline_diesel_kg,
        "co2_green_poupado_kg": max(0.0, co2_green_baseline_diesel_kg - co2_green_real_kg),


    }

def main():
    os.makedirs("output", exist_ok=True)

    city_path = "input/city.json"
    taxis_path = "input/taxis.json"
    pedidos_path = "input/pedidos.json"

    # desenhar uma vez
    city_draw = CityMap(city_path)
    graph0 = city_draw.load_city(0)
    city_draw.desenhar_grafo()
    print(f"[DEBUG] Grafo carregado com {len(graph0.nodes)} nós e {len(graph0.edges)} arestas")

    print("\n==================== SIMULAÇÃO A* ====================")
    random.seed(0)
    with open("output/astar_log.txt", "w", encoding="utf-8") as flog_astar:
        res_astar = run_simulation("astar", city_path, taxis_path, pedidos_path, flog_astar)

    print("\n==================== SIMULAÇÃO UCS ====================")
    random.seed(0)
    with open("output/ucs_log.txt", "w", encoding="utf-8") as flog_ucs:
        res_ucs = run_simulation("ucs", city_path, taxis_path, pedidos_path, flog_ucs)

    print("\n==================== RESUMO FINAL ====================")
    for r in (res_astar, res_ucs):
        print(f"\nAlgoritmo: {r['algoritmo']}")
        print(f"Pedidos: {r['total_pedidos']} | Atendidos: {r['atendidos']} | Falhados: {r['falhados']}")
        print(f"Taxa sucesso: {r['taxa_sucesso']*100:.1f}%")
        print(f"Custo total (€): {r['custo_total']:.2f}")
        print(f"Tempo resposta médio (min): {r['tempo_resposta_medio_min']:.1f}")
        print(f"Nós expandidos médios: {r['expanded_medio']:.1f}")
        print(f"Km vazios total (taxi->origem): {r['km_vazio_total']:.2f} km")
        print(f"Km com passageiros (origem->destino): {r['km_passageiro_total']:.2f} km")
        print(f"CO2 total (kg): {r['co2_total_kg']:.2f}")
        print(f"CO2 médio por pedido (kg): {r['co2_medio_por_pedido_kg']:.2f}")
        print(f"CO2 (pedidos verdes) real (kg): {r['co2_green_real_kg']:.2f}")
        print(f"CO2 (pedidos verdes) baseline diesel (kg): {r['co2_green_baseline_diesel_kg']:.2f}")
        print(f"CO2 poupado graças a 'prefere_verde' (kg): {r['co2_green_poupado_kg']:.2f}")

    # Comparação CO2 entre algoritmos (fora do for!)
    diff = res_ucs["co2_total_kg"] - res_astar["co2_total_kg"]
    if diff > 0:
        print(f"\nA* poupou {diff:.2f} kg CO2 face ao UCS")
    elif diff < 0:
        print(f"\nUCS poupou {abs(diff):.2f} kg CO2 face ao A*")
    else:
        print("\nAmbos os algoritmos emitiram o mesmo CO2 total.")

    # Função auxiliar para escrever resultados no ficheiro
    def dump_res(fcomp, r):
        fcomp.write(f"Algoritmo: {r['algoritmo']}\n")
        fcomp.write(f"Pedidos: {r['total_pedidos']} | Atendidos: {r['atendidos']} | Falhados: {r['falhados']}\n")
        fcomp.write(f"Taxa sucesso: {r['taxa_sucesso']*100:.1f}%\n")
        fcomp.write(f"Custo total (€): {r['custo_total']:.2f}\n")
        fcomp.write(f"Tempo resposta médio (min): {r['tempo_resposta_medio_min']:.1f}\n")
        fcomp.write(f"Nós expandidos médios: {r['expanded_medio']:.1f}\n")
        fcomp.write(f"Km vazios total: {r['km_vazio_total']:.2f}\n")
        fcomp.write(f"Km com passageiros: {r['km_passageiro_total']:.2f}\n")
        fcomp.write(f"CO2 total (kg): {r.get('co2_total_kg', 0.0):.2f}\n")
        if "co2_green_poupado_kg" in r:
            fcomp.write(f"CO2 poupado (prefere_verde) (kg): {r['co2_green_poupado_kg']:.2f}\n")
        fcomp.write("\n" + "-" * 80 + "\n\n")

    # Escrever comparação para TXT (tudo dentro do with!)
    with open("output/comparacao_algoritmos.txt", "w", encoding="utf-8") as fcomp:
        fcomp.write("COMPARAÇÃO FINAL DE ALGORITMOS\n")
        fcomp.write("=" * 80 + "\n\n")

        dump_res(fcomp, res_astar)
        dump_res(fcomp, res_ucs)



if __name__ == "__main__":
    main()
