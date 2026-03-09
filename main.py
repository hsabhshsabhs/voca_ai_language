import os
import json
import re
import asyncio
import logging
import hmac
import hashlib
from datetime import datetime
from typing import List, Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, BigInteger, Boolean, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from jose import jwt
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY", "lingvo_saas_ultra_final_2026")
ALGORITHM = "HS256"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- DATABASE ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./web_app/backend/voca_users.db")
# Render fix: SQLAlchemy requires postgresql:// instead of postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    credits = Column(Float, default=10.0) # Стартовые кредиты
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# Dependency
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- TELEGRAM UTILS ---
def verify_telegram_data(init_data: str) -> bool:
    if not BOT_TOKEN: return False
    try:
        vals = dict(parse_qsl(init_data))
        hash_val = vals.pop('hash')
        data_check_string = '\n'.join([f"{k}={v}" for k, v in sorted(vals.items())])
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return h == hash_val
    except Exception:
        return False

# --- JWT UTILS ---
def create_access_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        tg_id = payload.get("sub")
        user = db.query(User).filter(User.telegram_id == int(tg_id)).first()
        if not user: raise HTTPException(status_code=401)
        return user
    except:
        raise HTTPException(status_code=401)

# --- AI CALLS ---
async def deepseek_call(messages: List[dict]):
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": messages}, timeout=60) as resp:
                if resp.status != 200:
                    return f"Error API ({resp.status})"
                data = await resp.json()
                return data['choices'][0]['message']['content'].strip()
        except Exception as e:
            return f"Error: {str(e)[:50]}"

# --- APP ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/", response_class=HTMLResponse)
async def index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f: return f.read()
    return "<h1>lingvo.ai Mini App</h1>"

@app.post("/auth/telegram")
async def auth_telegram(req: dict, db: Session = Depends(get_db)):
    init_data = req.get("initData")
    if not verify_telegram_data(init_data):
        raise HTTPException(status_code=403, detail="Invalid Telegram data")
    
    # Extract user info
    data = dict(parse_qsl(init_data))
    user_data = json.loads(data.get("user", "{}"))
    tg_id = user_data.get("id")
    
    user = db.query(User).filter(User.telegram_id == tg_id).first()
    if not user:
        user = User(
            telegram_id=tg_id, 
            username=user_data.get("username"),
            first_name=user_data.get("first_name"),
            credits=20.0 # Приветственный бонус
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    token = create_access_token({"sub": str(tg_id)})
    return {"access_token": token, "credits": user.credits}

@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"username": user.first_name or user.username or "User", "credits": user.credits}

@app.post("/explain")
async def explain(req: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.credits < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    
    user.credits -= 1
    db.commit()
    
    prompt = f"Ты репетитор английского. Объясни структуру предложения на русском языке: '{req.get('text', '')}'"
    res = await deepseek_call([{"role": "user", "content": prompt}])
    return {"explanation": res or "Не удалось получить ответ", "credits": user.credits}

@app.post("/chat_stream")
async def chat_stream(req: dict, token: str, db: Session = Depends(get_db)):
    # Stream auth via token in query param
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        tg_id = payload.get("sub")
        user = db.query(User).filter(User.telegram_id == int(tg_id)).first()
        if not user or user.credits < 2:
             return StreamingResponse(iter(["||ERROR||Insufficient credits"]), media_type="text/plain")
    except:
        return StreamingResponse(iter(["||ERROR||Unauthorized"]), media_type="text/plain")

    user.credits -= 2
    db.commit()

    async def gen():
        full_en = ""
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        history = [{"role": "system", "content": f"ACT AS: {req['character']}. SCENARIO: {req['situation']}. Short replies."}]
        clean_hist = [m for m in req.get('history', []) if m.get("content")]
        
        if not clean_hist: history.append({"role": "user", "content": "Start conversation in English."})
        else: history.extend([{"role": m["role"], "content": m["content"]} for m in clean_hist])
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": history, "stream": True}) as resp:
                    async for line in resp.content:
                        lt = line.decode('utf-8').strip()
                        if lt.startswith("data: ") and lt != "data: [DONE]":
                            try:
                                chunk = json.loads(lt[6:])['choices'][0]['delta'].get('content', '')
                                full_en += chunk
                                yield chunk
                            except: continue
            except: yield "||ERROR||Connection lost"
        
        # Parallel meta tasks
        t_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Translate to Russian: {full_en}"}]))
        s_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Give 2 short English reply options for: {full_en}. JSON array: [{{'en':'...', 'ru':'...'}}]."}]))
        
        user_msg = clean_hist[-1]['content'] if clean_hist and clean_hist[-1]['role'] == 'user' else ""
        c_task = asyncio.create_task(deepseek_call([{"role":"user", "content":f"Check this English: '{user_msg}'. Return JSON {{'corrected':'...', 'explanation':'...'}} in Russian or NONE."}])) if user_msg else None

        trans, sug_raw, corr_raw = await asyncio.gather(t_task, s_task, c_task if c_task else asyncio.sleep(0, "NONE"))
        
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

# --- TELEGRAM STARS PAYMENTS ---
@app.post("/create-invoice")
async def create_invoice(req: dict, user: User = Depends(get_current_user)):
    amount = req.get("amount", 100) # Amount in Stars
    credits_to_add = amount * 2 # Course: 1 Star = 2 Credits
    
    invoice_payload = f"stars_pay_{user.telegram_id}_{int(datetime.now().timestamp())}"
    
    invoice_data = {
        "title": f"Пополнение: {credits_to_add} кредитов",
        "description": f"Покупка внутренней валюты для lingvo.ai (1 Star = 2 Credits)",
        "payload": invoice_payload,
        "currency": "XTR",
        "prices": [{"label": "Credits", "amount": amount}]
    }
    
    # Create invoice link via Telegram Bot API
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=invoice_data) as resp:
            data = await resp.json()
            if data.get("ok"):
                return {"invoice_link": data["result"]}
            raise HTTPException(status_code=500, detail="Failed to create invoice")

@app.post("/webhook/telegram")
async def telegram_webhook(update: dict, db: Session = Depends(get_db)):
    # Handle PreCheckoutQuery (Must answer OK within 10s)
    if "pre_checkout_query" in update:
        pq = update["pre_checkout_query"]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerPreCheckoutQuery"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={"pre_checkout_query_id": pq["id"], "ok": True})
        return {"ok": True}

    # Handle SuccessfulPayment
    message = update.get("message", {})
    if "successful_payment" in message:
        sp = message["successful_payment"]
        payload = sp["invoice_payload"]
        if payload.startswith("stars_pay_"):
            tg_id = int(payload.split("_")[2])
            amount = sp["total_amount"]
            user = db.query(User).filter(User.telegram_id == tg_id).first()
            if user:
                user.credits += amount * 2
                db.commit()
                logger.info(f"User {tg_id} paid {amount} Stars. Added {amount*2} credits.")
    
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

