1. Arquitetura de Telas e Fluxo do Usuário
Plaintext
┌─────────────────────────────────────────────────────────────────────────────────┐
│ TELA 1: Grid de Notebooks (Home)                                                │
│  - Grid de Cards (Título, Objetivo, Data, Contagem de Fontes)                  │
│  - Menu de Três Pontos por Card: [Editar Título/Objetivo] | [Excluir Caderno]   │
│  - Botão Primário Header: [+ Criar Novo Caderno]                                │
└───────────────────────────────────────┬─────────────────────────────────────────┘
                                        │ (Clique no Botão / Abre Modal)
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ MODAL: Criar Novo Caderno                                                       │
│  - Inputs: Nome do Caderno + Objetivo do Treinamento                            │
│  - Drag & Drop: Arquivos (PDF, MD, TXT, PNG, JPG)                               │
│  - Inputs de Link: Documentação (URL) + Vídeo (YouTube)                         │
│  - Botão: [Gerar Pré-Análise] ──► (Instancia no notebooklm-py, baixa fontes,    │
│                                    gera .md e abre a Tela 2)                    │
└───────────────────────────────────────┬─────────────────────────────────────────┘
                                        │ (Redirecionamento Automático)
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ TELA 2: Detalhes do Caderno (Visão de Duas Colunas)                              │
│ ┌──────────────────────────────────┬──────────────────────────────────────────┐ │
│ │ Coluna Esquerda (Fontes)         │ Coluna Direita (Pré-Análise)             │ │
│ │ - Lista de Fontes com Badges:    │ - Viewer Markdown do Resultado           │ │
│ │   [Pronto] ou [Indexando...]     │ - Botões no Topo: [Copiar] [Baixar .md]  │ │
│ │ - Botão: [+ Adicionar Nova Fonte]│ - Botão Flutuante: [🔄 Atualizar Análise]│ │
│ └──────────────────────────────────┴──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
2. Requisitos Atualizados
RF-01 (Ações de Grid - Melhora 2): O grid inicial deve exibir cards interativos com menu contextual (três pontos) para Editar Título/Objetivo e Excluir Caderno.

RF-02 (Gestão de Estados de Fontes - Melhora 1): Cada fonte vinculada ao caderno deve exibir o status de processamento (INDEXING ou READY). O botão "Atualizar Pré-Análise" permanece desabilitado enquanto houverem mídias no estado INDEXING.

RF-03 (Exportação de Resultados - Melhora 3): A caixa de visualização da pré-análise deve oferecer ações de Copiar Texto para a área de transferência e Baixar Arquivo .md.

RF-04 (Integração de Motores): Conexão via notebooklm-py para gestão de cadernos/fontes no Google e Gemma 4 31B (via OpenRouter) para inferência do prompt do analista GEM.