from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
import aiohttp
import asyncio
import os
import json
import re
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import List, Optional

# --- CONFIG ---
SECRET_KEY = "lingvo_saas_final_2026"
ALGORITHM = "HS256"
ADMIN_PASSWORD = "admin12345"

# MAIL (hsabhshsabhs@gmail.com)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "hsabhshsabhs@gmail.com"
SMTP_PASS = "trfj uthv yudg vzca"

DEEPSEEK_API_KEY = "sk-cb1ae1fbf6cd4909affe67cb0fe4e955"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"

# --- DATABASE ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./voca_users.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    credits = Column(Float, default=50.0)
    reg_ip = Column(String)
    reset_code = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

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

class ChatRequest(BaseModel):
    character: str
    situation: str
    history: List[dict]
    mode: Optional[str] = "with_suggestions"

# --- WEB UI ROUTE ---
@app.get("/", response_class=HTMLResponse)
async def index():
    # Сервер будет искать index.html в той же папке
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "<h1>lingvo.ai</h1><p>index.html not found</p>"

# --- API ENDPOINTS ---
@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/register")
def register(user: UserCreate, request: Request, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first(): raise HTTPException(status_code=400, detail="Логин занят")
    if db.query(User).filter(User.email == user.email).first(): raise HTTPException(status_code=400, detail="Почта занята")
    new_user = User(username=user.username, email=user.email, hashed_password=pwd_context.hash(user.password), credits=50, reg_ip=request.client.host)
    db.add(new_user)
    db.commit()
    return {"status": "ok"}

@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.hashed_password): raise HTTPException(status_code=400, detail="Ошибка входа")
    token = jwt.encode({"sub": user.username}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "credits": user.credits}

@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"username": user.username, "credits": user.credits}

@app.post("/chat_stream")
async def chat_stream(req: ChatRequest, token: str):
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
        # Система промптов
        sys_msg = {"role": "system", "content": f"ACT AS: {req.character}. SCENARIO: {req.situation}. natural English only."}
        history = [sys_msg]
        history.extend([{"role": m["role"], "content": m["content"]} for m in req.history if m.get("content")])
        if len(history) == 1: history.append({"role": "user", "content": "Start the scene."})
        
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
        
        t_res = await deepseek_call([{"role":"user", "content": "Translate to Russian (text only): " + full_en}])
        sug = []
        if req.mode == "with_suggestions":
            s_prompt = 'Context: ' + full_en + '. Give 2 short reply options the user could say. Return JSON array of objects with "en" (English) and "ru" (Russian translation) keys. Example: [{"en":"Sure","ru":"Конечно"}]. Only JSON, no explanation.'
            s_res = await deepseek_call([{"role":"user", "content": s_prompt}])
            try: match = re.search(r'\[.*\]', s_res, re.DOTALL); sug = json.loads(match.group(0))[:2]
            except: pass
        
        yield "||META||" + json.dumps({"translation": t_res, "suggestions": sug})

    return StreamingResponse(gen(), media_type="text/plain")

class AnalyzeRequest(BaseModel):
    text: str

@app.post("/analyze")
async def analyze_text(req: AnalyzeRequest, token: str):
    db = SessionLocal()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = db.query(User).filter(User.username == payload.get("sub")).first()
    except:
        user = None
    db.close()
    if not user:
        raise HTTPException(status_code=401)
    
    prompt = '''Ты - преподаватель английского языка. Сделай подробный разбор этой английской фразы для изучающего язык. 
Ответ должен быть в HTML формате (без DOCTYPE, html, head, body тегов - только содержимое).

Структура разбора:
1. <h3>Общая структура</h3> - разбей фразу на части и объясни их функции
2. <h3>Детальный разбор</h3> - для каждой части/предложения:
   - <h4><code>фраза на английском</code></h4>
   - Тип предложения
   - Грамматическая структура (подлежащее, сказуемое, дополнения)
   - Ключевые слова с объяснениями
   - Грамматические правила
3. <h3>Полезные выражения</h3> - похожие фразы для практики

Используй:
- <strong>текст</strong> для выделения важного
- <code>английские слова</code> для примеров
- <ul><li>списки</li></ul> для перечислений
- <table> для сравнений если нужно

Фраза для разбора: "''' + req.text + '''"

Отвечай ТОЛЬКО HTML кодом, без markdown.'''
    
    analysis = await deepseek_call([{"role": "user", "content": prompt}])
    return {"analysis": analysis}

@app.post("/check_grammar")
async def check_grammar(req: AnalyzeRequest, token: str):
    db = SessionLocal()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = db.query(User).filter(User.username == payload.get("sub")).first()
    except:
        user = None
    db.close()
    if not user:
        raise HTTPException(status_code=401)
    
    prompt = 'Check this English text for grammar errors. If there are errors, return JSON: {"has_errors": true, "original": "...", "corrected": "...", "explanation": "краткое объяснение на русском"}. If no errors: {"has_errors": false}. Text: "' + req.text + '"'
    result = await deepseek_call([{"role": "user", "content": prompt}])
    try:
        match = re.search(r'\{.*\}', result, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except:
        pass
    return {"has_errors": False}

async def deepseek_call(messages: List[dict]):
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": messages}, timeout=45) as resp:
                data = await resp.json()
                return data['choices'][0]['message']['content'].strip()
    except: return ""

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
