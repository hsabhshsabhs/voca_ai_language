from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
import aiohttp
import asyncio
import os
import json
import re
import random
import traceback
import sys
from datetime import datetime
from typing import List, Optional

# Добавляем корневую директорию в путь, чтобы импортировать общие модели
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from models import User, Base

# --- CONFIG (Render Environment Variables) ---
SECRET_KEY = os.environ.get("SECRET_KEY", "lingvo_saas_ultra_final_2026")
ALGORITHM = "HS256"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin12345")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-cb1ae1fbf6cd4909affe67cb0fe4e955")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"

# --- DATABASE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Используем общую базу в корне проекта
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), "voca_users.db")
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Создаем таблицы (если их нет)
Base.metadata.create_all(bind=engine)

FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        user = db.query(User).filter(User.username == username).first()
        if not user: raise HTTPException(status_code=401)
        return user
    except: raise HTTPException(status_code=401)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class ExplainRequest(BaseModel):
    text: str

@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        paths_to_try = [
            os.path.join(FRONTEND_DIR, "index.html"),
            "web_app/frontend/index.html",
            "frontend/index.html",
            "index.html"
        ]
        for p in paths_to_try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f: return f.read()
        return "<h1>lingvo.ai Backend</h1><p>index.html not found. Current DIR: " + os.getcwd() + "</p>"
    except Exception as e: 
        return f"<h1>Error</h1><p>{e}</p>"

@app.post("/register")
def register(user: UserCreate, request: Request, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first(): raise HTTPException(status_code=400, detail="Логин занят")
    new_user = User(username=user.username, email=user.email, hashed_password=pwd_context.hash(user.password), credits=50, reg_ip=request.client.host)
    db.add(new_user)
    db.commit()
    return {"status": "ok"}

@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.hashed_password): raise HTTPException(status_code=400, detail="Ошибка")
    token = jwt.encode({"sub": user.username}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "credits": user.credits}

@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"username": user.username, "credits": user.credits}

async def deepseek_call(messages: List[dict]):
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": messages}, timeout=45) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    print(f"DEBUG API ERROR: {resp.status} - {err_txt}")
                    return ""
                data = await resp.json()
                return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"DEBUG EXCEPTION in deepseek_call: {traceback.format_exc()}")
        return ""

@app.post("/explain")
async def explain(req: ExplainRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.credits < 2: raise HTTPException(status_code=402, detail="Баланс пуст")
    user.credits -= 2
    db.commit()
    prompt = f"Ты репетитор. Объясни структуру предложения: '{req.text}'. Пиши на русском, используй Markdown."
    res = await deepseek_call([{"role": "user", "content": prompt}])
    return {"explanation": res or "Не удалось получить объяснение."}

@app.post("/chat_stream")
async def chat_stream(req: dict, token: str):
    db = SessionLocal()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = db.query(User).filter(User.username == payload.get("sub")).first()
    except: user = None
    if not user or user.credits < 1:
        db.close()
        async def err(): yield "||ERROR||Баланс пуст!"
        return StreamingResponse(err(), media_type="text/plain")
    user.credits -= 1
    db.commit()
    db.close()

    async def gen():
        full_en = ""
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        system_content = (
            f"YOU ARE NOT AN AI. YOU ARE: {req['character']}. "
            f"CURRENT SCENARIO: {req['situation']}. "
            "IMPORTANT: Speak ONLY natural conversational English. Stay in character 100%. "
            "Keep your responses short (1-2 sentences). Do not break character."
        )
        history = [{"role": "system", "content": system_content}]
        clean_history = [m for m in req['history'] if m.get("content")]
        if not clean_history:
            history.append({"role": "user", "content": f"Start the scene. You are {req['character']} in the following situation: {req['situation']}. Say the very first phrase to me."})
        else:
            history.extend([{"role": m["role"], "content": m["content"]} for m in clean_history])
        
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": history, "stream": True}) as resp:
                async for line in resp.content:
                    lt = line.decode('utf-8').strip()
                    if lt.startswith("data: ") and lt != "data: [DONE]":
                        try:
                            chunk = json.loads(lt[6:])['choices'][0]['delta'].get('content', '')
                            full_en += chunk
                            yield chunk
                        except: continue
        
        t_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Translate to Russian: {full_en}"}]))
        s_task = None
        if req.get('mode') == "with_suggestions":
            s_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Based on the dialogue: '{full_en}', give me 2 short natural options for what I should say next. Return ONLY a JSON array: [{{'en':'...', 'ru':'...'}}, {{'en':'...', 'ru':'...'}}]."}]))
        
        user_msg = ""
        if clean_history:
            user_msgs = [m["content"] for m in clean_history if m["role"] == "user"]
            if user_msgs: user_msg = user_msgs[-1]
        c_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Check this English sentence for errors: '{user_msg}'. If there are errors, return JSON {{'corrected':'...', 'explanation':'...'}} in Russian. If no errors, return the word NONE."}])) if user_msg else None
        
        trans = await t_task
        sug_raw = await s_task if s_task else "[]"
        corr_raw = await c_task if c_task else "NONE"
        sug = []
        try: 
            match = re.search(r'\[.*\]', str(sug_raw), re.DOTALL)
            if match: sug = json.loads(match.group(0))[:2]
        except: pass
        corr_data = None
        if corr_raw and "NONE" not in str(corr_raw):
            try:
                match = re.search(r'\{.*\}', str(corr_raw), re.DOTALL)
                if match: corr_data = json.loads(match.group(0))
            except: pass
        yield "||META||" + json.dumps({"translation": trans, "suggestions": sug, "user_correction": corr_data})

    return StreamingResponse(gen(), media_type="text/plain")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
