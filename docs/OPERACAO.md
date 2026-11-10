# Operação

## Painel

A aba **Visão da operação** mostra indicadores gerais, cartões por equipamento, imagens/ilustrações, conexão, estado reportado, contador cumulativo, volume do dia e suprimentos. **Online** quer dizer que o serviço recebeu uma resposta SNMP válida; não significa que a impressora está pronta para imprimir. O estado do equipamento e os erros reportados aparecem à parte.

Uma impressora pode responder ao SNMP e ainda exibir erro de bandeja, papel, toner, atolamento ou manutenção. Por outro lado, **offline** representa falha de comunicação consecutiva, e não necessariamente que o equipamento está desligado.

## Produção diária e relatórios

A produção é o incremento do contador entre duas coletas. O ponto de partida é a primeira coleta bem-sucedida. O sistema não consegue atribuir as impressões a um trabalho, documento, departamento ou usuário.

Se a conexão ficar interrompida por um intervalo que atravesse a meia-noite, o sistema atribui o incremento ao dia da retomada e marca o total como estimado. Se o contador reiniciar ou mudar a unidade, o histórico indica a situação; o primeiro valor após a mudança não cria um incremento fictício.

A aba **Produção diária** permite consultar um dia ou período e exportar os dados em CSV, que pode ser aberto no Excel. A soma global só é exibida quando as impressoras usam a mesma unidade.

## Histórico

O histórico mantém a leitura inicial, alterações relevantes e uma linha de resumo por hora quando não houve mudança durante aquela hora. Os dados são retidos indefinidamente no banco ativo. Planeje armazenamento e backups conforme o crescimento do banco.

## Usuários

Cada pessoa deve usar uma conta individual. Na versão atual, todas as contas têm os mesmos privilégios administrativos. Um administrador pode criar contas, redefinir senhas e desativar contas; não é possível desativar a última conta ativa.

Use senhas fortes com pelo menos 12 caracteres. Tokens de sessão expiram após 12 horas. Ao compartilhar um computador, encerre a sessão e proteja o perfil Windows.

## Backup e restauração

### Verificar

Na aba **Servidor e backup**, teste o acesso ao compartilhamento e confira a mensagem e a data do último backup. O Windows que executa o servidor precisa ter permissão de escrita e leitura.

### Restaurar

1. Pare o serviço central.
2. Faça uma cópia do banco atual em `%APPDATA%\ContadoresImpressoras`.
3. Extraia `operacao.sqlite3` de um ZIP confiável para essa pasta, substituindo o banco.
4. Inicie novamente o serviço.
5. Confirme o estado do painel e os dados restaurados.

Não restaure enquanto o serviço estiver escrevendo no banco. O arquivo de certificado (`servidor.pem`) e a chave privada ficam fora do ZIP; mantenha cópias protegidas se precisar migrar o servidor e preservar a impressão digital. Se gerar certificado novo, atualize a impressão digital configurada nos clientes.

## Atualização

Antes de trocar os arquivos, faça um backup e feche o serviço central e os clientes. Atualize código ou executáveis juntos, preservando `%APPDATA%\ContadoresImpressoras`. Reinicie o serviço e abra os clientes. Não apague essa pasta durante uma atualização: ela contém banco, certificado e chave privada.
