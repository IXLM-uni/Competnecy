<!--
Руководство к файлу: AI.md
1) Назначение: краткий справочник по классам/функциям модулей AI (llm_service, llm_qdrant, llm_asr, llm_webcrawler, llm_semantic_scholar).
2) Как читать: разделы по модулям; формат «Название → Что делает → Когда использовать → Ссылка».
3) Обновление: при добавлении/изменении публичных методов, DTO, фабрик или оркестраторов дополняйте этот файл.
4) Локализация: писать по-русски, следовать логированию «ШАГ ...» как в коде.
-->

# AI модули — справочник

## Легенда
- **Название** — класс/функция.
- **Что делает** — кратко.
- **Когда использовать** — основной сценарий.
- **Ссылка** — `@filepath#строка-строка`.

---

## llm_asr.py (ASR UC-20)
- **TranscriptSegment** → DTO сегмента (start/end/text/speaker) → хранение кусочков речи → @/home/alexander/Projects/Global_services/AI/llm_asr.py#43-48
- **Transcript** → DTO транскрипта (segments/text/language) → результат ASR → @/home/alexander/Projects/Global_services/AI/llm_asr.py#50-55
- **ASRClient** → клиент Cloud.ru ASR + безопасный fallback (сжатие, нарезка, очередь) → транскрибация файлов/байтов аудио → @/home/alexander/Projects/Global_services/AI/llm_asr.py#57-755
  - `__init__` → конфиг API/лимитов → @/home/alexander/Projects/Global_services/AI/llm_asr.py#93-115
  - `transcribe` → отправка bytes в `/audio/transcriptions` → @/home/alexander/Projects/Global_services/AI/llm_asr.py#116-207
  - `transcribe_file` → вход по пути файла, direct или fallback → @/home/alexander/Projects/Global_services/AI/llm_asr.py#209-284
  - `_transcribe_path` → валидация размера + чтение файла → @/home/alexander/Projects/Global_services/AI/llm_asr.py#285-310
  - `_transcribe_with_preprocess` → сжатие/нарезка/очередь + merge → @/home/alexander/Projects/Global_services/AI/llm_asr.py#311-453
  - `_prepare_chunks_for_transcription` → решает, сжимать/резать → @/home/alexander/Projects/Global_services/AI/llm_asr.py#454-513
  - `_compress_audio_for_asr` → ffmpeg в Opus 16k mono → @/home/alexander/Projects/Global_services/AI/llm_asr.py#514-545
  - `_split_audio_into_chunks` → нарезка по лимиту payload → @/home/alexander/Projects/Global_services/AI/llm_asr.py#546-651
  - `_probe_duration_seconds` → длительность через ffprobe → @/home/alexander/Projects/Global_services/AI/llm_asr.py#652-700
  - `_run_command` → безопасный subprocess (ffmpeg/ffprobe) → @/home/alexander/Projects/Global_services/AI/llm_asr.py#701-733
  - `_build_chunk_context` → ctx для чанка (трассировка) → @/home/alexander/Projects/Global_services/AI/llm_asr.py#734-755

---

## llm_webcrawler.py (Интернет-поиск)
- **CrawlerQueryRewriter** → генерирует web-перефразы через LLM → перед интернет-поиском → @/home/alexander/Projects/Global_services/AI/llm_webcrawler.py#35-73
  - `rewrite` → возвращает список поисковых запросов (JSON) → @/home/alexander/Projects/Global_services/AI/llm_webcrawler.py#42-73
- **CrawlerClient** → клиент crawler-сервера (`/health`, `/crawl`, search orchestration) → веб-краулинг в UC-1 → @/home/alexander/Projects/Global_services/AI/llm_webcrawler.py#75-203
  - `_is_url` → проверяет, что строка уже URL → @/home/alexander/Projects/Global_services/AI/llm_webcrawler.py#95-98
  - `_query_to_search_url` → DuckDuckGo HTML для текста → @/home/alexander/Projects/Global_services/AI/llm_webcrawler.py#100-104
  - `health_check` → проверка доступности crawler → @/home/alexander/Projects/Global_services/AI/llm_webcrawler.py#105-112
  - `crawl_urls` → `/crawl`, сбор Snippet → @/home/alexander/Projects/Global_services/AI/llm_webcrawler.py#113-175
  - `search` → orchestration: query→url→crawl → @/home/alexander/Projects/Global_services/AI/llm_webcrawler.py#176-203

---

## llm_semantic_scholar.py (Semantic Scholar)
- **S2SearchFilter** → фильтры поиска статей (fields/year/citations/oa) → уточнение search → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#71-94
- **S2FieldInference** → LLM-инференс fieldsOfStudy → когда нужно автоопределить области → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#96-174
- **S2Client** → async-клиент Semantic Scholar SDK (поиск, авторы, цитаты, рекомендации) → основной API → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#176-667
  - `search_papers` → поиск статей → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#326-370
  - `get_paper` → детали статьи → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#371-400
  - `search_authors` / `get_author` / `get_author_papers` → авторы и их работы → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#401-504
  - `get_paper_citations` / `get_paper_references` → цитаты/ссылки → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#505-586
  - `get_recommendations_single` / `get_recommendations_from_lists` → рекомендации → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#587-667
  - Утилиты: `_parse_tldr`, `paper_to_dict`, `author_to_dict`, `paper_embed_text`, `paper_citation_key`, `paper_to_text` → @/home/alexander/Projects/Global_services/AI/llm_semantic_scholar.py#230-325

---

## llm_qdrant.py (Embeddings + Vector Store + RAG Retrieval)
- **SparseVectorData** → нормализованный sparse-вектор (indices/values) + валидация/конверсия в Qdrant → hybrid поиск → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#50-92
- **QdrantCollectionConfig** → параметры коллекции (dense/sparse/payload/HNSW) → создание коллекции → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#94-121
- **HybridSearchConfig** → настройки hybrid (RRF/DBSF, prefetch, score_threshold) → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#123-133
- **EmbeddingClient** → sentence-transformers dense embed (lazy, sync→executor) → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#135-168
- **CloudRuEmbeddingClient** → dense embed через Cloud.ru OpenAI-compatible → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#170-241
- **SparseEmbeddingClient** → sparse embed через SparseEncoder → hybrid RAG → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#243-396
- **VectorStore** → интерфейс upsert/search → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#398-423
- **QdrantVectorStore** → реализация VectorStore на AsyncQdrantClient → upsert/search/ensure/delete/info/count → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#425-874
  - `_ensure_collection` → создаёт dense+sparse коллекцию + payload индексы → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#446-549
  - `_ensure_payload_indexes` → индексы по payload → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#550-596
  - `delete_collection` / `get_collection_info` / `count_points` → сервисные опции → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#596-663
  - `upsert` → запись точек (dense+sparse) → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#692-753
  - `search` → dense-only или hybrid (RRF/DBSF) → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#754-874
- **Retriever** → orchestrator retrieval (embed query → vector search → merge multi) → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#1055-1136
- **ingest_and_index** (function) → bulk: files → ingest → chunk → dense/sparse embed → upsert → @/home/alexander/Projects/Global_services/AI/llm_qdrant.py#877-1053

---

## llm_service.py (Фасад: DTO + Orchestrator + фабрики)
### DTO/контракты
- `TokenUsage`, `RequestContext`, `ToolCall`, `ToolResult`, `ChatMessage`, `FileRef`, `UserInput`, `LLMMessage`, `LLMRequest`, `LLMResponse`, `StreamEvent`, `DocumentChunk`, `IndexMetadata`, `Snippet`, `OrchestratorResult` → базовые схемы/контекст → @/home/alexander/Projects/Global_services/AI/llm_service.py#155-339

### Контекст/валидация
- **ContextBuilder** → сбор LLMRequest из system+history+RAG/web/docs → @/home/alexander/Projects/Global_services/AI/llm_service.py#346-452
- **JsonRepairLLM** → чинит поломанный JSON из LLM → @/home/alexander/Projects/Global_services/AI/llm_service.py#459-489
- **StrictOutputParser** → Pydantic-валидация + авторемонт JSON → @/home/alexander/Projects/Global_services/AI/llm_service.py#491-523

### Tools
- **ToolSpec**, **ToolRequestContext**, **ToolRegistry**, **ToolExecutor** → регистрация/исполнение tool-calls → @/home/alexander/Projects/Global_services/AI/llm_service.py#530-660

### Ingest
- **Chunker** → токен-чанкинг → @/home/alexander/Projects/Global_services/AI/llm_service.py#667-736
- **DocumentIngestor** → ingest PDF/DOCX/HTML/TXT + скан директорий → @/home/alexander/Projects/Global_services/AI/llm_service.py#738-950

### RAG / Query rewriters
- **RagQueryRewriter** → перефраз запроса для RAG → @/home/alexander/Projects/Global_services/AI/llm_service.py#973-1008
  - `rewrite` → возвращает список перефраз (JSON) → @/home/alexander/Projects/Global_services/AI/llm_service.py#980-1008

### LLM клиент
- **OpenAIClient** → sync/stream вызовы LLM + tool-calls → @/home/alexander/Projects/Global_services/AI/llm_service.py#1030-1182
  - `create_response` → обычный вызов → @/home/alexander/Projects/Global_services/AI/llm_service.py#1042-1099
  - `stream_response` → стриминг + сбор tool_calls → @/home/alexander/Projects/Global_services/AI/llm_service.py#1100-1182

### Оркестратор
- **ChatOrchestrator** → единый pipeline UC-1..UC-5/20 (ASR, RAG, интернет, tools, JSON-валидация) → @/home/alexander/Projects/Global_services/AI/llm_service.py#1189-1703
  - `handle_user_input` → non-stream, tool-loop, JSON repair → @/home/alexander/Projects/Global_services/AI/llm_service.py#1229-1451
  - `stream_user_input` → streaming + tools → @/home/alexander/Projects/Global_services/AI/llm_service.py#1457-1632
  - `_run_rag` → перефразы + retrieve_multi → @/home/alexander/Projects/Global_services/AI/llm_service.py#1638-1659
  - `_run_internet` → crawler pipeline → @/home/alexander/Projects/Global_services/AI/llm_service.py#1661-1687

### Фабрики / утилиты UC
- `create_cloudru_openai_client_from_env` → @/home/alexander/Projects/Global_services/AI/llm_service.py#1710-1721
- `create_cloudru_asr_client_from_env` → @/home/alexander/Projects/Global_services/AI/llm_service.py#1723-1767
- `create_cloudru_embedding_client_from_env` → @/home/alexander/Projects/Global_services/AI/llm_service.py#1770-1786
- `create_sparse_embedding_client_from_env` → @/home/alexander/Projects/Global_services/AI/llm_service.py#1788-1796
- `create_default_orchestrator_from_env` → сборка оркестратора → @/home/alexander/Projects/Global_services/AI/llm_service.py#1798-1863
- `generate_indexing_report` → JSON-отчёт индексации → @/home/alexander/Projects/Global_services/AI/llm_service.py#1871-1922
- `load_env_and_validate` → загрузка .env + валидация ключей → @/home/alexander/Projects/Global_services/AI/llm_service.py#1930-1999
- `create_rag_clients_from_env` → фабрика RAG-клиентов → @/home/alexander/Projects/Global_services/AI/llm_service.py#2002-2054
- `build_rag_prompt` / `build_web_prompt` → промпт-шаблоны → @/home/alexander/Projects/Global_services/AI/llm_service.py#2057-2174
- `stream_llm_to_stdout` → стриминг в stdout (CLI) → @/home/alexander/Projects/Global_services/AI/llm_service.py#2177-2248
- `query_llm_simple` → non-stream helper → @/home/alexander/Projects/Global_services/AI/llm_service.py#2251-2304

---

## Быстрые сценарии (подсказки)
- **Индексировать директорию**: `scan_directory` (DocumentIngestor) → `ingest_and_index` (llm_qdrant).
- **Задействовать RAG**: `Retriever.retrieve_multi` + `build_rag_prompt` → в `ChatOrchestrator`.
- **Интернет-поиск**: `CrawlerQueryRewriter.rewrite` → `CrawlerClient.search` → `build_web_prompt`.
- **ASR**: `ASRClient.transcribe_file` → возвращает `Transcript` (text + segments).