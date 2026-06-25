import time
from datetime import timedelta

class Taxi:
    def __init__(
        self,
        id,
        tipo,
        posicao,
        autonomia_max_km,
        autonomia_atual_km,
        velocidade,
        capacidade,
        custo_km,
        consumo_100km=None,        # kWh/100km ou L/100km
        capacidade_bateria_kwh=None,
        nivel_bateria_kwh=None,
        capacidade_deposito_l=None,
        nivel_deposito_l=None,
        tempo_carga=0
    ):
        self.id = id
        self.tipo = tipo                  # "eletrico", "hibrido", "diesel"
        self.posicao = posicao            # nó no grafo

        # Estes valores vêm do JSON, mas vão ser recalculados mais abaixo
        self.autonomia_max_km = autonomia_max_km
        self.autonomia_atual_km = autonomia_atual_km

        self.velocidade = velocidade      # km/h
        self.capacidade = capacidade      # nº passageiros
        self.custo_km = custo_km          # €/km

        # Consumo para estatísticas: kWh/100km ou L/100km
        self.consumo_100km = consumo_100km

        # Elétricos: bateria
        self.capacidade_bateria_kwh = capacidade_bateria_kwh
        self.nivel_bateria_kwh = (
            nivel_bateria_kwh
            if nivel_bateria_kwh is not None
            else capacidade_bateria_kwh
        )

        # Híbridos/diesel: depósito
        self.capacidade_deposito_l = capacidade_deposito_l
        self.nivel_deposito_l = (
            nivel_deposito_l
            if nivel_deposito_l is not None
            else capacidade_deposito_l
        )

        self.tempo_carga = tempo_carga    # minutos (elétricos)
        self.disponivel = True
        self.livre_apos = None

        # 👉 NOVO: recalcular autonomias com base em consumo e depósito/bateria
        self._recalcular_autonomia_inicial()

    def _recalcular_autonomia_inicial(self):
        """
        Calcula autonomia_max_km e autonomia_atual_km a partir de:
        - consumo_100km
        - depósito (híbrido/diesel) OU bateria (elétrico)
        Ignora os valores de autonomia vindos do JSON, se tiver dados suficientes.
        """
        if not self.consumo_100km or self.consumo_100km <= 0:
            return  # não há dados para calcular, mantemos o que veio do JSON

        # HÍBRIDO / DIESEL → usa litros do depósito
        if self.tipo in ("hibrido", "diesel") and self.capacidade_deposito_l:
            # autonomia máx com depósito cheio
            self.autonomia_max_km = (self.capacidade_deposito_l / self.consumo_100km) * 100.0

            # autonomia atual baseada nos litros atuais
            litros_atuais = self.nivel_deposito_l or self.capacidade_deposito_l
            self.autonomia_atual_km = (litros_atuais / self.consumo_100km) * 100.0

        # ELÉTRICO → usa kWh da bateria
        elif self.tipo == "eletrico" and self.capacidade_bateria_kwh:
            self.autonomia_max_km = (self.capacidade_bateria_kwh / self.consumo_100km) * 100.0

            kwh_atuais = self.nivel_bateria_kwh or self.capacidade_bateria_kwh
            self.autonomia_atual_km = (kwh_atuais / self.consumo_100km) * 100.0

    def autonomia_suficiente(self, km_necessarios):
        return self.autonomia_atual_km >= km_necessarios*1.15  # margem de 15%
    
    def precisa_recarregar(self):
        return self.autonomia_atual_km <= self.autonomia_max_km * 0.2 #limite critico de 20%
    
    def abastecer(self):
        self.autonomia_atual_km = self.autonomia_max_km
        if self.tipo == "eletrico":
            self.nivel_bateria_kwh = self.capacidade_bateria_kwh
            return self.tempo_carga
        elif self.tipo in ("hibrido", "diesel"):
            self.nivel_deposito_l = self.capacidade_deposito_l
            return 5

    def __repr__(self):
        return (
            f"Taxi({self.id}, {self.tipo}, pos={self.posicao}, "
            f"aut_km={self.autonomia_atual_km:.1f})"
        )
