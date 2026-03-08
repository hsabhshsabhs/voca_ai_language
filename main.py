import os
import json
import re
import asyncio
import logging
import traceback
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, BigInteger, Boolean, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from passlib.context import CryptContext
from jose import jwt
import aiohttp
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

# --- CONFIG ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get("SECRET_KEY", "lingvo_ultra_secret_2026")
ALGORITHM = "HS256"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TARGET_GROUP_ID = -5146140980

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

# --- DATABASE CONFIG ---
# Улучшенная логика подключения к PostgreSQL на Render
raw_db_url = os.environ.get("DATABASE_URL", "sqlite:///./voca_users.db")
if raw_db_url.startswith("postgres://"):
    DATABASE_URL = raw_db_url.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = raw_db_url

# Подключение к БД
try:
    if "sqlite" in DATABASE_URL:
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        # Для Postgres используем pool_pre_ping для стабильности
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
except Exception as e:
    logger.error(f"DATABASE CONNECTION ERROR: {e}")
    # Фолбек на локальную базу, если Postgres не настроен
    engine = create_engine("sqlite:///./voca_users.db", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=True)
    credits = Column(Float, default=50.0)
    reg_ip = Column(String, nullable=True)
    telegram_id = Column(BigInteger, unique=True, nullable=True, index=True)
    first_name = Column(String, nullable=True)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# --- SECURITY ---
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

# --- UTILS ---
async def deepseek_call(messages: List[dict]):
    if not DEEPSEEK_API_KEY: return ""
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": messages}, timeout=45) as resp:
                if resp.status != 200: return ""
                data = await resp.json()
                return data['choices'][0]['message']['content'].strip()
    except: return ""

# --- BOT LOGIC ---
async def run_bot_task():
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN is not set. Bot will not start.")
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher(storage=MemoryStorage())
        router = Router()

        @router.message(CommandStart())
        async def cmd_start(message: types.Message):
            await message.answer("Привет! Я бот поддержки lingvo.ai.\n\nОтправьте сюда чек об оплате или задайте вопрос.")

        @router.message()
        async def handle_bot_msg(message: types.Message):
            if message.chat.id == TARGET_GROUP_ID: return
            user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID:{message.from_user.id}"
            if message.photo:
                await bot.send_message(TARGET_GROUP_ID, f"📩 **НОВЫЙ ЧЕК** от {user_info}:")
                await message.forward(TARGET_GROUP_ID)
                await message.answer("✅ Чек получен! Мы начислим кредиты скоро.")
            elif message.text:
                await bot.send_message(TARGET_GROUP_ID, f"❓ **ВОПРОС** от {user_info}:\n\n{message.text}")
                await message.answer("📩 Вопрос передан администраторам.")

        dp.include_router(router)
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_task = asyncio.create_task(run_bot_task())
    yield
    bot_task.cancel()

# --- FASTAPI APP ---
app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        if os.path.exists("index.html"):
            with open("index.html", "r", encoding="utf-8") as f: return f.read()
        return "<h1>lingvo.ai Backend</h1><p>index.html not found</p>"
    except Exception as e: return f"<h1>Error</h1><p>{e}</p>"

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

@app.post("/explain")
async def explain(req: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.credits < 2: raise HTTPException(status_code=402)
    user.credits -= 2
    db.commit()
    prompt = f"Ты репетитор. Объясни структуру предложения: '{req.get('text', '')}'. Пиши на русском."
    res = await deepseek_call([{"role": "user", "content": prompt}])
    return {"explanation": res or "Ошибка API"}

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
        system_content = f"YOU ARE: {req['character']}. SCENARIO: {req['situation']}. Short English replies."
        history = [{"role": "system", "content": system_content}]
        clean_hist = [m for m in req['history'] if m.get("content")]
        if not clean_hist: history.append({"role": "user", "content": "Hello!"})
        else: history.extend([{"role": m["role"], "content": m["content"]} for m in clean_hist])
        
        try:
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
        except: yield "||ERROR||Connection error"
        
        t_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Translate to Russian: {full_en}"}]))
        s_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Context: {full_en}. Give 2 short natural options next. Return ONLY JSON array: [{{'en':'...', 'ru':'...'}}]."}]))
        trans = await t_task
        sug_raw = await s_task
        sug = []
        try: 
            match = re.search(r'\[.*\]', str(sug_raw), re.DOTALL)
            if match: sug = json.loads(match.group(0))[:2]
        except: pass
        yield "||META||" + json.dumps({"translation": trans, "suggestions": sug})

    return StreamingResponse(gen(), media_type="text/plain")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
