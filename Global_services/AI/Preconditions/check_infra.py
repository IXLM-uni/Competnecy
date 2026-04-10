# -*- coding: utf-8 -*-
"""
Руководство к файлу check_infra.py
===================================

Назначение:
    Проверка готовности инфраструктуры для e2e-тестов.
    Выполняет последовательные проверки:
      ШАГ 1. Переменные окружения (CLOUDRU_API_KEY, CLOUDRU_BASE_URL и т.д.)
      ШАГ 2. Доступность Cloud.ru LLM API (chat/completions ping)
      ШАГ 3. Доступность Cloud.ru Embedding API (/v1/embeddings ping)
      ШАГ 4. Доступность Cloud.ru ASR API (проверка endpoint)
      ШАГ 5. Доступность Qdrant (GET /collections)
      ШАГ 6. Наличие тестовых данных (documents/, RAG/Data.txt, audio/)
      ШАГ 7. Итоговый отчёт

    Возвращает словарь {check_name: bool, ...} и выводит цветной отчёт
    в stdout.

Переменные окружения:
    CLOUDRU_API_KEY, CLOUDRU_BASE_URL, CLOUDRU_MODEL_NAME,
    CLOUDRU_EMBED_MODEL, QDRANT_HOST, QDRANT_PORT

Использование:
    python -m AI.Preconditions.check_infra
    # или
    python AI/Preconditions/check_infra.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

logger = logging.getLogger(__name__)

PRECONDITIONS_DIR = os.path.dirname(os.path.abspath(__file__))


async def check_env_vars() -> dict:
    """ШАГ 1. Проверка переменных окружения."""
    logger.info("ШАГ 1. Проверка переменных окружения — ОТПРАВЛЯЕМ")
    required = ["CLOUDRU_API_KEY"]
    optional = [
        "CLOUDRU_BASE_URL", "CLOUDRU_MODEL_NAME",
        "CLOUDRU_EMBED_MODEL", "QDRANT_HOST", "QDRANT_PORT",
    ]
    result: dict = {"required": {}, "optional": {}}
    all_ok = True

    for var in required:
        val = os.environ.get(var)
        present = bool(val)
        result["required"][var] = present
        if not present:
            all_ok = False
            logger.error("ШАГ 1. ОШИБКА: %s не задан", var)
        else:
            logger.info("ШАГ 1. %s = %s...%s", var, val[:8], val[-4:])

    for var in optional:
        val = os.environ.get(var, "")
        result["optional"][var] = val or "(не задан, будет default)"
        logger.info("ШАГ 1. %s = %s", var, val or "(default)")

    result["ok"] = all_ok
    logger.info("ШАГ 1. %s", "УСПЕХ" if all_ok else "ОШИБКА")
    return result


async def check_cloudru_llm() -> dict:
    """ШАГ 2. Проверка доступности Cloud.ru LLM API."""
    logger.info("ШАГ 2. Проверка Cloud.ru LLM API — ОТПРАВЛЯЕМ")
    api_key = os.environ.get("CLOUDRU_API_KEY", "")
    base_url = os.environ.get(
        "CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1",
    )
    model = os.environ.get("CLOUDRU_MODEL_NAME", "zai-org/GLM-4.7")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                },
            )
            ok = response.status_code in (200, 201)
            logger.info(
                "ШАГ 2. Cloud.ru LLM: status=%d — %s",
                response.status_code, "УСПЕХ" if ok else "ОШИБКА",
            )
            return {"ok": ok, "status_code": response.status_code}
    except Exception as exc:
        logger.error("ШАГ 2. Cloud.ru LLM ОШИБКА: %s", exc)
        return {"ok": False, "error": str(exc)}


async def check_cloudru_embeddings() -> dict:
    """ШАГ 3. Проверка Cloud.ru Embedding API."""
    logger.info("ШАГ 3. Проверка Cloud.ru Embedding API — ОТПРАВЛЯЕМ")
    api_key = os.environ.get("CLOUDRU_API_KEY", "")
    base_url = os.environ.get(
        "CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1",
    )
    model = os.environ.get("CLOUDRU_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": ["тестовый текст для проверки"],
                },
            )
            ok = response.status_code in (200, 201)
            data = response.json() if ok else {}
            dim = len(data.get("data", [{}])[0].get("embedding", [])) if ok else 0
            logger.info(
                "ШАГ 3. Cloud.ru Embeddings: status=%d, dim=%d — %s",
                response.status_code, dim, "УСПЕХ" if ok else "ОШИБКА",
            )
            return {"ok": ok, "status_code": response.status_code, "dim": dim}
    except Exception as exc:
        logger.error("ШАГ 3. Cloud.ru Embeddings ОШИБКА: %s", exc)
        return {"ok": False, "error": str(exc)}


async def check_cloudru_asr() -> dict:
    """ШАГ 4. Проверка Cloud.ru ASR (проверяем доступность endpoint)."""
    logger.info("ШАГ 4. Проверка Cloud.ru ASR endpoint — ОТПРАВЛЯЕМ")
    api_key = os.environ.get("CLOUDRU_API_KEY", "")
    base_url = os.environ.get(
        "CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1",
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Отправляем минимальный запрос — ожидаем 4xx/2xx, но не connection error
            response = await client.post(
                f"{base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data={"model": "openai/whisper-large-v3"},
                files={"file": ("test.wav", b"RIFF" + b"\x00" * 40, "audio/wav")},
            )
            # Любой ответ (даже 400) означает, что endpoint доступен
            reachable = response.status_code < 500
            logger.info(
                "ШАГ 4. Cloud.ru ASR: status=%d — %s",
                response.status_code,
                "ДОСТУПЕН" if reachable else "ОШИБКА СЕРВЕРА",
            )
            return {"ok": reachable, "status_code": response.status_code}
    except Exception as exc:
        logger.error("ШАГ 4. Cloud.ru ASR ОШИБКА: %s", exc)
        return {"ok": False, "error": str(exc)}


async def check_qdrant() -> dict:
    """ШАГ 5. Проверка доступности Qdrant."""
    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6334"))
    logger.info("ШАГ 5. Проверка Qdrant %s:%d — ОТПРАВЛЯЕМ", host, port)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"http://{host}:{port}/collections")
            ok = response.status_code == 200
            data = response.json() if ok else {}
            collections = [
                c.get("name", "?")
                for c in data.get("result", {}).get("collections", [])
            ]
            logger.info(
                "ШАГ 5. Qdrant: status=%d, collections=%s — %s",
                response.status_code, collections, "УСПЕХ" if ok else "ОШИБКА",
            )
            return {"ok": ok, "collections": collections}
    except Exception as exc:
        logger.error("ШАГ 5. Qdrant ОШИБКА (не запущен?): %s", exc)
        return {"ok": False, "error": str(exc)}


async def check_test_data() -> dict:
    """ШАГ 6. Проверка наличия тестовых данных."""
    logger.info("ШАГ 6. Проверка тестовых данных — ОТПРАВЛЯЕМ")

    checks = {}

    # documents/
    docs_dir = os.path.join(PRECONDITIONS_DIR, "documents")
    if os.path.isdir(docs_dir):
        doc_files = os.listdir(docs_dir)
        checks["documents"] = {"ok": len(doc_files) > 0, "files": doc_files}
    else:
        checks["documents"] = {"ok": False, "error": "директория не существует"}

    # RAG/Data.txt
    rag_path = os.path.join(PRECONDITIONS_DIR, "RAG", "Data.txt")
    checks["rag_data"] = {
        "ok": os.path.isfile(rag_path),
        "size_kb": round(os.path.getsize(rag_path) / 1024, 1) if os.path.isfile(rag_path) else 0,
    }

    # RAG/ground_truth.csv
    gt_path = os.path.join(PRECONDITIONS_DIR, "RAG", "ground_truth.csv")
    checks["ground_truth"] = {"ok": os.path.isfile(gt_path)}

    # audio/
    audio_dir = os.path.join(PRECONDITIONS_DIR, "audio")
    if os.path.isdir(audio_dir):
        audio_files = [f for f in os.listdir(audio_dir) if f.endswith(".wav")]
        checks["audio"] = {"ok": True, "wav_files": audio_files}
    else:
        checks["audio"] = {"ok": True, "note": "аудио будет сгенерировано при тесте"}

    # tools/
    tools_dir = os.path.join(PRECONDITIONS_DIR, "tools")
    checks["tools"] = {"ok": os.path.isdir(tools_dir)}

    all_ok = all(v.get("ok", False) for v in checks.values())
    logger.info("ШАГ 6. Тестовые данные: %s — %s", checks, "УСПЕХ" if all_ok else "ПРЕДУПРЕЖДЕНИЕ")
    return {"ok": all_ok, "details": checks}


async def run_all_checks() -> dict:
    """Запуск всех проверок последовательно.

    ШАГ 1. Переменные окружения
    ШАГ 2. Cloud.ru LLM
    ШАГ 3. Cloud.ru Embeddings
    ШАГ 4. Cloud.ru ASR
    ШАГ 5. Qdrant
    ШАГ 6. Тестовые данные
    ШАГ 7. Итоговый отчёт
    """
    from dotenv import load_dotenv

    env_path = os.path.join(PRECONDITIONS_DIR, "..", "..", ".env")
    load_dotenv(os.path.abspath(env_path))

    results: dict = {}

    results["env_vars"] = await check_env_vars()
    results["cloudru_llm"] = await check_cloudru_llm()
    results["cloudru_embeddings"] = await check_cloudru_embeddings()
    results["cloudru_asr"] = await check_cloudru_asr()
    results["qdrant"] = await check_qdrant()
    results["test_data"] = await check_test_data()

    # ШАГ 7. Итоговый отчёт
    logger.info("ШАГ 7. Итоговый отчёт:")
    all_passed = True
    for name, result in results.items():
        ok = result.get("ok", False)
        status = "✅ PASS" if ok else "❌ FAIL"
        logger.info("  %s  %s", status, name)
        if not ok:
            all_passed = False

    results["all_passed"] = all_passed
    logger.info(
        "ШАГ 7. Общий статус: %s",
        "✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if all_passed else "❌ ЕСТЬ ПРОБЛЕМЫ",
    )
    return results


def _print_report(results: dict) -> None:
    """Печать цветного отчёта в stdout."""
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    print(f"\n{BOLD}{'='*60}")
    print(f"  ПРОВЕРКА ИНФРАСТРУКТУРЫ ДЛЯ e2e-ТЕСТОВ")
    print(f"{'='*60}{RESET}\n")

    for name, result in results.items():
        if name == "all_passed":
            continue
        ok = result.get("ok", False)
        color = GREEN if ok else RED
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {color}{name}{RESET}")

        # Детали
        for k, v in result.items():
            if k == "ok":
                continue
            if isinstance(v, dict):
                for kk, vv in v.items():
                    print(f"       {kk}: {vv}")
            else:
                print(f"       {k}: {v}")
        print()

    passed = results.get("all_passed", False)
    if passed:
        print(f"{BOLD}{GREEN}  >>> ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ — МОЖНО ЗАПУСКАТЬ e2e <<<{RESET}\n")
    else:
        print(f"{BOLD}{RED}  >>> ЕСТЬ ПРОБЛЕМЫ — ИСПРАВЬТЕ ПЕРЕД ЗАПУСКОМ e2e <<<{RESET}")
        print(f"{YELLOW}  Подсказки:{RESET}")
        if not results.get("qdrant", {}).get("ok"):
            print(f"    - Qdrant: docker run -d -p 6333:6333 -p 6334:6334 qdrant/qdrant")
        if not results.get("env_vars", {}).get("ok"):
            print(f"    - Проверьте .env файл: {os.path.abspath(os.path.join(PRECONDITIONS_DIR, '..', '..', '.env'))}")
        print()


# --- CLI-точка входа ---
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
    )
    results = asyncio.run(run_all_checks())
    _print_report(results)
    sys.exit(0 if results.get("all_passed") else 1)
