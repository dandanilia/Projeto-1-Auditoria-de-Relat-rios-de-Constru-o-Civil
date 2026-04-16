import os
import pandas as pd
import json
import time
import re
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_community.document_loaders import PyPDFLoader

# Carrega a chave do arquivo .env
load_dotenv()

# --- CONFIGURAÇÕES DE PASTAS ---
PASTA_ENTRADA = './inspecoes_pdfs/'  # Pasta com os PDFs de teste
PASTA_SAIDA = './saidas_excel/'      # Pasta onde o Excel será salvo

if not os.path.exists(PASTA_SAIDA):
    os.makedirs(PASTA_SAIDA)

# Inicializa o modelo GPT-4o
llm = ChatOpenAI(model_name="gpt-4o", temperature=0)

def extrair_dados_samarco(caminho_pdf):
    try:
        loader = PyPDFLoader(caminho_pdf)
        paginas = loader.load()
        texto_completo = "\n".join([p.page_content for p in paginas])

        # --- PROMPT PARA ABA 1: RESUMO ---
        prompt_resumo = f"""
        Você é um engenheiro de dados. Analise o relatório Samarco e extraia APENAS dados de cabeçalho e a tabela de resumo.
        Retorne estritamente um JSON.

        DIRETRIZES:
        1. CABEÇALHO: Extraia Nº SAP/OS, RT, Data.
        2. TABELA RESUMO (Pág 1): Extraia a soma de 'EVIDENCIAS' para as disciplinas 'TAC', 'REC' e 'REC/CONCRETO'.

        ESTRUTURA DO JSON RESUMO (Objeto único):
        "sap_os", "rt", "data_relatorio", "total_evidencias_tac_rec"

        DOCUMENTO:
        {texto_completo}
        """

        # --- PROMPT PARA ABA 2: DETALHES ---
        prompt_detalhes = f"""
        Você é um auditor de engenharia estrutural. Converta o PDF em uma lista exaustiva de atividades.
        Busque os dados detalhados obrigatoriamente no item '2.5 Conclusões'.
        Retorne estritamente uma LISTA de objetos JSON.

        DIRETRIZES CRÍTICAS:
        1. EXAUSTIVIDADE: Gere EXATAMENTE uma linha para cada recomendação numerada no item '2.5 Conclusões'. Não pule nada.
        2. CRUZAMENTO: Relacione cada conclusão com o 'Dano Identificado' e 'Página' correspondente no corpo do relatório.
        3. REMOÇÃO: Não extraia dados de Rastreabilidade.

        ESTRUTURA DO JSON DETALHES (Lista de objetos):
        "id_atividade", "sap_os", "rt", "data_do_retaorio", "grupo_da_atividade", "tipo_de_intervencao", "disciplina", "area", "subarea", "equipamento", "tag",  
        "elemento", "localização_detalhada", "pavimento_nivel", "observação_do_relatorio", "dano_identificado", "comentario_tecnico", 
        "recomendacao_executiva", "quantidade_de_peças", "peso", "unidade", "dimensoes", "criticidade", 
        "classe_ie", "nota_gut", "priorizacao","recomendação_para_execução", "data_recomendada_no_relatorio", "Risco_de_seguranca", "Necessita_isolamento", "Necessita_atendimento_NR12" 
        DOCUMENTO:
        {texto_completo}
        """

        # Executa as duas extrações
        print("   -> Extraindo Resumo (Aba 1)...")
        res_resumo = llm.invoke(prompt_resumo).content
        
        print("   -> Extraindo Detalhes Exaustivos (Aba 2)...")
        res_detalhes = llm.invoke(prompt_detalhes).content

        # Limpeza e parsing dos JSONs
        json_resumo = json.loads(re.sub(r'```json\n|\n```', '', res_resumo))
        json_detalhes = json.loads(re.sub(r'```json\n|\n```', '', res_detalhes))
        
        # Garante que detalhes seja uma lista
        if not isinstance(json_detalhes, list): json_detalhes = [json_detalhes]

        return json_resumo, json_detalhes
    
    except Exception as e:
        print(f"Erro no arquivo {os.path.basename(caminho_pdf)}: {e}")
        return None, None

def executar_processamento():
    print(f"Verificando pasta: {os.path.abspath(PASTA_ENTRADA)}")
    arquivos = [f for f in os.listdir(PASTA_ENTRADA) if f.lower().endswith('.pdf')]
    
    if not arquivos:
        print("⚠️ Nenhum PDF encontrado.")
        return

    print(f"🚀 Iniciando extração de {len(arquivos)} arquivos...")
    
    todos_resumos = []
    todos_detalhes = []
    
    for i, nome_arq in enumerate(arquivos):
        caminho = os.path.join(PASTA_ENTRADA, nome_arq)
        print(f"[{i+1}/{len(arquivos)}] Processando: {nome_arq}")
        
        resumo, detalhes = extrair_dados_samarco(caminho)
        
        if resumo and detalhes:
            resumo['Arquivo Fonte'] = nome_arq
            todos_resumos.append(resumo)
            
            # Validação: Compara total de linhas geradas com a soma da tabela resumo
            total_gerado = len(detalhes)
            total_esperado = resumo.get('total_evidencias_tac_rec', 0)
            
            status_validacao = "✅ OK" if total_gerado == total_esperado else "⚠️ DIVERGENTE"
            print(f"   -> {status_validacao}: {total_gerado} linhas geradas / {total_esperado} esperadas nas Conclusões.")
            
            for item in detalhes:
                item['Arquivo Fonte'] = nome_arq
                todos_detalhes.append(item)
        
        time.sleep(2) # Respiro para a API

    if todos_resumos and todos_detalhes:
        # Cria os DataFrames
        df_resumo = pd.DataFrame(todos_resumos)
        df_detalhes = pd.DataFrame(todos_detalhes)

        # Mapeamento de nomes amigáveis (Aba 2 - Sem Rastreabilidade)
        map_detalhes = {
            "sap_os": "Nº SAP / O.S.", "rt": "RT", "id_atividade": "ID Atividade",
            "disciplina": "Disciplina", "area": "Área", "subarea": "Subárea",
            "equipamento": "Equipamento", "tag": "TAG", "elemento": "Elemento",
            "pavimento_nivel": "Pavimento / Nível", "dano_identificado": "Dano Identificado",
            "comentario_tecnico": "Comentário Técnico", "recomendacao_executiva": "Recomendação Executiva",
            "quantidade": "Qtde", "unidade": "Unid", "dimensoes": "Dimensões",
            "criticidade": "Criticidade", "classe_ie": "Classe / IE", "nota_gut": "GUT",
            "priorizacao": "Priorização", "Risco_de_seguranca": "Risco Segurança",
            "Arquivo Fonte": "Arquivo PDF"
        }
        df_detalhes.rename(columns=map_detalhes, inplace=True)

        # --- SALVANDO EM DUAS ABAS ---
        nome_final = os.path.join(PASTA_SAIDA, f"Relatorio_Samarco_Auditoria_{int(time.time())}.xlsx")
        
        with pd.ExcelWriter(nome_final) as writer:
            df_resumo.to_excel(writer, sheet_name='Resumo_Priorizacao', index=False)
            df_detalhes.to_excel(writer, sheet_name='Detalhes_Conclusoes', index=False)
            
        print(f"\n✅ SUCESSO! Arquivo com 2 abas gerado em: {nome_final}")
    else:
        print("\n❌ Nenhuma atividade extraída.")

if __name__ == "__main__":
    executar_processamento()
