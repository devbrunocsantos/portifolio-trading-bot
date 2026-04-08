import os
import csv
import json
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta

class BotReports:
    """
    Classe utilitária para gerenciamento e envio de relatórios de trading.

    Esta classe consolida o histórico de operações (fills) da Binance Futures em 
    arquivos CSV e automatiza o envio desses dados, juntamente com os logs de 
    execução do sistema, via e-mail (SMTP).

    Funcionalidades principais:
    * Extração de dados brutos da API de Futuros dos últimos 7 dias.
    * Geração de relatórios em formato CSV para auditoria externa.
    * Integração com servidor SMTP (Gmail) para notificações semanais.
    * Gestão de limpeza de logs e arquivos temporários pós-envio.

    Requisitos:
    * Arquivo 'email_config.json' contendo as credenciais (sender_email, 
      app_password e recipient_emails).
    * Conexão ativa com a API da Binance via objeto da classe ccxt.
    """
    @staticmethod
    def fetch_weekly_trades_to_csv(
            exchange,
            symbol: str = 'BTCUSDT',
            csv_filepath: str = 'weekly_trade_report.csv'
            ):
        """
        Calcula o timestamp dos últimos 7 dias, busca as execuções de ordens (trade fills) brutas 
        da API de Futuros da Binance e as salva em um arquivo CSV temporário.
        """
        try:
            # Calcula o timestamp de 7 dias atrás em milissegundos
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            start_time_ms = int(seven_days_ago.timestamp() * 1000)
            
            # Requisição à API da Binance Futures
            trades = exchange.fetch_my_trades(symbol=symbol, since=start_time_ms)
            
            if not trades:
                logging.info("No trades found in the last 7 days.")
                return

            # Criação do arquivo CSV temporário
            with open(csv_filepath, mode='w', newline='') as file:
                writer = csv.writer(file)
                
                # Extrai os cabeçalhos dinamicamente das chaves do primeiro dicionário retornado
                headers = list(trades[0].keys())
                writer.writerow(headers)
                
                # Preenche as linhas com os dados brutos da corretora
                for trade in trades:
                    writer.writerow(list(trade.values()))
                    
        except Exception as e:
            logging.info(f"Error fetching weekly trades from Binance: {e}")

    @staticmethod
    def send_weekly_report(
            exchange, 
            symbol: str = 'BTCUSDT', 
            csv_filepath: str = 'weekly_trade_report.csv', 
            log_filepath: str = 'bot_trading.log', 
            config_filepath: str = 'email_config.json'
            ):
        """
        Lê as credenciais do arquivo JSON, anexa o relatório CSV gerado
        e o log de execução, e envia o e-mail via SMTP do Gmail.
        Após o envio bem-sucedido, exclui o arquivo CSV e limpa (trunca) o arquivo de log.
        """
        BotReports.fetch_weekly_trades_to_csv(exchange=exchange, symbol=symbol, csv_filepath=csv_filepath)

        if not os.path.exists(csv_filepath):
            return

        try:
            with open(config_filepath, 'r') as f:
                config_data = json.load(f)

            sender = config_data['sender_email']
            password = config_data['app_password']
            recipients = config_data['recipient_emails']

            email_msg = EmailMessage()
            email_msg['Subject'] = 'Weekly Report & Log - Binance Trading Bot'
            email_msg['From'] = sender
            email_msg['To'] = ', '.join(recipients)
            email_msg.set_content(
                'Attached are the CSV file with the raw trade data and the execution log for the last 7 days.'
                )

            # 1. Anexo do relatório financeiro (CSV)
            with open(csv_filepath, 'rb') as f_csv:
                csv_data = f_csv.read()
                csv_filename = os.path.basename(csv_filepath)
            email_msg.add_attachment(csv_data, maintype='text', subtype='csv', filename=csv_filename)

            # 2. Anexo do log de execução (TXT/LOG)
            if os.path.exists(log_filepath):
                with open(log_filepath, 'rb') as f_log:
                    log_data = f_log.read()
                    log_filename = os.path.basename(log_filepath)
                email_msg.add_attachment(log_data, maintype='text', subtype='plain', filename=log_filename)

            # 3. Disparo criptografado via servidor Google
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(sender, password)
                smtp.send_message(email_msg)

            # 4. Limpeza de segurança
            os.remove(csv_filepath) # Deleta o CSV temporário
            
            if os.path.exists(log_filepath):
                open(log_filepath, 'w').close() # Trunca (esvazia) o log sem destruir o arquivo original
            
        except Exception as e:
            logging.info(f"Error sending weekly email report: {e}")