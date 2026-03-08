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
from datetime import datetime
from typing import List, Optional

# --- CONFIG ---
SECRET_KEY = "lingvo_saas_ultra_final_2026"
ALGORITHM = "HS256"
ADMIN_PASSWORD = "admin12345"

# MAIL
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "hsabhshsabhs@gmail.com"
SMTP_PASS = "trfj uthv yudg vzca"

DEEPSEEK_API_KEY = "sk-cb1ae1fbf6cd4909affe67cb0fe4e955"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"

# --- DATABASE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'voca_users.db')}")
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {})
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

class ExplainRequest(BaseModel):
    text: str

@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        idx_path = os.path.join(BASE_DIR, "index.html")
        with open(idx_path, "r", encoding="utf-8") as f: return f.read()
    except Exception as e: 
        print(f"Error reading index.html: {e}")
        return "<h1>lingvo.ai Backend</h1>"

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
    if not user or not pwd_context.verify(form_data.password, user.hashed_password): raise HTTPException(status_code=400, detail="Ошибка")
    token = jwt.encode({"sub": user.username}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "credits": user.credits}

@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"username": user.username, "credits": user.credits}

@app.get("/admin/users")
def admin_users(admin_password: str, db: Session = Depends(get_db)):
    if admin_password != ADMIN_PASSWORD: raise HTTPException(status_code=403)
    return [{"username":u.username, "email":u.email, "credits":u.credits} for u in db.query(User).all()]

@app.post("/admin/add_credits")
def admin_add(req: dict, db: Session = Depends(get_db)):
    if req['admin_password'] != ADMIN_PASSWORD: raise HTTPException(status_code=403)
    user = db.query(User).filter(User.username == req['username']).first()
    if user:
        user.credits += req['amount']
        db.commit()
    return {"status": "ok"}

async def deepseek_call(messages: List[dict]):
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": messages}, timeout=45) as resp:
                data = await resp.json()
                return data['choices'][0]['message']['content'].strip()
    except: return ""

@app.post("/explain")
async def explain(req: ExplainRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.credits < 2: raise HTTPException(status_code=402, detail="Баланс пуст")
    user.credits -= 2
    db.commit()
    prompt = (
        f"Ты репетитор. Объясни структуру предложения и правила построения фразы: '{req.text}'. "
        "Пиши на русском, используй Markdown."
    )
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
        history = [{"role": "system", "content": f"ACT AS: {req['character']}. SCENARIO: {req['situation']}. Natural short English."}]
        history.extend([{"role": m["role"], "content": m["content"]} for m in req['history'] if m.get("content")])
        
        user_msg = ""
        if req['history']:
            user_msgs = [m["content"] for m in req['history'] if m["role"] == "user"]
            if user_msgs: user_msg = user_msgs[-1]

        if len(history) == 1: history.append({"role": "user", "content": "Start conversation."})
        
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
        
        # Получаем данные
        t_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Translate to Russian: {full_en}"}]))
        s_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Context: {full_en}. Return JSON array with 2 short natural English replies + Russian translations: [{{'en':'...', 'ru':'...'}}]."}]))
        c_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Check this English sentence for errors: '{user_msg}'. If there are errors, return JSON {{'corrected':'...', 'explanation':'...'}} in Russian. If no errors, return NONE."}])) if user_msg else None
        
        trans, sug_raw = await asyncio.gather(t_task, s_task)
        corr_raw = await c_task if c_task else "NONE"

        sug = []
        try: 
            match = re.search(r'\[.*\]', sug_raw, re.DOTALL)
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
