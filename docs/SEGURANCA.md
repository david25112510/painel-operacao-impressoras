# Segurança e privacidade

## Limites de implantação

Esta aplicação é projetada para uma rede privada autogerenciada. Ela ainda não possui separação de papéis: todas as contas são administradoras. Não exponha o serviço HTTPS TCP 8765 à internet nem a redes de convidados ou não confiáveis.

## Rede

- Restringir UDP 161 de saída ao servidor central e às impressoras cadastradas.
- Restringir TCP 8765 de entrada ao perfil privado e aos clientes autorizados.
- SNMP v1/v2c transmite comunidade e dados sem criptografia. Use uma comunidade exclusiva de leitura e segmentação de rede. SNMPv3 não é implementado nesta versão.
- O serviço usa HTTPS com certificado autoassinado e fingerprint fixado no cliente. Verifique a fingerprint por um canal confiável ao configurar cada estação.

## Contas e dados

- Senhas são armazenadas como hash PBKDF2-HMAC-SHA256 com salt individual; o valor original não é guardado.
- Sessões expiram em 12 horas. Todas as contas têm privilégios administrativos.
- A comunidade SNMP é armazenada no banco SQLite local. Proteja as permissões NTFS da pasta `%APPDATA%\ContadoresImpressoras`.
- Backups incluem o banco, inclusive hashes, comunidades, histórico e imagens. Restrinja ACLs do NAS/compartilhamento.
- A chave privada TLS fica nessa pasta e não é incluída no backup ZIP padrão. Proteja-a para manter a identidade TLS ao migrar o servidor.
- Não inclua endereços IP, comunidades SNMP, banco, certificados, chaves, exportações ou fotos de equipamentos em issues ou pull requests públicos.

## Divulgação responsável

Não publique credenciais, fingerprints privadas de ambientes, caminhos internos, dados pessoais ou detalhes de vulnerabilidade em uma issue pública. Se encontrar um problema de segurança, contate o mantenedor pelo perfil GitHub e compartilhe apenas os detalhes necessários em canal privado.

## Lista antes da implantação

- [ ] Comunidades SNMP são somente leitura e não reutilizadas fora da VLAN de impressoras.
- [ ] O servidor está em rede privada com firewall restritivo.
- [ ] A pasta de dados e o destino de backup são acessíveis apenas por operadores autorizados.
- [ ] As contas têm senhas fortes e cada usuário tem login individual.
- [ ] Há teste de restauração de backup realizado pelo administrador.
- [ ] A fingerprint configurada nos clientes foi obtida do servidor esperado.
