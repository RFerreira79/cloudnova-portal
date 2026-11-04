# CloudNova - Portal Corporativo Seguro na Nuvem

Aplicacao web Flask com login Microsoft Entra ID, base de dados Azure SQL (Private Endpoint)
e Azure Blob Storage (Private Endpoint), implantada em Azure Container Instances numa VNet
isolada, com saida controlada pelo Azure Firewall.

Cada push na branch `main` executa o pipeline `.github/workflows/ci-cd.yml`:
1. valida (flake8), compila e testa (pytest) o codigo;
2. gera a imagem e envia-a para o Azure Container Registry;
3. atualiza o contentor no Azure Container Instances.

Todas as credenciais estao nos Secrets do repositorio (nunca no codigo).
