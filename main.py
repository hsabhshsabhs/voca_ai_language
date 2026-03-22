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


# --- TRANSLATIONS ---
TRANSLATIONS = {
    "Russian": {
        "welcome_title": "lingvo ai — твой интерактивный тренажер языков",
        "welcome_desc": "Практикуй языки в диалогах с AI. Получай мгновенные исправления и учи грамматику.",
        "welcome_features": "✅ Любые роли, ситуации и языки.\n✅ Автоматическая проверка ошибок.\n✅ Разбор с транскрипцией.\n✅ Умные варианты ответов.",
        "welcome_action": "Нажми \"Open\" и начни обучение!",
        "welcome_your_lang": "Твой язык интерфейса",
        "affiliate_title": "💼 Партнерская программа",
        "affiliate_desc": "Стань амбассадором и получай:\n\n🎁 +30 токенов за каждого друга\n💰 20% от покупок друга!",
        "affiliate_link": "🔗 Твоя ссылка:\n",
        "affiliate_invite": "Пригласить друзей",
        "lang_select_title": "🌍 Выбери свой язык",
        "lang_select_desc": "Я буду использовать этот язык для интерфейса.",
        "lang_select_action": "Нажми на флаг 👇",
        "referral_bonus": "🎉 Ура! По твоей ссылке новый пользователь! +30 токенов!",
        "channel_btn": "📢 Наш канал",
        "affiliate_btn": "💼 Партнерская программа",
        "promo_subscribe": "Подпишись на канал! При балансе <50 токенов начисляется 15 ежедневно!",
    },
    "English": {
        "welcome_title": "lingvo ai — your interactive language trainer",
        "welcome_desc": "Practice languages in AI dialogues. Get instant corrections and learn grammar while chatting.",
        "welcome_features": "✅ Any roles, situations and languages.\n✅ Automatic error checking.\n✅ Phrase analysis with transcription.\n✅ Smart reply suggestions.",
        "welcome_action": "Click \"Open\" and start learning!",
        "welcome_your_lang": "Your interface language",
        "affiliate_title": "💼 Affiliate Program",
        "affiliate_desc": "Become an ambassador and earn:\n\n🎁 +30 tokens for every friend\n💰 20% from friend\'s purchases!",
        "affiliate_link": "🔗 Your link:\n",
        "affiliate_invite": "Invite Friends",
        "lang_select_title": "🌍 Choose your language",
        "lang_select_desc": "I\'ll use this language for the interface.",
        "lang_select_action": "Tap a flag 👇",
        "referral_bonus": "🎉 Hooray! Someone signed up via your link! +30 tokens!",
        "channel_btn": "📢 Our Channel",
        "affiliate_btn": "💼 Affiliate Program",
        "promo_subscribe": "Subscribe to our channel! Get 15 tokens daily when balance <50!",
    },
    "Spanish": {
        "welcome_title": "lingvo ai — tu entrenador de idiomas interactivo",
        "welcome_desc": "Practica idiomas en diálogos con IA. Obtén correcciones instantáneas y aprende gramática.",
        "welcome_features": "✅ Cualquier rol, situación e idioma.\n✅ Corrección automática de errores.\n✅ Análisis con transcripción.\n✅ Sugerencias inteligentes.",
        "welcome_action": "¡Haz clic en \"Open\" y empieza a aprender!",
        "welcome_your_lang": "Tu idioma de interfaz",
        "affiliate_title": "💼 Programa de Afiliados",
        "affiliate_desc": "Conviértete en embajador y gana:\n\n🎁 +30 tokens por cada amigo\n💰 20% de las compras del amigo!",
        "affiliate_link": "🔗 Tu enlace:\n",
        "affiliate_invite": "Invitar Amigos",
        "lang_select_title": "🌍 Elige tu idioma",
        "lang_select_desc": "Usaré este idioma para la interfaz.",
        "lang_select_action": "Toca una bandera 👇",
        "referral_bonus": "🎉 ¡Hurra! ¡Alguien se registró con tu enlace! +30 tokens!",
        "channel_btn": "📢 Nuestro Canal",
        "affiliate_btn": "💼 Programa de Afiliados",
        "promo_subscribe": "¡Suscríbete al canal! Obtén 15 tokens diarios cuando saldo <50!",
    },
    "Portuguese": {
        "welcome_title": "lingvo ai — seu trainer de idiomas interativo",
        "welcome_desc": "Pratique idiomas em diálogos com IA. Obtenha correções instantâneas e aprenda gramática.",
        "welcome_features": "✅ Qualquer papel, situação e idioma.\n✅ Verificação automática de erros.\n✅ Análise com transcrição.\n✅ Sugestões inteligentes.",
        "welcome_action": "Clique em \"Open\" e comece a aprender!",
        "welcome_your_lang": "Seu idioma de interface",
        "affiliate_title": "💼 Programa de Afiliados",
        "affiliate_desc": "Torne-se um embaixador e ganhe:\n\n🎁 +30 tokens por amigo\n💰 20% das compras do amigo!",
        "affiliate_link": "🔗 Seu link:\n",
        "affiliate_invite": "Convidar Amigos",
        "lang_select_title": "🌍 Escolha seu idioma",
        "lang_select_desc": "Usarei este idioma para a interface.",
        "lang_select_action": "Toque numa bandeira 👇",
        "referral_bonus": "🎉 Eba! Alguém se cadastrou pelo seu link! +30 tokens!",
        "channel_btn": "📢 Nosso Canal",
        "affiliate_btn": "💼 Programa de Afiliados",
        "promo_subscribe": "Inscreva-se no canal! Receba 15 tokens diários quando saldo <50!",
    },
    "German": {
        "welcome_title": "lingvo ai — dein interaktiver Sprachtrainer",
        "welcome_desc": "Übe Sprachen in KI-Dialogen. Erhalte sofortige Korrekturen und lerne Grammatik.",
        "welcome_features": "✅ Beliebige Rollen, Situationen und Sprachen.\n✅ Automatische Fehlerprüfung.\n✅ Analyse mit Transkription.\n✅ Intelligente Vorschläge.",
        "welcome_action": "Klicke auf \"Open\" und lerne!",
        "welcome_your_lang": "Deine Interface-Sprache",
        "affiliate_title": "💼 Partnerprogramm",
        "affiliate_desc": "Werden Sie Botschafter und verdienen Sie:\n\n🎁 +30 Tokens pro Freund\n💰 20% von Freundes Einkäufen!",
        "affiliate_link": "🔗 Dein Link:\n",
        "affiliate_invite": "Freunde einladen",
        "lang_select_title": "🌍 Wähle deine Sprache",
        "lang_select_desc": "Ich verwende diese Sprache für die Oberfläche.",
        "lang_select_action": "Tippe auf eine Flagge 👇",
        "referral_bonus": "🎉 Juhu! Jemand hat sich über deinen Link angemeldet! +30 Tokens!",
        "channel_btn": "📢 Unser Kanal",
        "affiliate_btn": "💼 Partnerprogramm",
        "promo_subscribe": "Abonniere den Kanal! Erhalte 15 Tokens täglich wenn Kontostand <50!",
    },
    "French": {
        "welcome_title": "lingvo ai — ton coach de langues interactif",
        "welcome_desc": "Pratique les langues dans des dialogues IA. Obtiens des corrections instantanées et apprends la grammaire.",
        "welcome_features": "✅ Rôles, situations et langues variés.\n✅ Vérification automatique des erreurs.\n✅ Analyse avec transcription.\n✅ Suggestions intelligentes.",
        "welcome_action": "Clique sur \"Open\" et commence à apprendre!",
        "welcome_your_lang": "Ta langue d\'interface",
        "affiliate_title": "💼 Programme d\'Affiliation",
        "affiliate_desc": "Deviens ambassadeur et gagne:\n\n🎁 +30 jetons par ami\n💰 20% des achats de ton ami!",
        "affiliate_link": "🔗 Ton lien:\n",
        "affiliate_invite": "Inviter des Amis",
        "lang_select_title": "🌍 Choisis ta langue",
        "lang_select_desc": "J\'utiliserai cette langue pour l\'interface.",
        "lang_select_action": "Touche un drapeau 👇",
        "referral_bonus": "🎉 Hourra! Quelqu\'un s\'est inscrit via ton lien! +30 jetons!",
        "channel_btn": "📢 Notre Chaîne",
        "affiliate_btn": "💼 Programme d\'Affiliation",
        "promo_subscribe": "Abonne-toi à la chaîne! Reçois 15 jetons par jour si solde <50!",
    },
    "Italian": {
        "welcome_title": "lingvo ai — il tuo trainer di lingue interattivo",
        "welcome_desc": "Pratica le lingue in dialoghi con IA. Ottieni correzioni istantanee e impara la grammatica.",
        "welcome_features": "✅ Qualsiasi ruolo, situazione e lingua.\n✅ Verifica automatica degli errori.\n✅ Analisi con trascrizione.\n✅ Suggerimenti intelligenti.",
        "welcome_action": "Clicca su \"Open\" e inizia a imparare!",
        "welcome_your_lang": "La tua lingua dell\'interfaccia",
        "affiliate_title": "💼 Programma di Affiliazione",
        "affiliate_desc": "Diventa ambasciatore e guadagna:\n\n🎁 +30 token per ogni amico\n💰 20% dagli acquisti dell\'amico!",
        "affiliate_link": "🔗 Il tuo link:\n",
        "affiliate_invite": "Invita Amici",
        "lang_select_title": "🌍 Scegli la tua lingua",
        "lang_select_desc": "Userò questa lingua per l\'interfaccia.",
        "lang_select_action": "Tocca una bandiera 👇",
        "referral_bonus": "🎉 Evviva! Qualcuno si è registrato tramite il tuo link! +30 token!",
        "channel_btn": "📢 Il Nostro Canale",
        "affiliate_btn": "💼 Programma di Affiliazione",
        "promo_subscribe": "Iscriviti al canale! Ricevi 15 token giornalieri quando saldo <50!",
    },
    "Japanese": {
        "welcome_title": "lingvo ai — インタラクティブ言語トレーナー",
        "welcome_desc": "AIとの対話で言語を練習。即座に修正を得て、文法を学びましょう。",
        "welcome_features": "✅ あらゆる役割、状況、言語。\n✅ 自動エラー修正。\n✅ 文字起こし付き分析。\n✅ スマートな提案。",
        "welcome_action": "\"Open\"をクリックして学習を始めよう！",
        "welcome_your_lang": "あなたのインターフェース言語",
        "affiliate_title": "💼 アフィリエーションプログラム",
        "affiliate_desc": "アンバサダーになって収益をGET:\n\n🎁 友達1人につき+30トークン\n💰 友達の買い物の20%！",
        "affiliate_link": "🔗 あなたのリンク:\n",
        "affiliate_invite": "友達を招待",
        "lang_select_title": "🌍 言語を選択",
        "lang_select_desc": "インターフェースにこの言語を使います。",
        "lang_select_action": "旗をタップ 👇",
        "referral_bonus": "🎉 やった！誰かがあなたのリンクから登録しました！+30トークン！",
        "channel_btn": "📢 チャンネル",
        "affiliate_btn": "💼 アフィリエーション",
        "promo_subscribe": "チャンネルに登録！残高<50トークンの場合、15トークン獲得！",
    },
    "Chinese": {
        "welcome_title": "lingvo ai — 你的互动语言教练",
        "welcome_desc": "在AI对话中练习语言。获得即时纠正并学习语法。",
        "welcome_features": "✅ 任何角色、情境和语言。\n✅ 自动错误检查。\n✅ 带转录的分析。\n✅ 智能建议。",
        "welcome_action": "点击\"Open\"开始学习！",
        "welcome_your_lang": "你的界面语言",
        "affiliate_title": "💼 附属计划",
        "affiliate_desc": "成为大使并赚取:\n\n🎁 每个朋友+30代币\n💰 朋友购物的20%！",
        "affiliate_link": "🔗 你的链接:\n",
        "affiliate_invite": "邀请朋友",
        "lang_select_title": "🌍 选择你的语言",
        "lang_select_desc": "我将使用这种语言作为界面。",
        "lang_select_action": "点击旗帜 👇",
        "referral_bonus": "🎉 好棒！有人通过你的链接注册了！+30代币！",
        "channel_btn": "📢 我们的频道",
        "affiliate_btn": "💼 附属计划",
        "promo_subscribe": "订阅频道！余额<50时每日获得15代币！",
    },
    "Korean": {
        "welcome_title": "lingvo ai — 당신의 대화형 언어 트레이너",
        "welcome_desc": "AI 대화로 언어 연습. 즉각적인 교정 받고 문법 배우기.",
        "welcome_features": "✅ 다양한 역할, 상황, 언어.\n✅ 자동 오류 검사.\n✅ 음역 포함 분석.\n✅ 똑똑한 답변 제안.",
        "welcome_action": "\"Open\"을 클릭하고 학습을 시작하세요!",
        "welcome_your_lang": "당신의 인터페이스 언어",
        "affiliate_title": "💼 제휴 프로그램",
        "affiliate_desc": "앰배서더가 되고 수익을 얻으세요:\n\n🎁 친구每人 +30토큰\n💰 친구 구매의 20%！",
        "affiliate_link": "🔗 당신의 링크:\n",
        "affiliate_invite": "친구 초대",
        "lang_select_title": "🌍 언어 선택",
        "lang_select_desc": "이 언어를 인터페이스로 사용합니다.",
        "lang_select_action": "깃발을 탭하세요 👇",
        "referral_bonus": "🎉好啊！누군가 당신의 링크로 가입했습니다！+30토큰！",
        "channel_btn": "📢 우리 채널",
        "affiliate_btn": "💼 제휴 프로그램",
        "promo_subscribe": "채널 구독! 잔액 <50시 매일 15토큰 획득!",
    },
}

def t(lang, key):
    return TRANSLATIONS.get(lang, TRANSLATIONS["English"]).get(key, TRANSLATIONS["English"].get(key, ""))


# --- DATABASE ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./web_app/backend/voca_users.db")
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
    user_lang = Column(String, nullable=True)  # User's native language
    credits = Column(Float, default=30.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_reward_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- TELEGRAM UTILS ---
async def check_subscription(user_id: int) -> bool:
    if not BOT_TOKEN: return True
    channel_id = "@lingvoaichanel"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params={"chat_id": channel_id, "user_id": user_id}) as resp:
                if resp.status != 200: return False
                data = await resp.json()
                if not data.get("ok"): return False
                status = data["result"].get("status")
                return status in ["member", "administrator", "creator"]
        except: return False

def verify_telegram_data(init_data: str) -> bool:
    if not BOT_TOKEN: return False
    try:
        vals = dict(parse_qsl(init_data))
        hash_val = vals.pop('hash')
        data_check_string = '\n'.join([f"{k}={v}" for k, v in sorted(vals.items())])
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return h == hash_val
    except: return False

def create_access_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "): raise HTTPException(status_code=401)
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        tg_id = payload.get("sub")
        user = db.query(User).filter(User.telegram_id == int(tg_id)).first()
        if not user: raise HTTPException(status_code=401)
        return user
    except: raise HTTPException(status_code=401)

# --- AI CALLS ---
async def deepseek_call(messages: List[dict], max_tokens: int = 1000):
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": messages, "max_tokens": max_tokens}, timeout=60) as resp:
                if resp.status != 200: return f"Error API ({resp.status})"
                data = await resp.json()
                return data['choices'][0]['message']['content'].strip()
        except Exception as e: return f"Error: {str(e)[:50]}"

# --- APP ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/", response_class=HTMLResponse)
async def index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f: return f.read()
    return "<h1>lingvo.ai</h1>"

@app.post("/auth/telegram")
async def auth_telegram(req: dict, db: Session = Depends(get_db)):
    init_data = req.get("initData")
    if not verify_telegram_data(init_data): raise HTTPException(status_code=403)
    data = dict(parse_qsl(init_data))
    user_data = json.loads(data.get("user", "{}"))
    tg_id = user_data.get("id")
    user = db.query(User).filter(User.telegram_id == tg_id).first()
    if not user:
        user = User(telegram_id=tg_id, username=user_data.get("username"), first_name=user_data.get("first_name"), credits=30.0)
        db.add(user); db.commit(); db.refresh(user)
    return {"access_token": create_access_token({"sub": str(tg_id)}), "credits": user.credits}

@app.get("/me")
async def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Daily reward logic
    now = datetime.utcnow()
    today = now.date()
    last_reward_date = user.last_reward_at.date() if user.last_reward_at else None
    
    reward_given = False
    if user.credits < 50 and last_reward_date != today:
        user.credits += 15.0
        user.last_reward_at = now
        db.commit()
        db.refresh(user)
        reward_given = True
        
    return {
        "username": user.first_name or user.username or "User", 
        "credits": user.credits,
        "reward_given": reward_given
    }

@app.post("/explain")
async def explain(req: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # if user.credits < 1: raise HTTPException(status_code=402)
    # user.credits -= 1; db.commit()
    lang = req.get('lang', 'English')
    text = req.get('text', '')
    mode = req.get('mode', 'academic') # 'academic' or 'informal'
    
    if mode == 'informal':
        system_prompt = f"Ты — крутой наставник по {lang}. Объясняй кратко, 'на пальцах', как другу. Минимум теории, максимум пользы."
    else:
        system_prompt = f"Ты — профи репетитор по {lang}. Давай четкий грамматический разбор и структуру без воды."

    prompt = (
        f"{system_prompt}\n\n"
        f"Разбери фразу: '{text}'.\n"
        f"План ответа:\n"
        f"1. Перевод на русский.\n"
        f"2. Слова + IPA транскрипция [ ] + краткое пояснение.\n"
        f"3. Суть грамматики (тезисно, самое важное).\n"
        "Пиши емко, избегай вступительных слов. Используй Markdown."
    )
    res = await deepseek_call([{"role": "user", "content": prompt}], max_tokens=1000)
    return {"explanation": res or "Не удалось получить ответ", "credits": user.credits}

@app.post("/chat_stream")
async def chat_stream(req: dict, token: str, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        tg_id = payload.get("sub")
        user = db.query(User).filter(User.telegram_id == int(tg_id)).first()
        if not user or user.credits < 1: return StreamingResponse(iter(["||ERROR||Credits"]), media_type="text/plain")
    except: return StreamingResponse(iter(["||ERROR||Auth"]), media_type="text/plain")

    user.credits -= 1; db.commit()
    target_lang = req.get('lang', 'English')

    async def gen():
        full_res = ""
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        system_content = (
            f"ACT AS: {req['character']}. SCENARIO: {req['situation']}. "
            f"ALWAYS respond in {target_lang} ONLY. BE VERY CONCISE. MAX 2-3 SHORT SENTENCES. "
            "Do not write long descriptions."
        )
        history = [{"role": "system", "content": system_content}]
        clean_hist = [m for m in req.get('history', []) if m.get("content")]
        if not clean_hist: 
            history.append({"role": "user", "content": f"Start conversation in {target_lang}."})
        else: 
            history.extend([{"role": m["role"], "content": m["content"]} for m in clean_hist])
        
        # Check promo requirement
        is_sub = await check_subscription(user.telegram_id)
        promo = None
        if not is_sub and len(clean_hist) == 6:
            promo = t(user.user_lang or "English", "promo_subscribe")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(DEEPSEEK_URL, headers=headers, json={"model": MODEL, "messages": history, "stream": True}) as resp:
                    async for line in resp.content:
                        lt = line.decode('utf-8').strip()
                        if lt.startswith("data: ") and lt != "data: [DONE]":
                            try:
                                chunk = json.loads(lt[6:])['choices'][0]['delta'].get('content', '')
                                full_res += chunk; yield chunk
                            except: continue
            except: yield "||ERROR||Lost"
        
        await asyncio.sleep(0.1)
        # Translation and Suggestions
        t_prompt = f"Translate this {target_lang} text to Russian strictly: {full_res}"
        t_task = asyncio.create_task(deepseek_call([
            {"role":"system", "content":"You are a professional translator. Return ONLY the translated Russian text."}, 
            {"role":"user", "content": t_prompt}
        ]))
        
        # IMPROVED SUGGESTIONS PROMPT
        s_system = (
            f"You are a language tutor assistant. Based on the conversation, provide 2 short reply options for the USER (the student) to say next in {target_lang}. "
            f"Return ONLY a JSON array: [{{\"target\":\"...\", \"ru\":\"...\"}}]. NO explanations, NO intro."
        )
        s_user_prompt = f"Scenario: {req['situation']}. AI character: {req['character']}. Last AI message: {full_res}. Provide 2 short user reply options."
        s_task = asyncio.create_task(deepseek_call([
            {"role":"system", "content": s_system}, 
            {"role":"user", "content": s_user_prompt}
        ]))
        
        user_msg = clean_hist[-1]['content'] if clean_hist and clean_hist[-1]['role'] == 'user' else ""
        c_task = asyncio.create_task(deepseek_call([
            {"role":"system", "content":f"Grammar check for {target_lang}. Return JSON {{\"corrected\":\"...\", \"explanation\":\"...\"}} in Russian or word NONE."}, 
            {"role":"user", "content": f"Text: {user_msg}"}
        ])) if user_msg else None

        trans, sug_raw, corr_raw = await asyncio.gather(t_task, s_task, c_task if c_task else asyncio.sleep(0, "NONE"))
        
        sug = []
        try:
            m = re.search(r'\[\s*\{.*\}\s*\]', str(sug_raw), re.DOTALL)
            if m: 
                raw_sug = json.loads(m.group(0))[:2]
                sug = [{"en": s.get('target', s.get('en', s.get('target_lang'))), "ru": s.get('ru')} for s in raw_sug]
        except: 
            # Fallback if JSON parsing fails but content might be okay
            logger.error(f"Failed to parse suggestions: {sug_raw}")
        
        corr_data = None
        if corr_raw and "NONE" not in str(corr_raw).upper():
            try:
                m = re.search(r'\{.*\}', str(corr_raw), re.DOTALL)
                if m: corr_data = json.loads(m.group(0))
            except: pass
            
        yield "||META||" + json.dumps({"translation": str(trans).strip(), "suggestions": sug, "user_correction": corr_data, "promo": promo}, ensure_ascii=False)

    return StreamingResponse(gen(), media_type="text/plain")

@app.post("/create-invoice")
async def create_invoice(req: dict, user: User = Depends(get_current_user)):
    amount = req.get("amount", 100)
    invoice_data = {"title": f"Refill: {amount*2} Credits", "description": "lingvo.ai currency", "payload": f"stars_{user.telegram_id}_{int(datetime.now().timestamp())}", "currency": "XTR", "prices": [{"label": "Credits", "amount": amount}]}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=invoice_data) as resp:
            data = await resp.json()
            if data.get("ok"): return {"invoice_link": data["result"]}
            raise HTTPException(status_code=500)

@app.get("/webhook/telegram")
async def telegram_webhook_test():
    return {"status": "Webhook endpoint is alive. Please use POST for Telegram updates."}

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
    except:
        return {"ok": False}
    
    if "pre_checkout_query" in update:
        pq = update["pre_checkout_query"]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerPreCheckoutQuery"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={"pre_checkout_query_id": pq["id"], "ok": True})
        return {"ok": True}

    if "callback_query" in update:
        cb = update["callback_query"]
        if cb.get("data") == "affiliate_info":
            user_id = cb["from"]["id"]
            db = SessionLocal()
            db_user = db.query(User).filter(User.telegram_id == user_id).first()
            u_lang = db_user.user_lang if db_user and db_user.user_lang else "English"
            db.close()
            
            async with aiohttp.ClientSession() as session:
                bot_resp = await session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
                bot_data = await bot_resp.json()
                bot_username = bot_data.get("result", {}).get("username", "lingvo_ai_bot")
                
                aff_text = (
                    f"<b>{t(u_lang, 'affiliate_title')}</b>\n\n"
                    f"{t(u_lang, 'affiliate_desc')}\n\n"
                    f"<b>{t(u_lang, 'affiliate_link')}</b><code>https://t.me/{bot_username}?start=ref_{user_id}</code>"
                )
                invite_url = f"https://t.me/share/url?url=https://t.me/{bot_username}?start=ref_{user_id}&text=Practice%20languages%20with%20AI%20in%20lingvo.ai!"
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                await session.post(url, json={
                    "chat_id": user_id,
                    "text": aff_text,
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [[{"text": t(u_lang, "affiliate_invite"), "url": invite_url}]]
                    }
                })
            return {"ok": True}
        
        # Handle user language selection
        if cb.get("data", "").startswith("user_lang_"):
            user_id = cb["from"]["id"]
            selected_lang = cb.get("data", "").replace("user_lang_", "")
            
            # Map lang code to full name
            lang_map = {
                "ru": "Russian", "en": "English", "es": "Spanish", "pt": "Portuguese",
                "de": "German", "fr": "French", "it": "Italian", "ja": "Japanese",
                "zh": "Chinese", "ko": "Korean", "nl": "Dutch", "pl": "Polish",
                "tr": "Turkish", "ar": "Arabic", "hi": "Hindi", "id": "Indonesian"
            }
            user_lang = lang_map.get(selected_lang, "English")
            
            db = SessionLocal()
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if user:
                user.user_lang = user_lang
                db.commit()
            db.close()
            
            # Send welcome message with animation
            welcome_text = (
                f"<b>{t(user_lang, 'welcome_title')}</b> 🚀\n\n"
                f"{t(user_lang, 'welcome_features')}\n\n"
                f"<b>{t(user_lang, 'welcome_your_lang')}: {user_lang}</b>\n"
                f"<b>{t(user_lang, 'welcome_action')}</b>"
            )
            
            async with aiohttp.ClientSession() as session:
                # Answer callback first
                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", 
                    json={"callback_query_id": cb["id"]})
                
                # Edit the message to show welcome
                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendAnimation", json={
                    "chat_id": user_id, 
                    "animation": "https://raw.githubusercontent.com/hsabhshsabhs/voca_ai_language/main/Image/gif.mp4",
                    "caption": welcome_text, 
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": t(user_lang, "channel_btn"), "url": "https://t.me/lingvoaichanel"}],
                            [{"text": t(user_lang, "affiliate_btn"), "callback_data": "affiliate_info"}]
                        ]
                    }
                })
            return {"ok": True}

    message = update.get("message", {})
    if "successful_payment" in message:
        sp = message["successful_payment"]
        payload = sp.get("invoice_payload", "")
        if payload.startswith("stars_"):
            try:
                tg_id = int(payload.split("_")[1])
                db = SessionLocal()
                user = db.query(User).filter(User.telegram_id == tg_id).first()
                if user:
                    user.credits += sp["total_amount"] * 2
                    db.commit()
                db.close()
            except: pass
        return {"ok": True}

    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")
    if text.startswith("/start") and chat_id:
        db = SessionLocal()
        user = db.query(User).filter(User.telegram_id == chat_id).first()
        is_new_user = False
        if not user:
            user = User(telegram_id=chat_id, username=message["from"].get("username"), first_name=message["from"].get("first_name"), credits=30.0)
            db.add(user); db.commit()
            is_new_user = True
            if "ref_" in text:
                try:
                    ref_id = int(text.split("ref_")[1])
                    if ref_id != chat_id:
                        referrer = db.query(User).filter(User.telegram_id == ref_id).first()
                        if referrer:
                            referrer.credits += 30.0; db.commit()
                            async with aiohttp.ClientSession() as session:
                                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                                    "chat_id": ref_id,
                                    "text": f"<b>🎉 {t(user.user_lang or 'English', 'referral_bonus')}</b>",
                                    "parse_mode": "HTML"
                                })
                except: pass
        db.close()

        # If returning user with lang set, show welcome. New users see lang selection.
        if not is_new_user and user.user_lang:
            u_lang = user.user_lang if user.user_lang else "English"
            welcome_text = (
                f"<b>{t(u_lang, 'welcome_title')}</b> 🚀\n\n"
                f"{t(u_lang, 'welcome_desc')}\n\n"
                f"<b>{t(u_lang, 'welcome_action')}</b>"
            )
            async with aiohttp.ClientSession() as session:
                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendAnimation", json={
                    "chat_id": chat_id, 
                    "animation": "https://raw.githubusercontent.com/hsabhshsabhs/voca_ai_language/main/Image/gif.mp4",
                    "caption": welcome_text, 
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": t(u_lang, "channel_btn"), "url": "https://t.me/lingvoaichanel"}],
                            [{"text": t(u_lang, "affiliate_btn"), "callback_data": "affiliate_info"}]
                        ]
                    }
                })
        else:
            # New user - ask for language preference
            lang_select_text = (
                f"<b>{t('English', 'lang_select_title')}</b>\n\n"
                f"{t('English', 'lang_select_desc')}\n\n"
                f"{t('English', 'lang_select_action')}"
            )
            async with aiohttp.ClientSession() as session:
                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id, 
                    "text": lang_select_text, 
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "🇷🇺 Русский", "callback_data": "user_lang_ru"},
                             {"text": "🇬🇧 English", "callback_data": "user_lang_en"},
                             {"text": "🇪🇸 Español", "callback_data": "user_lang_es"},
                             {"text": "🇧🇷 Português", "callback_data": "user_lang_pt"}],
                            [{"text": "🇩🇪 Deutsch", "callback_data": "user_lang_de"},
                             {"text": "🇫🇷 Français", "callback_data": "user_lang_fr"},
                             {"text": "🇮🇹 Italiano", "callback_data": "user_lang_it"},
                             {"text": "🇯🇵 日本語", "callback_data": "user_lang_ja"}],
                            [{"text": "🇨🇳 中文", "callback_data": "user_lang_zh"},
                             {"text": "🇰🇷 한국어", "callback_data": "user_lang_ko"},
                             {"text": "🇳🇱 Nederlands", "callback_data": "user_lang_nl"},
                             {"text": "🇵🇱 Polski", "callback_data": "user_lang_pl"}],
                            [{"text": "🇹🇷 Türkçe", "callback_data": "user_lang_tr"},
                             {"text": "🇸🇦 العربية", "callback_data": "user_lang_ar"},
                             {"text": "🇮🇳 हिन्दी", "callback_data": "user_lang_hi"},
                             {"text": "🇮🇩 Bahasa", "callback_data": "user_lang_id"}]
                        ]
                    }
                })
        return {"ok": True}

    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))









