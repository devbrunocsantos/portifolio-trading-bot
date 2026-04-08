import os
import time
import ccxt
import math
import logging
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv
from datetime import datetime, timezone
from reports import BotReports

# Configuração de log para monitoramento contínuo na AWS EC2
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_trading.log"),
        logging.StreamHandler()
        ]
    )

# --- Credenciais de API ---
load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")

COLOR_LONG = '\033[92m'  # Verde
COLOR_SHORT = '\033[91m' # Vermelho
COLOR_RESET = '\033[0m'  # Resetar cor

class BinanceFuturesBot:
    """
    Motor de execução para trading automatizado em mercados de Futuros da Binance.

    Esta classe implementa uma estratégia de acompanhamento de tendência baseada em 
    médias móveis exponenciais (EMAs) e força de mercado (ADX/OBV), utilizando o 
    indicador Chandelier Exit como mecanismo de trailing stop dinâmico.

    Funcionalidades principais:
    * Arquitetura de Conectividade: Integração com a API Binance Futures via CCXT 
      utilizando margem isolada, modo One-Way e alavancagem customizável.
    * Inteligência Técnica: Cálculo de indicadores de tendência (EMA 14, 30, 60), 
      momentum (ADX), volume (OBV) e volatilidade (ATR).
    * Gestão de Risco: Dimensionamento dinâmico de posição (Position Sizing) baseado 
      em uma porcentagem fixa de risco do capital e volatilidade do ativo (2x ATR).
    * Automação Operacional: Monitoramento 24/7 com execução de ordens a mercado, 
      posicionamento de Stop Loss e transferência automática de lucros para a conta Spot.
    * Saída por Exaustão: Implementação de Trailing Stop dinâmico através do 
      Chandelier Exit para proteção de lucro e redução de drawdown.

    Requisitos:
    * Variáveis de ambiente configuradas (.env) com chaves de API da Binance.
    * Dependências instaladas: ccxt, pandas_ta e dependências de sistema para logs.
    """
    def __init__(self, api_key: str, api_secret: str):
        """
        Inicializa a conexão com a Binance Futures via ccxt.
        Configura o mercado utilizando o padrão unificado de derivativos do CCXT.
        """
        # Símbolo atualizado para o padrão unificado do CCXT (Mercado Futuro Linear USD-M)
        self.symbol = 'BTC/USDT:USDT' 
        self.timeframe = '1d'
        self.leverage = 2
        self.max_capital = 1000000.0 # Limite máximo de capital (1.000.000 USDT)
        self.risk_per_trade = 0.05 # 5% de risco fixo por operação
        self.prev_chandelier_short = None # Variável para armazenar o valor anterior do Chandelier Short para comparação
        self.prev_chandelier_long = None # Variável para armazenar o valor anterior do Chandelier Long para comparação

        # Variável auxiliar para chamadas cruas na API da Binance (formato: BTCUSDT)
        market_symbol = self.symbol.split(':')[0].replace('/', '')
        
        try:
            self.exchange = ccxt.binance({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'swap'  # Mantém o roteamento para Contratos Perpétuos
                }
                })

            # Configuração de Modo One-Way (Garante que a conta não esteja em Hedge Mode)
            try:
                self.exchange.fapiPrivatePostPositionSideDual({
                    'dualSidePosition': 'false'
                    })
            except ccxt.ExchangeError as e:
                if "-4059" in str(e):
                    logging.info("Conta já configurada em Modo One-Way (Nenhuma alteração necessária).")
                else:
                    logging.error(f"Erro ao configurar Modo One-Way: {e}")
            
            # Configuração de Margem Isolada (Utiliza o market_symbol limpo: BTCUSDT)
            try:
                self.exchange.fapiPrivatePostMarginType({
                    'symbol': market_symbol,
                    'marginType': 'ISOLATED'
                    })
            except ccxt.ExchangeError as e:
                if "-4046" in str(e):
                    logging.info("Ativo já configurado em Margem Isolada (Nenhuma alteração necessária).")
                else:
                    logging.error(f"Erro ao configurar Margem Isolada: {e}")
            
            # Ajuste de Alavancagem (Utiliza o método nativo do CCXT com o símbolo unificado)
            try:
                self.exchange.set_leverage(self.leverage, self.symbol)
                logging.info(f"Alavancagem sincronizada e confirmada em {self.leverage}x pela exchange.")
            except Exception as e:
                logging.error(f"Erro crítico ao ajustar alavancagem na exchange: {e}")
                
            logging.info(
                f"Conexão estabelecida e parâmetros validados com sucesso (Isolada, {self.leverage}x, One-Way)."
                )
                
        except ccxt.BaseError as e:
            logging.error(f"Erro na API do ccxt durante a inicialização: {e}")
        except Exception as e:
            logging.error(f"Erro inesperado ao inicializar a API da Binance: {e}")

    def fetch_market_data(self) -> pd.DataFrame:
        """
        Coleta os dados de OHLCV e calcula os indicadores técnicos (EMAs, RSI, ADX, EFI).
        Retorna um DataFrame contendo o histórico e as colunas de sinais.
        """
        try:
            bars = self.exchange.fetch_ohlcv(self.symbol, timeframe=self.timeframe, limit=500)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            # Cálculo das EMAs (14 e 30 e 60 períodos)
            df.ta.ema(length=14, append=True)
            df.ta.ema(length=30, append=True)
            df.ta.ema(length=60, append=True)

            # Cálculo dos Filtros (OBV e ADX)
            df['OBV'] = df.ta.obv(close='close', volume='volume')
            df['OBV_EMA'] = ta.ema(df['OBV'], length=21) # EMA de 21 períodos
            df.ta.adx(length=14, append=True)
                        
            # Cálculo do Chandelier Exit (Regra de SAÍDA) 
            ce_length = 21
            ce_mult = 2.5
            
            # 1. Average True Range (ATR). Atribuição direta para evitar conflitos de string.
            df['ATR'] = df.ta.atr(length=ce_length)
            
            # 2. Máximas e Mínimas do período
            df['HH_22'] = df['high'].rolling(window=ce_length).max()
            df['LL_22'] = df['low'].rolling(window=ce_length).min()
            
            # 3. Limites de Stop Móvel Baseado em Volatilidade
            df['Chandelier_Long'] = df['HH_22'] - (df['ATR'] * ce_mult)
            df['Chandelier_Short'] = df['LL_22'] + (df['ATR'] * ce_mult)
                        
            # Limpeza de dados nulos gerados pelo atraso dos indicadores
            df.dropna(inplace=True)
            
            return df
            
        except ccxt.NetworkError as e:
            logging.error(f"Erro de rede ao buscar dados OHLCV: {e}")
            return pd.DataFrame()
        except Exception as e:
            logging.error(f"Erro no processamento dos indicadores técnicos: {e}")
            return pd.DataFrame()

    def evaluate_signals(self, df: pd.DataFrame, current_side: str = None) -> str:
        """
        Avalia as condições de entrada (RSI/ADX/EMA) e saída (Chandelier Exit) 
        com base no fechamento do último candle.
        
        Parâmetros:
        - df: DataFrame contendo os dados OHLCV e indicadores calculados.
        - current_side: String indicando a posição atual ('LONG', 'SHORT' ou None).
        
        Retorno:
        - String contendo o sinal gerado ('LONG', 'SHORT', 'CLOSE_POSITION', ou 'NEUTRAL').
        """
        # Extração das duas últimas linhas consolidadas para verificar cruzamentos
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        close = last_row['close']
        ema_14 = last_row['EMA_14']
        ema_30 = last_row['EMA_30']
        ema_60 = last_row['EMA_60']
        adx = last_row['ADX_14']
        prev_adx = prev_row['ADX_14']
        obv = last_row['OBV']
        obv_ema = last_row['OBV_EMA']
        
        # Leitura dos limites dinâmicos de volatilidade para exaustão
        chand_long = last_row['Chandelier_Long']
        chand_short = last_row['Chandelier_Short']

        if self.prev_chandelier_short is None and self.prev_chandelier_long is None:
            self.prev_chandelier_short = chand_short
            self.prev_chandelier_long = chand_long

        elif self.prev_chandelier_short is not None and self.prev_chandelier_long is not None:
            if chand_short < self.prev_chandelier_short:
                logging.info(f"Chandelier Short atualizado: {self.prev_chandelier_short:.2f} -> {chand_short:.2f}")
                self.prev_chandelier_short = chand_short

            if chand_long > self.prev_chandelier_long:
                logging.info(f"Chandelier Long atualizado: {self.prev_chandelier_long:.2f} -> {chand_long:.2f}")
                self.prev_chandelier_long = chand_long

        logging.info(f"ADX: {adx:.2f}|PREV_ADX: {prev_adx:.2f}")

        if obv > obv_ema:
            logging.info(f"{COLOR_LONG}OBV > OBV_EMA{COLOR_RESET}")
        else:
            logging.info(f"{COLOR_SHORT}OBV < OBV_EMA{COLOR_RESET}")

        emas_log = f"{COLOR_LONG}CLOSE > EMA_14{COLOR_RESET}" if close > ema_14 else f"{COLOR_SHORT}CLOSE < EMA_14{COLOR_RESET}"
        emas_log += f"|{COLOR_LONG}EMA_14 > EMA_30{COLOR_RESET}" if ema_14 > ema_30 else f"|{COLOR_SHORT}EMA_14 < EMA_30{COLOR_RESET}"
        emas_log += f"|{COLOR_LONG}EMA_30 > EMA_60{COLOR_RESET}" if ema_30 > ema_60 else f"|{COLOR_SHORT}EMA_30 < EMA_60{COLOR_RESET}"

        logging.info(f"{emas_log}")    

        # Verificação de Exaustão (Saída Baseada em Volatilidade) - Prioridade máxima
        if current_side is not None:
            if current_side == 'LONG':
                logging.info(f"Chandelier Long: {self.prev_chandelier_long:.2f}")
                # Gatilho: Preço fecha abaixo da linha de segurança (Trailing Stop)
                if close < self.prev_chandelier_long:
                    logging.info(f"Rompimento de volatilidade: Preço ({close:.2f}) < Chandelier Long ({chand_long:.2f})")
                    return 'CLOSE_POSITION'
                else:
                    return 'LONG'  # Mantém a posição LONG aberta
                    
            elif current_side == 'SHORT':
                logging.info(f"Chandelier Short: {self.prev_chandelier_short:.2f}")
                # Gatilho: Preço fecha acima da linha de segurança (Trailing Stop)
                if close > self.prev_chandelier_short:
                    logging.info(f"Rompimento de volatilidade: Preço ({close:.2f}) > Chandelier Short ({chand_short:.2f})")
                    return 'CLOSE_POSITION'
                else:
                    return 'SHORT'  # Mantém a posição SHORT aberta
                
        # Verificação de Entradas Padrão
        if current_side is None:
            # Regra LONG
            long_condition = (
                (close > ema_14 > ema_30 > ema_60) and
                (25 <= adx <= 45) and
                (prev_adx < adx) and
                (obv > obv_ema)
                )
            
            if long_condition:
                logging.info("Condições de LONG atendidas.")
                logging.info(f"Chandeler Long: {chand_long:.2f}")
                return 'LONG'
                
            # Regra SHORT
            short_condition = (
                (close < ema_14 < ema_30 < ema_60) and
                (25 <= adx <= 45) and
                (prev_adx < adx) and
                (obv < obv_ema)
                )
            
            if short_condition:
                logging.info("Condições de SHORT atendidas.")
                logging.info(f"Chandeler Short: {chand_short:.2f}")
                return 'SHORT'
                
        return 'NEUTRAL'

    def calculate_stop_loss(self, entry_price: float, side: str, atr_value: float) -> dict:
        """
        Calcula o nível de preço para Stop Loss dinâmico baseado no indicador ATR (2x ATR).
        
        Parâmetros:
        - entry_price: Preço de execução da ordem a mercado.
        - side: Direção da operação ('LONG' ou 'SHORT').
        - atr_value: Valor atual do Average True Range extraído do último candle.
        
        Retorno:
        - Float contendo o preço exato de acionamento do stop loss.
        """
        stop_distance = 2 * atr_value
        
        if side == 'LONG':
            sl_price = entry_price - stop_distance
        elif side == 'SHORT':
            sl_price = entry_price + stop_distance
        else:
            raise ValueError("O parâmetro side deve ser 'LONG' ou 'SHORT'.")
            
        return round(sl_price, 2)
    
    def get_position_size(self) -> tuple:
        """
        Consulta a posição atual do ativo na Binance Futures.
        Retorna um float com o tamanho da posição.
        Retorna (0.0) se não houver posição aberta.
        """
        try:
            positions = self.exchange.fetch_positions([self.symbol])
            for position in positions:
                if position['symbol'] == self.symbol:
                    return float(position['info']['positionAmt'])
            return 0.0
        except ccxt.NetworkError as e:
            logging.error(f"Erro de rede ao buscar posição atual: {e}")
            return 0.0
        except Exception as e:
            logging.error(f"Erro inesperado ao buscar posição atual: {e}")
            return 0.0

    def execute_order(self, side: str, amount: float) -> dict:
        """
        Executa uma ordem a mercado para entrada ou saída de posição.
        
        Parâmetros:
        - side: 'buy' para compras, 'sell' para vendas.
        - amount: Quantidade do ativo a ser negociada.
        """
        try:
            order = self.exchange.create_order(
                symbol=self.symbol,
                type='market',
                side=side,
                amount=amount
                )
            
            logging.info(f"Ordem a mercado executada: {side.upper()} {amount} {self.symbol}")
            return order
        except Exception as e:
            logging.error(f"Erro ao executar ordem a mercado ({side}): {e}")
            return {}

    def place_stop_loss(self, amount: float, side: str, target: dict):
        """
        Posiciona as ordens de Stop Loss.
        Utiliza Stop Market.
        """
        try:
            # Define a direção oposta para as ordens de saída
            exit_side = 'sell' if side == 'LONG' else 'buy'

            # Ordem de Stop Loss (Stop Market total com reduceOnly)
            self.exchange.create_order(
                symbol=self.symbol,
                type='stop_market',
                side=exit_side,
                amount=amount,
                params={
                    'stopPrice': target,
                    'reduceOnly': True
                    }
                )
            
            logging.info(f"Stop Loss (100%) posicionado em {target} ({exit_side.upper()}).")

        except Exception as e:
            logging.error(f"Erro ao posicionar ordens de risco: {e}")

    def process_signal(
            self,
            signal: str,
            current_balance: float,
            current_price: float,
            current_position_size: float,
            current_atr: float
            ):
        """
        Processa o sinal gerado, executa a entrada/reversão e posiciona os alvos e stops.
        """
        if signal == 'NEUTRAL':
            return current_position_size

        try:
            if current_position_size == 0.0:
                trade_amount = self.calculate_trade_amount(current_balance, current_price, current_atr)

            if signal == 'CLOSE_POSITION' and current_position_size != 0.0:
                logging.info(
                    "Reversão de volatilidade detectada pelo Chandelier Exit. Iniciando protocolo de fechamento."
                    )
                                
                exit_side = 'sell' if current_position_size > 0 else 'buy'
                self.execute_order(exit_side, abs(current_position_size))
                self.exchange.cancel_all_orders(symbol=self.symbol, params={'stop': True})

                self.prev_chandelier_long = None
                self.prev_chandelier_short = None
                
                logging.info(
                    "Posição encerrada via trailing stop dinâmico. Aguardando novo setup de entrada."
                    )
                return 0.0

            elif signal == 'LONG' and current_position_size == 0:
                logging.info("Sinal de LONG. Abrindo nova posição.")
                order = self.execute_order('buy', trade_amount)
                
                if order:
                    entry_price = order.get('average', order.get('price'))
                    target = self.calculate_stop_loss(entry_price, 'LONG', current_atr)
                    self.place_stop_loss(trade_amount, 'LONG', target)
                    return trade_amount
                
            elif signal == 'SHORT' and current_position_size == 0:
                logging.info("Sinal de SHORT. Abrindo nova posição.")
                order = self.execute_order('sell', trade_amount)
                
                if order:
                    entry_price = order.get('average', order.get('price'))
                    target = self.calculate_stop_loss(entry_price, 'SHORT', current_atr)
                    self.place_stop_loss(trade_amount, 'SHORT', target)
                    return -trade_amount

        except Exception as e:
            logging.error(f"Erro durante o processamento do sinal {signal}: {e}")
            return current_position_size

    def transfer_profits_to_spot(self):
        """
        Transfere o saldo excedente da conta de Futuros para a conta Spot.
        Executado apenas no dia 5 de cada mês. Mantém a reserva operacional intacta.
        """
        try:
            balance_info = self.exchange.fetch_balance(params={'type': 'future'})
            total_usdt = balance_info['USDT']['free'] # Saldo disponível para transferência
            
            if total_usdt > self.max_capital:
                profit = total_usdt - self.max_capital
                logging.info(f"Saldo total ({total_usdt} USDT) excede a reserva. Transferindo {profit} USDT para Spot.")
                
                # Transferência via API
                self.exchange.transfer(
                    code='USDT',
                    amount=profit,
                    fromAccount='future',
                    toAccount='spot'
                    )
                
                logging.info("Transferência de lucros para Spot concluída com sucesso.")
            else:
                logging.info(
                    f"Saldo atual ({total_usdt} USDT) dentro do limite operacional de {self.max_capital}. Nenhuma transferência executada."
                    )
                
        except Exception as e:
            logging.error(f"Erro ao transferir lucros: {e}")

    def get_usdt_balance(self) -> float:
        """
        Consulta o saldo disponível (livre) de USDT na carteira de Futuros.
        """
        try:
            balance = self.exchange.fetch_balance(params={'type': 'future'})
            
            free_usdt = balance['USDT']['free']
            
            return free_usdt
        except Exception as e:
            logging.error(f"Erro ao consultar saldo: {e}")
            return 0.0

    def calculate_trade_amount(self, balance: float, current_price: float, atr_value: float) -> float:
        """
        Calcula o tamanho da posição baseado no risco financeiro (1%) 
        e na distância dinâmica do Stop Loss (2x ATR).
        """
        try:
            self.exchange.load_markets()
            market = self.exchange.market(self.symbol)
            
            # 1. Valor financeiro ideal de risco (ex: 1% do capital disponível)
            risk_amount = balance * self.risk_per_trade
            
            # 2. Cálculo do percentual do Stop Loss com base no ATR (2x)
            stop_distance_abs = 2 * atr_value
            stop_loss_pct = stop_distance_abs / current_price
            
            # 3. Tamanho da posição financeira total e conversão para criptoativo
            position_size_usd = risk_amount / stop_loss_pct
            trade_amount_coin = position_size_usd / current_price
            
            # 4. Formatação inicial via CCXT (Corta as casas decimais excedentes)
            final_amount_str = self.exchange.amount_to_precision(self.symbol, trade_amount_coin)
            final_amount = float(final_amount_str)
            
            # 5. Validação da regra do Nocional Mínimo da Binance (Minimum Notional)
            min_notional = market.get('limits', {}).get('cost', {}).get('min', 100.0)
            
            if (final_amount * current_price) < min_notional:
                logging.info(
                    f"Nocional ({final_amount * current_price:.2f} USDT) menor que o exigido ({min_notional} USDT). Arredondando para lote seguro."
                    )
                
                step_size = market['limits']['amount']['min']
                required_coins = min_notional / current_price
                final_amount = math.ceil(required_coins / step_size) * step_size
                final_amount = float(self.exchange.amount_to_precision(self.symbol, final_amount))
                
                real_risk_usd = (final_amount * current_price) * stop_loss_pct
                real_risk_pct = (real_risk_usd / balance) * 100
                logging.info(
                    f"Lote ajustado. Novo Risco real: {real_risk_pct:.2f}% ({real_risk_usd:.2f} USDT)."
                    )
            else:
                logging.info(
                    f"Capital: {balance:.2f} USDT | Risco(1%): {risk_amount:.2f} USDT | Nocional: {(final_amount * current_price):.2f} USDT | Qtd: {final_amount} BTC"
                    )
                
            return final_amount
            
        except Exception as e:
            logging.error(f"Erro ao calcular o tamanho da ordem: {e}")
            return 0.0

    def run(self):
        """
        Loop principal projetado para execução contínua (24/7)
        """
        logging.info(f"Iniciando loop principal do robô (Timeframe: {self.timeframe})...")
        first_run = True
        
        while True:
            try:
                now = datetime.now(timezone.utc)
                
                # 1. Envio de relatório e log semanal (Segunda-feira, 11:00 UTC -> 08:00 Brasília)
                if now.weekday() == 0 and now.hour == 11 and now.minute == 00:
                    
                    csv_filepath = f'weekly_trade_report-{now.strftime("%Y-%m-%d")}.csv'
                    BotReports.send_weekly_report(exchange=self.exchange, csv_filepath=csv_filepath)
                    
                    now = datetime.now(timezone.utc)
                    secs_to_next_minute = 60 - now.second

                    time.sleep(secs_to_next_minute) # Pausa para não repetir a transferência no mesmo minuto
                    continue

                # 2. Transferência de lucros para Spot (Dia 5, 00:10 UTC) - Mantém a reserva operacional intacta
                if (now.day == 5 and now.hour == 0 and now.minute == 10) and now.month in [6, 12]:
                    self.transfer_profits_to_spot()

                    now = datetime.now(timezone.utc)
                    secs_to_next_minute = 60 - now.second

                    time.sleep(secs_to_next_minute) # Pausa para não repetir a transferência no mesmo minuto
                    continue
                
                # 3. Sincronização de Tempo
                if now.hour == 0 and now.minute == 1 or first_run: # Sincroniza a cada 24 horas para garantir alinhamento com o início do candle diário
                    df = self.fetch_market_data()
                    
                    if not df.empty:
                        last_row = df.iloc[-1]
                        current_price = last_row['close']
                        current_atr = last_row['ATR']
                        current_balance = self.get_usdt_balance()
                        current_position_size = self.get_position_size()
                        current_side = 'LONG' if current_position_size > 0 else 'SHORT' if current_position_size < 0 else None

                        if current_position_size == 0.0:
                            # 4. Verificação de Ordens Abertas para evitar conflitos
                            try:
                                stop_orders = self.exchange.fetch_open_orders(
                                    symbol=self.symbol, params={'stop': True}
                                    )

                                if stop_orders:
                                    self.exchange.cancel_all_orders(
                                        symbol=self.symbol, params={'stop': True}
                                        )  # Cancela todas as ordens de stop pendentes

                            except Exception as e:
                                logging.error(f"Erro ao verificar ou cancelar ordens abertas: {e}")

                            self.prev_chandelier_long = None
                            self.prev_chandelier_short = None

                        # Validação para evitar erros se a API retornar saldo zerado
                        if current_balance > 0:
                            # 5. Avaliação do sinal com base nos dados técnicos e na posição atual
                            signal = self.evaluate_signals(df, current_side)

                            # 6. Processamento do sinal gerado e execução das ordens correspondentes
                            current_position_size = self.process_signal(
                                signal, current_balance, current_price, current_position_size, current_atr
                                )
                            
                            if signal == 'LONG':
                                signal_log = f"{COLOR_LONG}LONG{COLOR_RESET}" 
                            elif signal == 'SHORT':
                                signal_log = f"{COLOR_SHORT}SHORT{COLOR_RESET}"
                            elif signal == 'NEUTRAL':
                                signal_log = f"{COLOR_RESET}NEUTRAL{COLOR_RESET}"
                            elif signal == 'CLOSE_POSITION':
                                signal_log = f"{COLOR_RESET}CLOSE_POSITION{COLOR_RESET}"

                            logging.info(
                                f"Sinal avaliado: {signal_log} | Posição Atual: {current_position_size} BTC"
                                )
                            
                        else:
                            logging.warning(
                                "Falha ao consultar saldo ou saldo zerado. Aguardando próximo ciclo."
                                )

                        first_run = False # Desativa a sincronização imediata após a primeira execução
                        
                # 7. Pausa após o processamento para aguardar o próximo minuto
                now = datetime.now(timezone.utc)
                secs_to_next_minute = 60 - now.second
                time.sleep(secs_to_next_minute)
                    
            except Exception as e:
                logging.error(f"Erro crítico no loop principal: {e}")
                time.sleep(60) # Previne acúmulo de logs em caso de instabilidade grave na rede

if __name__ == "__main__":
    bot = BinanceFuturesBot(api_key=API_KEY, api_secret=API_SECRET)
    bot.run()