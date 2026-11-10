# Instalação

## Opção A: executar pelo código-fonte

### Requisitos

- Windows 10 ou Windows 11, 64 bits.
- Python 3.10 ou superior instalado pelo instalador oficial, com a opção `py` Launcher disponível e Tcl/Tk incluído.
- Acesso à rede local. O computador central precisa enviar consultas UDP à porta 161 das impressoras.

### Serviço central

1. Escolha um computador Windows que fique ligado durante o período de coleta.
2. Copie o repositório para uma pasta local, por exemplo `C:\Apps\PainelImpressoras`.
3. Execute `instalar_servidor.bat`. O script cria `.venv-servidor` e instala as dependências de `requirements.txt`.
4. Execute `iniciar_servidor.bat`. Mantenha a janela aberta.
5. Anote o endereço HTTPS e a impressão digital SHA256 apresentados no console. O mesmo conteúdo é gravado em `%APPDATA%\ContadoresImpressoras\conexao.txt`.
6. Se o Firewall do Windows bloquear clientes, execute `liberar_porta_servidor.bat` como administrador. A regra é para TCP 8765 no perfil privado.
7. Confirme que o computador alcança as impressoras na rede e que SNMP de leitura está habilitado.

O serviço escuta em TCP 8765 e consulta por UDP 161. Não encaminhe a porta para a internet.

### Clientes

1. Copie a pasta do projeto para cada computador Windows da equipe.
2. Execute `instalar_cliente.bat` e, em seguida, `abrir_cliente.bat`.
3. Informe o endereço HTTPS e a impressão digital SHA256 do serviço central. O endereço deve conter `https://` e os dois valores devem ser colocados em campos separados.
4. Na primeira conexão, crie a conta administrativa inicial.
5. Cadastre as contas adicionais e os equipamentos conforme [Configuração](CONFIGURACAO.md).

Clientes só precisam alcançar o serviço central em TCP 8765. Não é necessário liberar SNMP nos computadores clientes.

## Opção B: gerar executáveis

Os executáveis não são versionados no repositório. Em um computador Windows de compilação com Python 3.10+, execute `build_windows.bat`. O script cria `.venv-build`, instala `requirements-build.txt` e gera os arquivos `ContadoresClienteAtualizado.exe` e `ContadoresServidorAtualizado.exe` dentro de `release`.

Copie a pasta do projeto que contém `release` para o servidor e para as estações. No servidor, execute `iniciar_servidor.bat`; nos clientes, execute `abrir_cliente.bat`. Python não é necessário nas máquinas onde se usa o executável compilado.

O executável do servidor é console e precisa permanecer aberto. O cliente é uma aplicação gráfica. Para atualizar, feche a instância antiga, copie a versão nova e reinicie o respectivo programa.

## Primeiro uso e identificação do serviço

O cliente fixa o certificado do servidor pela impressão digital SHA256. Isso protege contra conexão a um servidor diferente dentro da rede. Ao trocar ou recriar o certificado, confira a nova impressão digital no computador central e atualize os clientes. O endereço IP pode mudar se a rede não reservar um IP fixo para o computador central.

## Instalação automática ao iniciar o Windows

O projeto não registra serviço Windows nem tarefa de inicialização automaticamente. Para coleta contínua, mantenha a sessão Windows do computador central ativa e inicie o servidor manualmente após reinicializações. A instalação como serviço Windows pode ser configurada à parte, garantindo que use o mesmo perfil de usuário e `%APPDATA%` que contém o banco e o certificado.
