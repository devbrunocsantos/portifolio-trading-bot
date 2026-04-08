# Binance Futures Trading Bot - Trend Following & Volatility Management

<div align="center">

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Binance](https://img.shields.io/badge/Binance-F3BA2F?style=for-the-badge&logo=binance&logoColor=black)
![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?style=for-the-badge&logo=amazon-aws&logoColor=white)
![Status](https://img.shields.io/badge/Status-Operacional-brightgreen?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)

</div>

Este repositório apresenta um motor de execução automatizado para o mercado de Futuros da Binance (USD-M), desenvolvido com foco em robustez técnica, gestão de risco dinâmica e arquitetura escalável para implantação em nuvem (AWS EC2).

## 1. Visão Geral
O bot utiliza uma estratégia de acompanhamento de tendência (Trend Following) combinando filtros de momentum e volume com uma saída baseada em exaustão de volatilidade através do indicador **Chandelier Exit**.

### Principais Diferenciais Técnicos:
* **Gestão de Risco Dinâmica:** Dimensionamento de posição (Position Sizing) baseado em um percentual fixo de risco sobre o capital total, ajustado pela volatilidade do ativo (2x ATR).
* **Trailing Stop Inteligente:** Implementação do Chandelier Exit para proteção de lucro e redução de drawdown.
* **Arquitetura Robusta:** Integração via biblioteca CCXT, utilizando margem isolada, modo One-Way e sincronização de tempo para execução 24/7.
* **Relatórios Automatizados:** Sistema auxiliar que consolida execuções (fills) em CSV e envia logs e relatórios semanais via SMTP (Gmail).

## 2. Tecnologias Utilizadas
* **Linguagem:** Python 3.10+
* **Bibliotecas de Dados:** `pandas`, `pandas-ta`
* **Conectividade:** `ccxt` (Binance API)
* **Infraestrutura:** `python-dotenv` para segurança de credenciais, `logging` para monitoramento.

## 3. Estrutura do Projeto
* `main.py`: Motor principal, lógica de sinais e execução de ordens.
* `reports.py`: Utilitário de auditoria e envio de e-mails.
* `requirements.txt`: Dependências do ecossistema.
* `.env`: (Não incluído) Configurações de API e chaves secretas.

## 4. Configuração e Execução
1. Clone o repositório.
2. Crie um ambiente virtual: `python -m venv venv`.
3. Instale as dependências: `pip install -r requirements.txt`.
4. Configure o arquivo `.env` com suas chaves da Binance.
5. Execute o bot: `python main.py`.

---

## ⚠️ AVISO LEGAL (DISCLAIMER)

**ESTE SOFTWARE É PARA FINS EXCLUSIVAMENTE DIDÁTICOS E DE PORTFÓLIO.**

1.  **Risco Financeiro:** O mercado de criptoativos, especialmente o de Futuros/Derivativos, envolve alto risco e volatilidade. Perdas podem exceder o depósito inicial.
2.  **Sem Garantias:** O autor não garante lucro nem a precisão dos sinais gerados por este algoritmo. O desempenho passado não é garantia de resultados futuros.
3.  **Isenção de Responsabilidade:** O desenvolvedor **não se responsabiliza** por qualquer perda financeira, danos diretos ou indiretos causados pelo uso, mau uso ou falhas técnicas deste bot. O uso de chaves de API com permissão de negociação é de total responsabilidade do usuário.
4.  **Não é Aconselhamento Financeiro:** O código contido neste repositório não constitui aconselhamento de investimento ou recomendação de compra/venda.

## 5. Licença
Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.
