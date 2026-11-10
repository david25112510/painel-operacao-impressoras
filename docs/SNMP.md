# SNMP: cobertura e diagnóstico

## Protocolos aceitos

A aplicação suporta SNMP v1 e SNMP v2c com comunidade de leitura. SNMPv3 e operações de escrita SNMP não são implementados. A comunidade começa vazia e deve ser configurada no equipamento e no cadastro do aplicativo.

O servidor envia consultas para UDP 161. Cada consulta usa timeout de 2 segundos e zero tentativas adicionais. As seis ou mais impressoras são consultadas em paralelo. Uma resposta bem-formada permite marcar **online**; três falhas consecutivas levam a **offline**.

## Grupos e objetos consultados

| Informação | Base/objeto consultado |
|---|---|
| Descrição do sistema, object ID, uptime e nome | System Group (SNMP MIB-II) |
| Nome e serial da impressora | Printer-MIB, grupo prtGeneral |
| Estado e bitmap de erros | Host-Resources-MIB, grupo hrPrinter |
| Contador total do mecanismo | `prtMarkerLifeCount` |
| Unidade do contador | `prtMarkerCounterUnit` |
| Contador desde o ciclo de energia | `prtMarkerPowerOnCount` |
| Descrição, unidade, máximo e nível de suprimentos | Printer-MIB, prtMarkerSuppliesTable |
| Capacidade, estado, mídia e nome das entradas | Printer-MIB, prtInputTable |

Referências: [Printer-MIB v2 (RFC 3805)](https://www.rfc-editor.org/rfc/rfc3805) e [Host Resources MIB (RFC 2790)](https://www.rfc-editor.org/rfc/rfc2790). A implementação consulta OIDs padronizados, mas muitos campos/tabelas da Printer-MIB são opcionais. Um fabricante pode não implementar um objeto, expor uma unidade própria ou exigir configuração SNMP específica.

## Status e valores ausentes

- **Conexão online** é uma resposta válida do agente SNMP.
- **Estado da impressora** é a condição informada pelo objeto de estado; pode ser desconhecida mesmo com a conexão online.
- **Erro de consulta** fica disponível nos detalhes/diagnóstico do servidor e conta para o limiar de offline.
- **Sem leitura** para suprimento indica que a porcentagem não pôde ser extraída/calculada; não indica nível cheio.
- **Unidade desconhecida** não deve ser somada a outro tipo de unidade.

Uma impressora acessível por ping ainda pode bloquear SNMP. Confirme SNMP habilitado, versão, comunidade, ACL do equipamento e UDP 161 a partir do computador central. Ping não substitui uma consulta SNMP.

## Contador diário

O contador de vida é cumulativo. A produção diária é derivada da diferença entre leituras sucessivas; consulte [Operação](OPERACAO.md) para limites, resets, rollovers e períodos sem comunicação. Nenhuma informação sobre conteúdo de documento, usuário ou job é solicitada.
