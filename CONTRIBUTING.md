# Contribuindo

Obrigado pelo interesse. Antes de abrir uma alteração:

1. Descreva o problema e os passos para reproduzi-lo sem publicar endereços internos, comunidades SNMP, fingerprints, banco ou fotos de clientes.
2. Para mudanças grandes de interface, esquema de dados ou suporte SNMP, abra primeiro uma discussão/issue sem dados operacionais privados.
3. Mantenha suporte a Windows 10/11 e Python 3.10+ até que a política do projeto mude.
4. Prefira objetos SNMP padronizados e trate a ausência de tabelas/valores opcionais sem marcar a impressora offline.
5. Atualize a documentação e informe impactos em banco, backup, compatibilidade ou segurança.
6. Não adicione bibliotecas, binários, dados de impressoras ou imagens sem necessidade e licença clara.

## Preparar ambiente

```powershell
py -3 -m venv .venv-dev
.venv-dev\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-client.txt
```

Para gerar executáveis Windows, execute `build_windows.bat`. O processo gera arquivos em `release`, ignorados pelo Git.

## Revisão antes de enviar

- Reveja a diferença completa e confirme que nenhum dado real de rede ou segredo foi adicionado.
- Não versione banco SQLite, certificados, chaves, backups, exports, `.venv`, `work` ou `release`.
- Descreva como a alteração foi validada. Para SNMP, use impressoras/MIBs de laboratório ou dados simulados; não publique credenciais de uma instalação.
