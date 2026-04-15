# Vision

AI-платформа на базе Open WebUI с интеграцией MWS GPT.

## Требования

- **Node.js** >= 18
- **Python** >= 3.11
- **npm**

macOS:
```bash
brew install node python@3.11
```

## Запуск (одна команда)

```bash
git clone <repo-url> && cd open-webui
chmod +x run.sh
./run.sh
```

Скрипт сам установит все зависимости (venv, pip, npm, pyodide) и запустит оба сервера.

| Сервис   | Адрес                     |
|----------|---------------------------|
| Frontend | http://127.0.0.1:4000     |
| Backend  | http://127.0.0.1:2000     |

В dev-режиме открывайте **только** интерфейс на **:4000**. Запросы `/api`, `/oauth`, `/static` и т.д. идут на тот же origin; Vite проксирует их на backend **:2000** (`PUBLIC_WEBUI_BACKEND_URL` в `.env` — это адрес прокси, не прямой URL в браузере). Так фронт и бэк ведут себя как одно приложение.

Остановка: **Ctrl+C**

## Варианты запуска

```bash
./run.sh                # установка + backend + frontend
./run.sh --backend      # только backend  (порт 2000)
./run.sh --frontend     # только frontend (порт 4000)
./run.sh --install      # только установка (без запуска)
```

## Настройка

API-ключи и параметры — в файле `.env` (создаётся автоматически из `.env.example` при первом запуске).

Основные переменные:

```
MWS_GPT_API_KEY=         # ключ MWS GPT
IMAGES_OPENAI_API_KEY=   # ключ для генерации изображений
TELEGRAM_BOT_TOKEN=      # токен Telegram-бота
```

## npm-команды (альтернатива)

```bash
npm run dev:backend      # backend
npm run dev:web          # frontend
npm run dev:all          # оба сервера
npm run bootstrap        # установка зависимостей
```
