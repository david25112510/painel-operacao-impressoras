# Solução de problemas

## Todas as impressoras aparecem offline

1. Confirme que `ContadoresServidorAtualizado.exe` ou `server.py` está aberto no computador central.
2. Verifique se os endereços no cadastro são os atuais e podem ser alcançados a partir do servidor.
3. Confirme SNMP habilitado, versão v1/v2c correta e comunidade somente de leitura correspondente.
4. Verifique regras de rede para UDP 161 entre servidor e impressora; clientes não precisam de UDP 161.
5. Confira o campo de erro/última leitura no cartão ou nos detalhes, além do log do console central.
6. Após corrigir rede ou credenciais, aguarde três ciclos de coleta (aproximadamente 90 segundos) para voltar de offline a online.

O estado **online** é atualizado assim que uma consulta completa válida retorna. Um erro local do coletor também pode fazer a interface classificar a impressora como offline; preserve a mensagem de erro para diagnóstico.

## Cliente não conecta ao servidor

- Use `https://` no começo da URL e inclua a porta, por exemplo `https://IP-DO-SERVIDOR:8765`.
- Coloque URL e impressão digital SHA256 em campos diferentes.
- Confirme que ambos estão na rede local e que TCP 8765 está liberada no perfil privado do Windows.
- Use o endereço e fingerprint atuais do console do servidor ou de `%APPDATA%\ContadoresImpressoras\conexao.txt`.
- Se o certificado foi regenerado, reconfigure o fingerprint em cada cliente.

## Impressora está online, mas faltam dados

Impressoras podem responder ao SNMP sem implementar todos os grupos Printer-MIB. Modelo, serial, toner, unidade e bandejas podem não ser publicados ou usar semântica específica do fabricante. Confirme a configuração SNMP do equipamento e compare com a documentação/MIB do modelo.

**Sem leitura** para toner significa que não houve uma porcentagem calculável; não significa necessariamente toner cheio ou vazio. Unidade desconhecida não deve ser somada a outra unidade.

## Produção diária parece incorreta

- A produção começa a contar apenas depois da primeira leitura que estabelece uma referência.
- Um intervalo offline atravessando a meia-noite é atribuído à data de retomada e marcado como estimado.
- Impressões, páginas, folhas e imagens podem ser unidades diferentes. Duplex pode gerar duas impressões em uma folha física.
- Troca/reinicialização do contador pode impedir o cálculo do incremento daquele intervalo.

## Backup falha

Confirme que o caminho de rede existe e que a conta Windows que executa o serviço pode criar arquivos nele. Teste o caminho na aba **Servidor e backup** e consulte o alerta/mensagem mais recente. O serviço precisa estar ativo no horário de backup.

## O executável não abre

Use `abrir_cliente.bat` para o cliente e `iniciar_servidor.bat` para o servidor quando os executáveis compilados estão em `release`. Os arquivos `instalar_*.bat` executam a instalação pelo código e precisam de Python instalado. Se o Windows Defender bloquear um executável, verifique o aviso e a origem antes de permitir; compilações locais não têm assinatura de editor.
