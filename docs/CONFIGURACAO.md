# Configuração

## Cadastro de uma impressora

Abra a aba **Equipamentos** no cliente e informe:

- **Nome no painel:** nome amigável escolhido pela equipe.
- **Endereço IP:** endereço IPv4 fixo ou reservado por DHCP.
- **Comunidade SNMP:** comunidade com permissão somente de leitura, configurada na impressora. O campo começa vazio por segurança.
- **Versão SNMP:** v1 ou v2c.
- **Foto:** opcional. Sem foto própria, a aplicação desenha uma ilustração genérica da família de equipamento.

Confirme que o endereço está acessível a partir do computador central, não apenas da estação cliente. A versão e a comunidade devem coincidir com a configuração da impressora.

## Dados lidos

O coletor usa os seguintes grupos de informação quando o dispositivo os fornece:

- Identificação: descrição, object ID, nome de host, nome e número de série.
- Estado de impressão e sinalizadores de erro, como falta de papel, tampa aberta, atolamento ou necessidade de manutenção.
- Tempo ligado.
- Contador total de vida, unidade e contador desde a última energização.
- Descrição e nível de suprimentos; porcentagem calculada quando a impressora informa escala percentual ou nível máximo.
- Nome, capacidade, mídia e estado de bandejas.

A implementação consulta objetos padrão da System Group, Printer-MIB e Host-Resources-MIB. Alguns fabricantes omitem tabelas, usam unidades incomuns ou expõem valores específicos de firmware. Campo ausente é mostrado como sem leitura/indisponível; não significa necessariamente erro de conexão.

O projeto não mostra todos os OIDs indiscriminadamente e não consulta trabalhos, documentos, usuários nem conteúdo impresso.

## Frequência e estados

- Intervalo de coleta: 30 segundos.
- Cada consulta usa timeout SNMP de 2 segundos, sem repetição automática por tentativa.
- A impressora passa a offline após três falhas seguidas; até lá aparece como verificando.
- O cliente atualiza a interface periodicamente usando o serviço central.
- Alerta de toner: 5% ou menos quando a impressora fornece uma porcentagem utilizável.

Uma impressão com falha pode ser causada por indisponibilidade da rede, comunidade/versão incompatíveis, SNMP desativado, bloqueio de UDP 161 ou resposta que o firmware não implementa.

## Alertas

O painel mantém os alertas ativos até a condição se resolver. Usuários podem reconhecer alertas no cliente. Uma notificação flutuante aparece nos computadores com o cliente aberto quando surge nova ocorrência; o aplicativo não entrega notificações se estiver fechado.

## Backup

Na aba **Servidor e backup**, configure uma pasta gravável pelo usuário Windows que executa o serviço, por exemplo `\\NAS\Impressoras\Backups`. O backup ZIP diário ocorre depois das 02:00, horário local, e mantém por padrão os 30 arquivos mais recentes. A retenção pode ser ajustada na interface.

O serviço central precisa permanecer ativo para executar o agendamento. O backup contém uma cópia do banco SQLite, incluindo cadastro, histórico, comunidades SNMP, contas (hashes de senha), alertas e fotos. Restrinja a pasta compartilhada a pessoas autorizadas.
