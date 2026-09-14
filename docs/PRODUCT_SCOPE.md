# Op_PM — escopo inicial

## Direção recomendada

Construir uma webapp com login, API e base de dados. A aplicação deve ser a fonte operacional principal, mantendo integrações com ClickUp, Microsoft 365/Outlook, OneDrive/SharePoint e Financial.

Para até cinco utilizadores e sem requisito offline, uma solução web alojada é preferível à sincronização por JSON numa pasta partilhada. A Drive deve continuar a ser usada para documentos, mas não como base de dados de operações.

## Perfis e permissões

- Administrador
- Chefe de operações
- Project manager
- Comercial
- Financeiro

As permissões devem ser aplicadas no servidor e registadas no histórico. Escolher apenas “PM” ou “Chefe” na interface não é autenticação.

## Módulos prioritários

1. Projetos, clientes, PMs e identificadores estáveis.
2. Dashboard semanal e vista comercial.
3. Planeamento, calendário e visitas técnicas.
4. Formulários, documentos e fotografias.
5. Mapa de instalações, fornecedores e recolhas.
6. Inventário, reservas e pedidos de material.
7. Custos, adjudicações e integração com Financial.
8. Relatórios internos e automações com Claude.

## Funcionalidades pretendidas

### Dashboard

- estatísticas semanais;
- trabalhos a fazer e atrasados;
- próximas visitas e comissionamentos;
- vista comercial;
- férias e aniversários;
- filtros por PM, estado, cliente e período.

### Visitas e deslocações

- criar visita técnica;
- consultar disponibilidade;
- propor horários ao cliente;
- calcular deslocações;
- conciliar várias deslocações;
- otimizar rotas;
- gerar rascunho de email e evento;
- exigir aprovação humana antes de enviar ou reservar.

### Mapa

- instalações;
- fornecedores;
- recolha de material;
- visitas e rotas;
- filtros operacionais.

### Inventário e compras

- stock atual, mínimo e reservado;
- material em trânsito;
- previsão de consumo pelas obras futuras;
- alertas de ruptura;
- pedido de material por projeto;
- email preparado para fornecedores;
- orçamentos e anexos;
- aprovação, adjudicação e envio ao financeiro.

### Custos

- orçamento estimado;
- adjudicações;
- compras e subempreiteiros;
- deslocações;
- custo previsto e real;
- margem e desvios;
- integração com Financial.

### Documentos e formulários

Biblioteca na Drive/OneDrive para inversores, contadores, meters, segurança, painéis, cabos, estruturas, carregadores VE, material elétrico, baterias, backups e documentação de subempreiteiros.

Cada projeto deve permitir formulários de visita técnica e comissionamento, anexos e fotografias. O fecho deve gerar um lembrete ou bloqueio quando as fotografias obrigatórias não existirem.

### Claude

O Claude deve apoiar, não substituir, as regras da aplicação. Pode:

- propor visitas e rotas;
- preparar emails;
- analisar listas de material e orçamentos;
- pesquisar manuais relevantes;
- preparar relatórios semanais;
- resumir riscos e pendências.

Envio de emails, marcação de calendário, adjudicações e alterações de custos devem ter aprovação humana e auditoria.

## Critérios de arquitetura

- IDs estáveis para projetos e tarefas ClickUp;
- base de dados transacional;
- histórico de alterações;
- deteção de conflitos;
- validação de schemas;
- API server-side para segredos e integrações;
- dados de produção fora do GitHub;
- fixtures fictícias para testes;
- backups e recuperação testados;
- suporte a Outlook clássico e novo através de Microsoft Graph quando possível.
