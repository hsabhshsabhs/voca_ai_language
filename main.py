from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import aiohttp
import asyncio
import os
import json
import re
from typing import List

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Берем ключ из переменных окружения (настроим в Render)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"

class ChatRequest(BaseModel):
    character: str
    situation: str
    history: List[dict]
    mode: str

class ExplainRequest(BaseModel):
    text: str

async def deepseek_call(messages: List[dict], timeout=45):
    if not DEEPSEEK_API_KEY:
        return "Ошибка: API ключ не настроен в переменной DEEPSEEK_API_KEY"
    
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": messages, "stream": False}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=timeout) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data['choices'][0]['message']['content'].strip()
    except: return None

async def deepseek_stream(messages: List[dict]):
    if not DEEPSEEK_API_KEY:
        yield "Ошибка: API ключ не найден."
        return
        
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": messages, "stream": True}
    async with aiohttp.ClientSession() as session:
        async with session.post(DEEPSEEK_URL, headers=headers, json=payload) as resp:
            async for line in resp.content:
                line_text = line.decode('utf-8').strip()
                if line_text.startswith("data: "):
                    data_str = line_text[6:]
                    if data_str == "[DONE]": break
                    try:
                        data = json.loads(data_str)
                        chunk = data['choices'][0]['delta'].get('content', '')
                        if chunk: yield chunk
                    except: continue

@app.get("/", response_class=HTMLResponse)
async def get_index():
    # Пытаемся найти index.html в зависимости от структуры
    path = os.path.join(os.path.dirname(__file__), "../frontend/index.html")
    if not os.path.exists(path):
        path = "index.html" # Если деплоим в одну папку
    
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/explain")
async def explain_grammar(req: ExplainRequest):
    prompt = f"Ты репетитор. Объясни структуру предложения и правила построения фразы: '{req.text}'. Используй Markdown."
    res = await deepseek_call([{"role": "user", "content": prompt}], timeout=60)
    return {"explanation": res or "Не удалось получить разбор."}

@app.post("/chat_stream")
async def chat_stream(req: ChatRequest):
    current_history = req.history
    user_msg = current_history[-1]['content'] if current_history else ""
    if not current_history:
        current_history = [{"role": "user", "content": "Please start the conversation."}]

    system_prompt = f"You are {req.character}. Context: {req.situation}. Speak ONLY English. Stay in character."
    messages = [{"role": "system", "content": system_prompt}] + current_history

    async def event_generator():
        full_en = ""
        async for chunk in deepseek_stream(messages):
            full_en += chunk
            yield chunk
        
        if full_en:
            tasks = [
                asyncio.create_task(deepseek_call([{"role": "user", "content": f"Translate to Russian: {full_en}"}])),
                asyncio.create_task(deepseek_call([{"role": "user", "content": f"Context: {full_en}. Give 2 short natural replies. JSON array."}]))
            ]
            results = await asyncio.gather(*tasks)
            translation, sug_raw = results[0], results[1]

            suggestions = []
            try:
                match = re.search(r'\[.*\]', sug_raw, re.DOTALL)
                if match: suggestions = json.loads(match.group(0))
            except: pass

            meta = {"translation": translation, "suggestions": suggestions[:2]}
            yield "||META||" + json.dumps(meta)

    return StreamingResponse(event_generator(), media_type="text/plain")

if __name__ == "__main__":
    import uvicorn
    # Для деплоя используем PORT из переменных окружения
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
