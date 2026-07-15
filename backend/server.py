from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta, date
import jwt
import bcrypt
import shutil
import re
import secrets
import hashlib
import asyncio
import json
import math
from zoneinfo import ZoneInfo

# Fuso horário de Portugal continental (trata automaticamente verão/inverno).
# Os registos são guardados em UTC; converte-se para Lisboa só ao apresentar.
LISBON_TZ = ZoneInfo("Europe/Lisbon")

# Resend for email
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False

# httpx para chamadas a APIs externas (ex.: Google Places — avaliações)
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'hr-system-secret-key-2024')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Admin Master Configuration (from environment variables)
MASTER_ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'geral@olacai.com')
MASTER_ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH')

# Perfis com acesso de gestão (acesso operacional completo). Todos podem fazer
# tudo; apenas o admin master (por email) cria/gere outros gestores.
MANAGER_ROLES = ["admin", "gerente", "contabilista"]

# Password Reset Configuration
RESET_TOKEN_EXPIRATION_HOURS = 1

# Resend Email Configuration
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')
# URL do frontend usado nos links de recuperação de palavra-passe.
# Em produção definir FRONTEND_URL no .env (ex.: https://rh.suaempresa.pt)
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# Google Places API (avaliações por loja). A chave fica SÓ no servidor (.env),
# nunca no frontend nem no git. Ativar "Places API" na Google Cloud e criar a chave.
GOOGLE_PLACES_API_KEY = os.environ.get('GOOGLE_PLACES_API_KEY')
# Quanto tempo guardar em cache as avaliações de cada loja (em minutos).
# Evita gastar quota/€ da Google a cada abertura da página.
GOOGLE_REVIEWS_CACHE_MINUTES = int(os.environ.get('GOOGLE_REVIEWS_CACHE_MINUTES', '360'))

# Initialize Resend
if RESEND_AVAILABLE and RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# Password validation configuration
MIN_PASSWORD_LENGTH = 8

# File upload directory
UPLOAD_DIR = ROOT_DIR / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)

# Create the main app
app = FastAPI(title="RH grupo Lisbonb - Sistema de Gestão")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== PASSWORD UTILITIES ====================

def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password meets minimum security requirements"""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"A palavra-passe deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres"
    return True, ""

def validate_photo_data_url(photo):
    """Valida uma foto em data URL (base64). Levanta HTTP 400 se inválida."""
    if photo:
        if not isinstance(photo, str) or not photo.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="Formato de imagem inválido")
        if len(photo) > 4_000_000:  # ~3MB
            raise HTTPException(status_code=400, detail="Imagem demasiado grande (máx. ~3MB)")

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash"""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

def create_token(user_id: str, email: str, role: str, employee_id: str = None, must_change_password: bool = False) -> str:
    """Create JWT token with user information"""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "employee_id": employee_id,
        "must_change_password": must_change_password,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

# ==================== PASSWORD RESET UTILITIES ====================

def generate_reset_code() -> str:
    """Generate a secure 6-digit code for password reset"""
    return f"{secrets.randbelow(1000000):06d}"

def hash_reset_token(token: str) -> str:
    """Hash the reset token using SHA256 for storage"""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def get_password_reset_email_html(user_name: str, reset_code: str) -> str:
    """Generate HTML email template for password reset code"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    </head>
    <body style=\"margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; background-color: #f4f4f4;\">
        <table role=\"presentation\" style=\"width: 100%; border-collapse: collapse;\">
            <tr>
                <td style=\"padding: 40px 0;\">
                    <table role=\"presentation\" style=\"width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);\">
                        <tr>
                            <td style=\"background-color: #1a365d; padding: 30px; text-align: center;\">
                                <h1 style=\"color: #ffffff; margin: 0; font-size: 24px;\">RH grupo Lisbonb</h1>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding: 40px 30px;\">
                                <h2 style=\"color: #1a365d; margin: 0 0 20px 0; font-size: 20px;\">Código de Redefinição</h2>
                                <p style=\"color: #4a5568; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;\">
                                    Olá <strong>{user_name}</strong>,
                                </p>
                                <p style=\"color: #4a5568; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;\">
                                    Recebemos um pedido para redefinir a palavra-passe da sua conta. Utilize o código de 6 dígitos abaixo para continuar no site:
                                </p>
                                <div style=\"text-align: center; margin: 30px 0;\">
                                    <div style=\"display: inline-block; padding: 16px 24px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #f8fafc;\">
                                        <span style=\"font-size: 32px; letter-spacing: 6px; color: #1a365d; font-weight: bold;\">{reset_code}</span>
                                    </div>
                                </div>
                                <p style=\"color: #718096; font-size: 14px; line-height: 1.6; margin: 20px 0 0 0;\">
                                    Este código é válido por <strong>1 hora</strong>. Se não solicitou esta alteração, pode ignorar este email em segurança.
                                </p>
                                <p style=\"color: #718096; font-size: 14px; line-height: 1.6; margin: 10px 0 0 0;\">
                                    Por segurança, não partilhe este código com ninguém.
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"background-color: #f7fafc; padding: 20px 30px; text-align: center; border-top: 1px solid #e2e8f0;\">
                                <p style=\"color: #a0aec0; font-size: 12px; margin: 0;\">
                                    © 2024 RH grupo Lisbonb. Todos os direitos reservados.
                                </p>
                                <p style=\"color: #a0aec0; font-size: 12px; margin: 10px 0 0 0;\">
                                    Este é um email automático, por favor não responda.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

async def send_password_reset_email(email: str, user_name: str, reset_code: str) -> bool:
    """Send password reset code email using Resend"""
    if not RESEND_AVAILABLE or not RESEND_API_KEY:
        logger.warning("Resend not configured. Password reset email not sent.")
        return False

    html_content = get_password_reset_email_html(user_name, reset_code)

    params = {
        "from": SENDER_EMAIL,
        "to": [email],
        "subject": "Código de Redefinição - RH grupo Lisbonb",
        "html": html_content
    }

    try:
        email_response = await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Password reset code email sent to {email}, ID: {email_response.get('id')}")
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email: {str(e)}")
        return False

def get_leave_request_email_html(employee_name: str, type_label: str, start_date: str, end_date: str, reason: str) -> str:
    """Template HTML do email de novo pedido de férias/ausência."""
    reason_html = f'<p style="margin:8px 0 0;"><strong>Motivo:</strong> {reason}</p>' if reason else ""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 560px; margin: 0 auto; color: #1f2937;">
      <div style="background:#4f46e5; color:#fff; padding:20px; border-radius:8px 8px 0 0;">
        <h2 style="margin:0; font-size:18px;">Novo pedido de {type_label}</h2>
      </div>
      <div style="border:1px solid #e5e7eb; border-top:none; padding:20px; border-radius:0 0 8px 8px;">
        <p style="margin:0 0 12px;">O colaborador <strong>{employee_name}</strong> submeteu um pedido de {type_label}.</p>
        <p style="margin:4px 0;"><strong>Início:</strong> {start_date}</p>
        <p style="margin:4px 0;"><strong>Fim:</strong> {end_date}</p>
        {reason_html}
        <p style="margin:16px 0 0; font-size:13px; color:#6b7280;">
          Aceda ao RH grupo Lisbonb para aprovar ou recusar o pedido.
        </p>
      </div>
    </div>
    """

async def send_leave_request_email(to_emails: list, employee_name: str, type_label: str, start_date: str, end_date: str, reason: str = None) -> bool:
    """Avisar admins/gestores por email de um novo pedido de férias/ausência."""
    if not RESEND_AVAILABLE or not RESEND_API_KEY or not to_emails:
        return False

    params = {
        "from": SENDER_EMAIL,
        "to": to_emails,
        "subject": f"Novo pedido de {type_label} - {employee_name}",
        "html": get_leave_request_email_html(employee_name, type_label, start_date, end_date, reason or ""),
    }
    try:
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Leave request email sent to {to_emails}")
        return True
    except Exception as e:
        logger.error(f"Failed to send leave request email: {str(e)}")
        return False

async def notify_managers_of_leave_request(employee_name: str, leave_type: str, start_date: str, end_date: str, reason: str = None):
    """Envia o email a todos os admins/gestores. Falha em silêncio (não bloqueia o pedido)."""
    try:
        managers = await db.users.find(
            {"role": {"$in": MANAGER_ROLES}},
            {"_id": 0, "email": 1}
        ).to_list(100)
        emails = [m["email"] for m in managers if m.get("email")]
        if not emails:
            return
        type_label = "férias" if leave_type == "ferias" else "ausência"
        await send_leave_request_email(emails, employee_name, type_label, start_date, end_date, reason)
    except Exception as e:
        logger.error(f"Erro ao notificar gestores do pedido de ausência: {str(e)}")

def get_leave_decision_email_html(employee_name: str, status: str, type_label: str, start_date: str, end_date: str, admin_response: str) -> str:
    """Template do email de decisão (aprovado/recusado) para o colaborador."""
    approved = status == "aprovado"
    color = "#0F9D70" if approved else "#D64545"
    chip = "Aprovado" if approved else "Recusado"
    note_html = f'<p style="margin:14px 0 0;"><strong>Resposta da administração:</strong> {admin_response}</p>' if admin_response else ""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 560px; margin: 0 auto; color: #1f2937;">
      <div style="background:#1366F0; color:#fff; padding:20px; border-radius:8px 8px 0 0;">
        <h2 style="margin:0; font-size:18px;">RH grupo Lisbonb</h2>
      </div>
      <div style="border:1px solid #e5e7eb; border-top:none; padding:22px; border-radius:0 0 8px 8px;">
        <p style="margin:0 0 14px;">Olá {employee_name},</p>
        <p style="margin:0 0 14px;">O seu pedido de <strong>{type_label}</strong> foi:</p>
        <div style="display:inline-block; background:{color}; color:#fff; font-weight:bold; padding:8px 18px; border-radius:20px;">{chip}</div>
        <p style="margin:18px 0 4px;"><strong>Período:</strong> {start_date} a {end_date}</p>
        {note_html}
        <p style="margin:18px 0 0; font-size:13px; color:#6b7280;">Pode consultar os detalhes no sistema RH grupo Lisbonb.</p>
      </div>
    </div>
    """

async def notify_employee_of_leave_decision(employee_email: str, employee_name: str, status: str, type_label: str, start_date: str, end_date: str, admin_response: str = None):
    """Avisa o colaborador por email da decisão do seu pedido. Falha em silêncio."""
    if not RESEND_AVAILABLE or not RESEND_API_KEY or not employee_email:
        return
    try:
        params = {
            "from": SENDER_EMAIL,
            "to": [employee_email],
            "subject": f"O seu pedido de {type_label} foi {status}",
            "html": get_leave_decision_email_html(employee_name, status, type_label, start_date, end_date, admin_response or ""),
        }
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Leave decision email sent to {employee_email}")
    except Exception as e:
        logger.error(f"Failed to send leave decision email: {str(e)}")

def get_welcome_email_html(employee_name: str, company_name: str, login_email: str, temp_password: str, login_url: str) -> str:
    """Template do email de boas-vindas a um novo colaborador (com acessos)."""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 560px; margin: 0 auto; color: #1f2937;">
      <div style="background:linear-gradient(135deg,#1366F0,#16B8A6); color:#fff; padding:26px 22px; border-radius:8px 8px 0 0;">
        <h2 style="margin:0; font-size:20px;">Bem-vindo ao grupo Lisbonb 👋</h2>
        <p style="margin:6px 0 0; font-size:14px; opacity:0.9;">A sua conta de colaborador já está ativa.</p>
      </div>
      <div style="border:1px solid #e5e7eb; border-top:none; padding:22px; border-radius:0 0 8px 8px;">
        <p style="margin:0 0 14px;">Olá <strong>{employee_name}</strong>,</p>
        <p style="margin:0 0 16px;">Foi criado o seu acesso ao sistema de RH da <strong>{company_name}</strong>.
        Use os dados abaixo para entrar:</p>
        <div style="background:#f8fafc; border:1px solid #e5e7eb; border-radius:8px; padding:16px; margin:0 0 18px;">
          <p style="margin:0 0 8px; font-size:14px;"><strong>Email:</strong> {login_email}</p>
          <p style="margin:0; font-size:14px;"><strong>Palavra-passe temporária:</strong>
            <span style="font-family:monospace; background:#eef2ff; color:#1366F0; padding:2px 8px; border-radius:5px;">{temp_password}</span>
          </p>
        </div>
        <div style="text-align:center; margin:0 0 18px;">
          <a href="{login_url}" style="display:inline-block; background:#1366F0; color:#fff; text-decoration:none; font-weight:bold; padding:12px 26px; border-radius:8px;">Aceder ao RH</a>
        </div>
        <p style="margin:0; font-size:13px; color:#6b7280;">
          Por segurança, será pedido para <strong>alterar a palavra-passe</strong> no primeiro acesso.
          Se não reconhece este email, ignore-o.
        </p>
      </div>
    </div>
    """

async def send_welcome_email(email: str, employee_name: str, company_name: str, temp_password: str) -> bool:
    """Envia o email de boas-vindas com os acessos. Falha em silêncio (não bloqueia a criação)."""
    if not RESEND_AVAILABLE or not RESEND_API_KEY or not email:
        logger.warning("Resend não configurado — email de boas-vindas não enviado.")
        return False
    try:
        params = {
            "from": SENDER_EMAIL,
            "to": [email],
            "subject": "Bem-vindo ao grupo Lisbonb — os seus acessos",
            "html": get_welcome_email_html(employee_name, company_name, email, temp_password, FRONTEND_URL),
        }
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Welcome email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email: {str(e)}")
        return False

# ==================== MODELS ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "colaborador"

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    employee_id: Optional[str] = None
    must_change_password: bool = False
    is_master_admin: bool = False

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordCodeRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str

    @field_validator('code')
    @classmethod
    def validate_code(cls, v):
        code = v.strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("O código deve ter 6 dígitos")
        return code

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

class VerifyResetCodeRequest(BaseModel):
    email: EmailStr
    code: str

    @field_validator('code')
    @classmethod
    def validate_code(cls, v):
        code = v.strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("O código deve ter 6 dígitos")
        return code

class CompanyCreate(BaseModel):
    name: str
    description: Optional[str] = None

class CompanyResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: str

class LocationCreate(BaseModel):
    name: str
    company_id: str
    address: Optional[str] = None
    # Cerca geográfica (opcional): posição do local e raio em metros.
    # Se geofence_radius estiver definido (>0), o ponto só é aceite dentro do raio.
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geofence_radius: Optional[int] = None
    # ID do local no Google (Place ID) — usado para puxar avaliações no Marketing.
    google_place_id: Optional[str] = None

class LocationResponse(BaseModel):
    id: str
    name: str
    company_id: str
    company_name: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geofence_radius: Optional[int] = None
    google_place_id: Optional[str] = None

class EmployeeCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    company_id: str
    location_id: Optional[str] = None  # opcional: colaboradores sem local físico
    position: str
    contract_type: str
    start_date: str
    vacation_days: int = 22
    observations: Optional[str] = None
    # Isento de cerca geográfica (ex.: trabalha em vários locais).
    # Se True, pode bater ponto de qualquer lugar (a localização é só registada).
    geofence_exempt: bool = False
    # Dados pessoais (o admin pode preencher; o colaborador também os edita)
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo: Optional[str] = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    company_id: Optional[str] = None
    location_id: Optional[str] = None
    position: Optional[str] = None
    contract_type: Optional[str] = None
    start_date: Optional[str] = None
    vacation_days: Optional[int] = None
    observations: Optional[str] = None
    geofence_exempt: Optional[bool] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo: Optional[str] = None

class EmployeeResponse(BaseModel):
    id: str
    user_id: str
    name: str
    email: str
    company_id: str
    company_name: Optional[str] = None
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    position: str
    contract_type: str
    start_date: str
    vacation_days: int
    vacation_days_used: int = 0
    vacation_days_available: int = 0
    observations: Optional[str] = None
    geofence_exempt: bool = False
    # Dados de perfil (editáveis pelo próprio colaborador)
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo: Optional[str] = None  # imagem em data URL (base64)
    created_at: str

class SelfProfileUpdate(BaseModel):
    """Campos que o próprio colaborador pode editar no seu perfil."""
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo: Optional[str] = None

class TimeRecordCreate(BaseModel):
    record_type: str  # entrada or saida
    # Geolocalização (opcional - o browser pode negar)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None  # precisão em metros

class TimeRecordCorrection(BaseModel):
    time: str
    justification: str

class TimeRecordResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    record_type: str
    time: str
    corrected: bool = False
    correction_history: List[dict] = []
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None

class AdminLeaveCreate(BaseModel):
    user_id: str = Field(alias="userId")
    leave_type: str = Field(alias="type")
    start_date: str = Field(alias="startDate")
    end_date: str = Field(alias="endDate")
    reason: Optional[str] = None
    is_paid: bool = Field(alias="isPaid")

    model_config = {"populate_by_name": True}

    @field_validator('leave_type')
    @classmethod
    def validate_leave_type(cls, v):
        if v not in ["ferias", "ausencia"]:
            raise ValueError("Tipo inválido. Use 'ferias' ou 'ausencia'")
        return v

class WorkScheduleTemplateCreate(BaseModel):
    name: str
    work_days: List[int] = Field(alias="workDays")
    # Hora de início do turno (HH:MM). Usada para lembrar o colaborador no app.
    start_time: Optional[str] = Field(default=None, alias="startTime")

    model_config = {"populate_by_name": True}

    @field_validator('work_days')
    @classmethod
    def validate_work_days(cls, v):
        if not v:
            raise ValueError("Selecione pelo menos um dia de trabalho")
        if any(day not in range(0, 7) for day in v):
            raise ValueError("Dias de trabalho inválidos")
        if len(set(v)) != len(v):
            raise ValueError("Dias de trabalho duplicados")
        return v

    @field_validator('start_time')
    @classmethod
    def validate_start_time(cls, v):
        if v in (None, ""):
            return None
        if not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', v):
            raise ValueError("Hora inválida. Use o formato HH:MM")
        return v

class WorkScheduleTemplateResponse(BaseModel):
    id: str
    name: str
    work_days: List[int]
    start_time: Optional[str] = None
    created_at: str

class WorkScheduleAssignmentCreate(BaseModel):
    employee_id: str = Field(alias="employeeId")
    template_id: str = Field(alias="templateId")
    start_date: str = Field(alias="startDate")
    end_date: Optional[str] = Field(default=None, alias="endDate")

    model_config = {"populate_by_name": True}

    @field_validator('start_date', 'end_date')
    @classmethod
    def validate_dates(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("Datas inválidas. Use o formato AAAA-MM-DD")
        return v

class WorkScheduleAssignmentResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    template_id: str
    template_name: Optional[str] = None
    work_days: List[int] = []
    start_date: str
    end_date: Optional[str] = None
    created_at: str

class LeaveRequestCreate(BaseModel):
    leave_type: str  # ferias, falta, doenca, folga
    start_date: str
    end_date: str
    observation: Optional[str] = None

class LeaveRequestResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    leave_type: str
    start_date: str
    end_date: str
    status: str  # pendente, aprovado, recusado
    observation: Optional[str] = None
    document_id: Optional[str] = None
    admin_response: Optional[str] = None
    created_by: Optional[str] = None
    is_paid: Optional[bool] = None
    counted_days: Optional[int] = None
    audit_log: Optional[List[dict]] = None
    created_at: str

class FolderCreate(BaseModel):
    name: str
    employee_id: str
    allow_employee_upload: bool = False

class FolderResponse(BaseModel):
    id: str
    name: str
    employee_id: str
    allow_employee_upload: bool
    created_at: str

class DocumentResponse(BaseModel):
    id: str
    name: str
    folder_id: str
    folder_name: Optional[str] = None
    employee_id: str
    uploaded_by: str
    uploaded_by_name: Optional[str] = None
    file_path: str
    created_at: str

class NotificationResponse(BaseModel):
    id: str
    user_id: str
    title: str
    message: str
    read: bool
    created_at: str

class DashboardStats(BaseModel):
    total_employees: int
    total_companies: int
    pending_requests: int
    today_records: int
    employees_by_company: List[dict]
    recent_requests: List[dict]

def build_audit_entry(action: str, actor: dict) -> dict:
    return {
        "action": action,
        "actor_id": actor.get("user_id"),
        "actor_name": actor.get("name"),
        "actor_role": actor.get("role"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ==================== VACATION CALCULATION ====================

def _easter_sunday(year: int) -> date:
    """Domingo de Páscoa (algoritmo anónimo gregoriano)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)

_pt_holiday_cache: dict = {}

def get_pt_holidays(year: int) -> set:
    """Feriados nacionais obrigatórios de Portugal para o ano indicado."""
    if year in _pt_holiday_cache:
        return _pt_holiday_cache[year]
    easter = _easter_sunday(year)
    holidays = {
        date(year, 1, 1),    # Ano Novo
        date(year, 4, 25),   # Dia da Liberdade
        date(year, 5, 1),    # Dia do Trabalhador
        date(year, 6, 10),   # Dia de Portugal
        date(year, 8, 15),   # Assunção de Nossa Senhora
        date(year, 10, 5),   # Implantação da República
        date(year, 11, 1),   # Todos os Santos
        date(year, 12, 1),   # Restauração da Independência
        date(year, 12, 8),   # Imaculada Conceição
        date(year, 12, 25),  # Natal
        easter - timedelta(days=2),   # Sexta-feira Santa
        easter,                       # Páscoa
        easter + timedelta(days=60),  # Corpo de Deus
    }
    _pt_holiday_cache[year] = holidays
    return holidays

async def get_custom_holiday_monthdays(company_id: Optional[str], location_id: Optional[str]) -> set:
    """Feriados personalizados (ex.: municipais) aplicáveis, como pares (mês, dia).
    Âmbito: grupo (sem empresa/loja), por empresa, ou por loja. Recorrem todos os anos."""
    docs = await db.holidays.find({}, {"_id": 0}).to_list(500)
    applies = set()
    for h in docs:
        hc = h.get("company_id")
        hl = h.get("location_id")
        if (not hc and not hl) or (hc and hc == company_id) or (hl and hl == location_id):
            try:
                applies.add((int(h["month"]), int(h["day"])))
            except (KeyError, ValueError, TypeError):
                continue
    return applies

def find_schedule_assignment(assignments: list[dict], target_date: date):
    for assignment in assignments:
        start_dt = datetime.fromisoformat(assignment["start_date"]).date()
        end_raw = assignment.get("end_date")
        end_dt = datetime.fromisoformat(end_raw).date() if end_raw else None
        if target_date >= start_dt and (end_dt is None or target_date <= end_dt):
            return assignment
    return None

async def calculate_leave_counted_days(employee_id: str, start_date: str, end_date: str) -> int:
    """Count leave days based on work schedule."""
    start_dt = datetime.fromisoformat(start_date).date()
    end_dt = datetime.fromisoformat(end_date).date()

    if start_dt > end_dt:
        return 0

    assignments = await db.work_schedule_assignments.find(
        {"employee_id": employee_id},
        {"_id": 0}
    ).sort("start_date", 1).to_list(200)

    for assignment in assignments:
        if not assignment.get("work_days"):
            template = await db.work_schedule_templates.find_one(
                {"id": assignment.get("template_id")},
                {"_id": 0, "work_days": 1}
            )
            if template:
                assignment["work_days"] = template.get("work_days", [])

    # Feriados personalizados (municipais) aplicáveis a este colaborador
    emp = await db.employees.find_one(
        {"id": employee_id}, {"_id": 0, "company_id": 1, "location_id": 1}
    )
    custom_holidays = await get_custom_holiday_monthdays(
        emp.get("company_id") if emp else None,
        emp.get("location_id") if emp else None,
    )

    total_days = 0
    current_date = start_dt
    while current_date <= end_dt:
        # Feriados (nacionais ou municipais) nunca contam
        if (current_date in get_pt_holidays(current_date.year)
                or (current_date.month, current_date.day) in custom_holidays):
            current_date += timedelta(days=1)
            continue

        assignment = find_schedule_assignment(assignments, current_date)
        if assignment:
            # Com escala: só contam os dias de trabalho (folgas não contam)
            work_days = assignment.get("work_days", [])
            if current_date.weekday() in work_days:
                total_days += 1
        else:
            # Sem escala: por defeito, só dias úteis (Seg-Sex); fim de semana não conta
            if current_date.weekday() < 5:
                total_days += 1
        current_date += timedelta(days=1)

    return total_days

async def calculate_vacation_days_used(employee_id: str, year: Optional[int] = None, status: str = "aprovado") -> int:
    """Vacation days counted for an employee in a given year (default: current year).

    status selects which requests count: "aprovado" (default) or "pendente".
    """
    if year is None:
        year = datetime.now(timezone.utc).year
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    vacation_requests = await db.leave_requests.find({
        "employee_id": employee_id,
        "leave_type": "ferias",
        "status": status,
        "$or": [
            {"start_date": {"$gte": year_start, "$lte": year_end}},
            {"end_date": {"$gte": year_start, "$lte": year_end}},
            {"$and": [{"start_date": {"$lte": year_start}}, {"end_date": {"$gte": year_end}}]}
        ]
    }, {"_id": 0}).to_list(1000)

    total_days = 0
    for request in vacation_requests:
        start = datetime.fromisoformat(request["start_date"])
        end = datetime.fromisoformat(request["end_date"])

        # Adjust dates to the requested year boundaries
        year_start_date = datetime(year, 1, 1)
        year_end_date = datetime(year, 12, 31)

        effective_start = max(start, year_start_date)
        effective_end = min(end, year_end_date)

        if effective_start <= effective_end:
            counted = await calculate_leave_counted_days(
                employee_id,
                effective_start.date().isoformat(),
                effective_end.date().isoformat()
            )
            total_days += counted

    return total_days

# ==================== AUTH UTILITIES ====================

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token"""
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

async def admin_required(current_user: dict = Depends(get_current_user)):
    """Acesso operacional completo: admin OU gestor (gerente).

    O gestor/contabilista pode fazer tudo. A gestão de outros gestores/admins
    continua exclusiva do admin master (verificação por email nos /admins).
    """
    if current_user.get("role") not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas administradores ou gestores.")
    user_doc = await db.users.find_one({"id": current_user.get("user_id")}, {"_id": 0, "name": 1, "role": 1})
    current_user["name"] = user_doc.get("name") if user_doc else current_user.get("email")
    return current_user

async def admin_manager_required(current_user: dict = Depends(get_current_user)):
    """Require admin or manager role"""
    if current_user.get("role") not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas administradores ou gestores.")
    user_doc = await db.users.find_one({"id": current_user.get("user_id")}, {"_id": 0, "name": 1, "role": 1})
    current_user["name"] = user_doc.get("name") if user_doc else current_user.get("email")
    return current_user

async def ensure_master_admin_exists():
    """Garante que o admin master existe.

    Password vem de ADMIN_PASSWORD (texto simples, encriptada aqui) ou, em
    alternativa, de ADMIN_PASSWORD_HASH (hash já pronto). Usar ADMIN_PASSWORD
    evita problemas com o '$' do hash em ficheiros .env / docker-compose.
    Se o admin já existir e ADMIN_PASSWORD estiver definido, a password é
    atualizada (o .env é a fonte de verdade para o admin master).
    """
    admin_password = os.environ.get('ADMIN_PASSWORD')
    password_hash = hash_password(admin_password) if admin_password else MASTER_ADMIN_PASSWORD_HASH

    if not password_hash:
        logger.warning("Nem ADMIN_PASSWORD nem ADMIN_PASSWORD_HASH configurados. Admin master não criado.")
        return

    existing = await db.users.find_one({"email": MASTER_ADMIN_EMAIL})
    if not existing:
        admin_doc = {
            "id": str(uuid.uuid4()),
            "email": MASTER_ADMIN_EMAIL,
            "password": password_hash,
            "name": "Administrador Principal",
            "role": "admin",
            "employee_id": None,
            "must_change_password": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.users.insert_one(admin_doc)
        logger.info(f"Master admin created: {MASTER_ADMIN_EMAIL}")
    elif admin_password:
        # Repara/atualiza a password do admin master a partir do .env
        await db.users.update_one(
            {"email": MASTER_ADMIN_EMAIL},
            {"$set": {"password": password_hash, "must_change_password": False}}
        )
        logger.info(f"Master admin password atualizada: {MASTER_ADMIN_EMAIL}")

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/login")
async def login(credentials: UserLogin):
    """Authenticate user and return JWT token"""
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    
    must_change_password = user.get("must_change_password", False)
    
    token = create_token(
        user["id"], 
        user["email"], 
        user["role"], 
        user.get("employee_id"),
        must_change_password
    )
    
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "employee_id": user.get("employee_id"),
            "must_change_password": must_change_password,
            "is_master_admin": user["email"] == MASTER_ADMIN_EMAIL
        }
    }

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0, "password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    user["is_master_admin"] = user.get("email") == MASTER_ADMIN_EMAIL
    return UserResponse(**user)

@api_router.post("/auth/change-password")
async def change_password(request: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    """Change user password"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    
    # Verify current password
    if not verify_password(request.current_password, user["password"]):
        raise HTTPException(status_code=400, detail="Palavra-passe atual incorreta")
    
    # Check if new password is different from current
    if verify_password(request.new_password, user["password"]):
        raise HTTPException(status_code=400, detail="A nova palavra-passe deve ser diferente da atual")
    
    # Update password and set must_change_password to False
    new_password_hash = hash_password(request.new_password)
    await db.users.update_one(
        {"id": current_user["user_id"]},
        {"$set": {"password": new_password_hash, "must_change_password": False}}
    )
    
    # Generate new token with must_change_password = False
    token = create_token(
        user["id"],
        user["email"],
        user["role"],
        user.get("employee_id"),
        False
    )
    
    return {
        "message": "Palavra-passe alterada com sucesso",
        "token": token
    }

# ==================== PASSWORD RESET ENDPOINTS ====================

@api_router.post("/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """
    Request password reset. Sends email with 6-digit code if user exists.
    Always returns success to prevent email enumeration attacks.
    """
    success_message = {
        "message": "Se o email existir no sistema, receberá um código de 6 dígitos para redefinir a palavra-passe."
    }

    normalized_email = request.email.lower().strip()

    logger.info("=== FORGOT PASSWORD DEBUG ===")
    logger.info(f"Email RECEBIDO (raw): '{request.email}'")
    logger.info(f"Email NORMALIZADO: '{normalized_email}'")

    user = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}},
        {"_id": 0}
    )

    if not user:
        user = await db.users.find_one({"email": normalized_email}, {"_id": 0})

    all_users = await db.users.find({}, {"_id": 0, "email": 1, "id": 1}).to_list(100)
    logger.info(f"Total de usuários no banco: {len(all_users)}")
    for u in all_users:
        match = u.get('email', '').lower().strip() == normalized_email
        logger.info(f"  - '{u.get('email')}' | ID: {u.get('id')[:8]}... | MATCH: {match}")

    if not user:
        logger.warning(f"Usuário NÃO ENCONTRADO para email: '{normalized_email}'")
        logger.info("=== END FORGOT PASSWORD DEBUG ===")
        return success_message

    logger.info(f"Usuário ENCONTRADO: {user.get('email')} | ID: {user.get('id')}")
    logger.info(f"Nome: {user.get('name')}")

    reset_code = generate_reset_code()
    code_hash = hash_reset_token(reset_code)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRATION_HOURS)

    logger.info("Código de redefinição gerado e preparado para envio.")

    update_result = await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "reset_password_token": code_hash,
                "reset_password_expires": expires_at.isoformat()
            }
        }
    )

    logger.info(f"Update result: matched={update_result.matched_count}, modified={update_result.modified_count}")

    saved_user = await db.users.find_one({"id": user["id"]}, {"_id": 0, "email": 1, "reset_password_token": 1})
    logger.info("Verificação após salvar:")
    logger.info(f"  Email do usuário salvo: {saved_user.get('email')}")
    logger.info(f"  Token HASH no banco: {saved_user.get('reset_password_token')}")
    logger.info(f"  Hashes IGUAIS: {saved_user.get('reset_password_token') == code_hash}")

    email_sent = await send_password_reset_email(
        email=user["email"],
        user_name=user["name"],
        reset_code=reset_code
    )

    if email_sent:
        logger.info(f"Email ENVIADO com sucesso para: {user['email']}")
    else:
        logger.warning(f"FALHA ao enviar email para: {user['email']}")

    logger.info("=== END FORGOT PASSWORD DEBUG ===")

    return success_message

@api_router.post("/auth/reset-password")
async def reset_password(request: ResetPasswordCodeRequest):
    """
    Reset password using the code received via email.
    Code must be valid and not expired.
    """
    logger.info("=== RESET PASSWORD DEBUG ===")

    normalized_email = request.email.lower().strip()
    code = request.code.strip()

    logger.info(f"Email NORMALIZADO: '{normalized_email}'")
    logger.info(f"Código RECEBIDO LENGTH: {len(code)}")

    code_hash = hash_reset_token(code)

    user = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}, "reset_password_token": code_hash},
        {"_id": 0}
    )

    if not user:
        user = await db.users.find_one(
            {"email": normalized_email, "reset_password_token": code_hash},
            {"_id": 0}
        )

    if not user:
        logger.warning("Código NÃO encontrado para o email informado!")
        logger.info("=== END RESET PASSWORD DEBUG ===")
        raise HTTPException(
            status_code=400,
            detail="Código inválido ou expirado. Por favor, solicite um novo código."
        )

    expires_at = user.get("reset_password_expires")
    if expires_at:
        expires_datetime = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > expires_datetime:
            await db.users.update_one(
                {"id": user["id"]},
                {"$unset": {"reset_password_token": "", "reset_password_expires": ""}}
            )
            logger.warning("Código EXPIRADO!")
            logger.info("=== END RESET PASSWORD DEBUG ===")
            raise HTTPException(
                status_code=400,
                detail="Código expirado. Por favor, solicite um novo código."
            )

    new_password_hash = hash_password(request.new_password)

    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "password": new_password_hash,
                "must_change_password": False
            },
            "$unset": {
                "reset_password_token": "",
                "reset_password_expires": ""
            }
        }
    )

    logger.info(f"Password successfully reset for user {user['email']}")
    logger.info("=== END RESET PASSWORD DEBUG ===")

    return {
        "message": "Palavra-passe redefinida com sucesso. Pode agora fazer login com a nova palavra-passe."
    }

@api_router.post("/auth/verify-reset-code")
async def verify_reset_code(request: VerifyResetCodeRequest):
    """
    Verify if a password reset code is valid (for frontend validation before showing form).
    """
    logger.info("=== VERIFY CODE DEBUG ===")

    normalized_email = request.email.lower().strip()
    code = request.code.strip()

    logger.info(f"Email NORMALIZADO: '{normalized_email}'")
    logger.info(f"Código RECEBIDO LENGTH: {len(code)}")

    code_hash = hash_reset_token(code)

    user = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}, "reset_password_token": code_hash},
        {"_id": 0}
    )

    if not user:
        user = await db.users.find_one(
            {"email": normalized_email, "reset_password_token": code_hash},
            {"_id": 0}
        )

    if not user:
        logger.warning("Código NÃO encontrado para o email informado!")
        logger.info("=== END VERIFY CODE DEBUG ===")
        raise HTTPException(status_code=400, detail="Código inválido")

    expires_at = user.get("reset_password_expires")
    if expires_at:
        expires_datetime = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > expires_datetime:
            await db.users.update_one(
                {"id": user["id"]},
                {"$unset": {"reset_password_token": "", "reset_password_expires": ""}}
            )
            logger.warning("Código EXPIRADO!")
            logger.info("=== END VERIFY CODE DEBUG ===")
            raise HTTPException(status_code=400, detail="Código expirado")

    logger.info("=== END VERIFY CODE DEBUG ===")
    return {"valid": True, "email": user["email"]}

# ==================== ADMIN/MANAGER CREATION ====================

class AdminCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "admin"  # admin or gerente

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        if v not in MANAGER_ROLES:
            raise ValueError("Função inválida")
        return v

class AdminResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    created_at: str

@api_router.post("/admins", response_model=AdminResponse)
async def create_admin(admin: AdminCreate, current_user: dict = Depends(admin_required)):
    """Create a new admin or manager (admin only). Must change password on first login."""
    # Only master admin can create other admins
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if user["email"] != MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Apenas o administrador master pode criar outros administradores")
    
    # Check if email exists
    existing = await db.users.find_one({"email": admin.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email já registado")
    
    # Create admin/manager with must_change_password = True
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "email": admin.email,
        "password": hash_password(admin.password),
        "name": admin.name,
        "role": admin.role,
        "employee_id": None,
        "must_change_password": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    logger.info(f"New {admin.role} created: {admin.email}")
    
    return AdminResponse(
        id=user_id,
        email=admin.email,
        name=admin.name,
        role=admin.role,
        created_at=user_doc["created_at"]
    )

@api_router.get("/admins", response_model=List[AdminResponse])
async def get_admins(current_user: dict = Depends(admin_required)):
    """Get all admins and managers (master admin only)"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if user["email"] != MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Apenas o administrador master pode ver administradores")
    
    admins = await db.users.find(
        {"role": {"$in": MANAGER_ROLES}, "email": {"$ne": MASTER_ADMIN_EMAIL}},
        {"_id": 0, "password": 0}
    ).to_list(100)
    
    return [AdminResponse(**a) for a in admins]

class AdminUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    new_password: Optional[str] = None

@api_router.put("/admins/{admin_id}", response_model=AdminResponse)
async def update_admin(admin_id: str, payload: AdminUpdate, current_user: dict = Depends(admin_required)):
    """Editar um gestor/administrador (só o admin master): nome, email,
    tipo de acesso e, opcionalmente, definir uma password nova (o utilizador
    terá de a trocar no próximo login, como na criação)."""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if user["email"] != MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Apenas o administrador master pode editar administradores")

    admin = await db.users.find_one({"id": admin_id}, {"_id": 0})
    if not admin:
        raise HTTPException(status_code=404, detail="Administrador não encontrado")
    if admin["email"] == MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="O administrador master edita-se pelo .env do servidor")

    updates = {}
    if payload.name is not None and payload.name.strip():
        updates["name"] = payload.name.strip()
    if payload.role is not None:
        if payload.role not in MANAGER_ROLES:
            raise HTTPException(status_code=400, detail="Tipo de acesso inválido")
        updates["role"] = payload.role
    if payload.email is not None and payload.email != admin["email"]:
        existing = await db.users.find_one({"email": payload.email, "id": {"$ne": admin_id}})
        if existing:
            raise HTTPException(status_code=400, detail="Email já registado")
        updates["email"] = payload.email
    if payload.new_password:
        is_valid, message = validate_password_strength(payload.new_password)
        if not is_valid:
            raise HTTPException(status_code=400, detail=message)
        updates["password"] = hash_password(payload.new_password)
        updates["must_change_password"] = True  # troca obrigatória no próximo login

    if updates:
        await db.users.update_one({"id": admin_id}, {"$set": updates})
        logger.info(f"Admin atualizado por master: {admin_id} campos={list(updates.keys())}")

    updated = await db.users.find_one({"id": admin_id}, {"_id": 0, "password": 0})
    return AdminResponse(**updated)

@api_router.delete("/admins/{admin_id}")
async def delete_admin(admin_id: str, current_user: dict = Depends(admin_required)):
    """Delete an admin or manager (master admin only)"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if user["email"] != MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Apenas o administrador master pode eliminar administradores")
    
    admin = await db.users.find_one({"id": admin_id}, {"_id": 0})
    if not admin:
        raise HTTPException(status_code=404, detail="Administrador não encontrado")
    
    if admin["email"] == MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Não é possível eliminar o administrador master")
    
    await db.users.delete_one({"id": admin_id})
    return {"message": f"Administrador {admin['name']} eliminado com sucesso"}

# ==================== COMPANY ROUTES ====================

@api_router.post("/companies", response_model=CompanyResponse)
async def create_company(company: CompanyCreate, current_user: dict = Depends(admin_required)):
    company_id = str(uuid.uuid4())
    company_doc = {
        "id": company_id,
        "name": company.name,
        "description": company.description,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.companies.insert_one(company_doc)
    return CompanyResponse(**company_doc)

@api_router.get("/companies", response_model=List[CompanyResponse])
async def get_companies(current_user: dict = Depends(get_current_user)):
    companies = await db.companies.find({}, {"_id": 0}).to_list(100)
    return [CompanyResponse(**c) for c in companies]

@api_router.get("/companies/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: str, current_user: dict = Depends(get_current_user)):
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return CompanyResponse(**company)

@api_router.put("/companies/{company_id}", response_model=CompanyResponse)
async def update_company(company_id: str, company: CompanyCreate, current_user: dict = Depends(admin_required)):
    result = await db.companies.update_one(
        {"id": company_id},
        {"$set": {"name": company.name, "description": company.description}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    updated = await db.companies.find_one({"id": company_id}, {"_id": 0})
    return CompanyResponse(**updated)

@api_router.delete("/companies/{company_id}")
async def delete_company(company_id: str, current_user: dict = Depends(admin_required)):
    # Check if company has employees
    employee_count = await db.employees.count_documents({"company_id": company_id})
    if employee_count > 0:
        raise HTTPException(status_code=400, detail="Não é possível eliminar empresa com colaboradores associados")
    
    result = await db.companies.delete_one({"id": company_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    
    # Delete associated locations
    await db.locations.delete_many({"company_id": company_id})
    return {"message": "Empresa eliminada com sucesso"}

# ==================== LOCATION ROUTES ====================

@api_router.post("/locations", response_model=LocationResponse)
async def create_location(location: LocationCreate, current_user: dict = Depends(admin_required)):
    # Verify company exists
    company = await db.companies.find_one({"id": location.company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    
    location_id = str(uuid.uuid4())
    location_doc = {
        "id": location_id,
        "name": location.name,
        "company_id": location.company_id,
        "address": location.address,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "geofence_radius": location.geofence_radius,
        "google_place_id": location.google_place_id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.locations.insert_one(location_doc)
    return LocationResponse(**location_doc, company_name=company["name"])

@api_router.get("/locations", response_model=List[LocationResponse])
async def get_locations(company_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    locations = await db.locations.find(query, {"_id": 0}).to_list(100)
    
    # Get company names
    for loc in locations:
        company = await db.companies.find_one({"id": loc["company_id"]}, {"_id": 0})
        loc["company_name"] = company["name"] if company else None
    
    return [LocationResponse(**loc) for loc in locations]

@api_router.put("/locations/{location_id}", response_model=LocationResponse)
async def update_location(location_id: str, location: LocationCreate, current_user: dict = Depends(admin_required)):
    result = await db.locations.update_one(
        {"id": location_id},
        {"$set": {
            "name": location.name,
            "company_id": location.company_id,
            "address": location.address,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "geofence_radius": location.geofence_radius,
            "google_place_id": location.google_place_id,
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Local não encontrado")
    updated = await db.locations.find_one({"id": location_id}, {"_id": 0})
    company = await db.companies.find_one({"id": updated["company_id"]}, {"_id": 0})
    return LocationResponse(**updated, company_name=company["name"] if company else None)

@api_router.delete("/locations/{location_id}")
async def delete_location(location_id: str, current_user: dict = Depends(admin_required)):
    # Check if location has employees
    employee_count = await db.employees.count_documents({"location_id": location_id})
    if employee_count > 0:
        raise HTTPException(status_code=400, detail="Não é possível eliminar local com colaboradores associados")
    
    result = await db.locations.delete_one({"id": location_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Local não encontrado")
    return {"message": "Local eliminado com sucesso"}

# ==================== EMPLOYEE ROUTES ====================

@api_router.post("/employees", response_model=EmployeeResponse)
async def create_employee(employee: EmployeeCreate, current_user: dict = Depends(admin_required)):
    """Create employee with temporary password (must_change_password = true)"""
    # Check if email exists
    existing = await db.users.find_one({"email": employee.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email já registado")
    
    # Verify company and location
    company = await db.companies.find_one({"id": employee.company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    
    if employee.location_id:
        location = await db.locations.find_one({"id": employee.location_id}, {"_id": 0})
        if not location:
            raise HTTPException(status_code=404, detail="Local não encontrado")

    validate_photo_data_url(employee.photo)

    # Create user account with must_change_password = True (temporary password)
    user_id = str(uuid.uuid4())
    employee_id = str(uuid.uuid4())
    
    user_doc = {
        "id": user_id,
        "email": employee.email,
        "password": hash_password(employee.password),
        "name": employee.name,
        "role": "colaborador",
        "employee_id": employee_id,
        "must_change_password": True,  # User must change password on first login
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    # Create employee record
    employee_doc = {
        "id": employee_id,
        "user_id": user_id,
        "name": employee.name,
        "email": employee.email,
        "company_id": employee.company_id,
        "location_id": employee.location_id,
        "position": employee.position,
        "contract_type": employee.contract_type,
        "start_date": employee.start_date,
        "vacation_days": employee.vacation_days,
        "observations": employee.observations,
        "geofence_exempt": employee.geofence_exempt,
        "phone": employee.phone,
        "address": employee.address,
        "birth_date": employee.birth_date,
        "emergency_contact_name": employee.emergency_contact_name,
        "emergency_contact_phone": employee.emergency_contact_phone,
        "photo": employee.photo,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.employees.insert_one(employee_doc)
    
    # Create default folders
    default_folders = [
        {"name": "Contrato", "allow_employee_upload": False},
        {"name": "Recibos de Vencimento", "allow_employee_upload": False},
        {"name": "Documentos Pessoais", "allow_employee_upload": True},
        {"name": "Justificações de Faltas", "allow_employee_upload": True},
        {"name": "Outros", "allow_employee_upload": True}
    ]
    
    for folder in default_folders:
        folder_doc = {
            "id": str(uuid.uuid4()),
            "name": folder["name"],
            "employee_id": employee_id,
            "allow_employee_upload": folder["allow_employee_upload"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.folders.insert_one(folder_doc)
    
    # Create welcome notification with password change reminder
    notification_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": "Bem-vindo!",
        "message": f"A sua conta foi criada com sucesso. Bem-vindo à {company['name']}! Por favor, altere a sua palavra-passe temporária no primeiro acesso.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.notifications.insert_one(notification_doc)

    # Email de boas-vindas com os acessos (não bloqueia a criação se falhar)
    await send_welcome_email(employee.email, employee.name, company["name"], employee.password)

    return EmployeeResponse(
        **employee_doc,
        company_name=company["name"],
        location_name=location["name"] if employee.location_id and location else None
    )

@api_router.get("/employees", response_model=List[EmployeeResponse])
async def get_employees(
    company_id: Optional[str] = None,
    location_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    if company_id:
        query["company_id"] = company_id
    if location_id:
        query["location_id"] = location_id
    
    # If colaborador, only return their own data
    if current_user.get("role") == "colaborador":
        query["id"] = current_user.get("employee_id")
    
    employees = await db.employees.find(query, {"_id": 0}).to_list(1000)

    # Get company and location names and calculate vacation days
    for emp in employees:
        company = await db.companies.find_one({"id": emp["company_id"]}, {"_id": 0})
        location = await db.locations.find_one({"id": emp["location_id"]}, {"_id": 0})
        emp["company_name"] = company["name"] if company else None
        emp["location_name"] = location["name"] if location else None
        
        # Calculate vacation days used and available
        vacation_used = await calculate_vacation_days_used(emp["id"])
        emp["vacation_days_used"] = vacation_used
        emp["vacation_days_available"] = emp["vacation_days"] - vacation_used
    
    return [EmployeeResponse(**e) for e in employees]

@api_router.get("/employees/{employee_id}", response_model=EmployeeResponse)
async def get_employee(employee_id: str, current_user: dict = Depends(get_current_user)):
    # Colaboradores can only see their own data
    if current_user.get("role") == "colaborador" and current_user.get("employee_id") != employee_id:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    company = await db.companies.find_one({"id": employee["company_id"]}, {"_id": 0})
    location = await db.locations.find_one({"id": employee["location_id"]}, {"_id": 0})
    
    # Calculate vacation days used and available
    vacation_used = await calculate_vacation_days_used(employee_id)
    
    return EmployeeResponse(
        **employee,
        company_name=company["name"] if company else None,
        location_name=location["name"] if location else None,
        vacation_days_used=vacation_used,
        vacation_days_available=employee["vacation_days"] - vacation_used
    )

async def _build_employee_response(employee: dict) -> EmployeeResponse:
    company = await db.companies.find_one({"id": employee["company_id"]}, {"_id": 0})
    location = None
    if employee.get("location_id"):
        location = await db.locations.find_one({"id": employee["location_id"]}, {"_id": 0})
    vacation_used = await calculate_vacation_days_used(employee["id"])
    return EmployeeResponse(
        **employee,
        company_name=company["name"] if company else None,
        location_name=location["name"] if location else None,
        vacation_days_used=vacation_used,
        vacation_days_available=employee["vacation_days"] - vacation_used
    )

@api_router.get("/me/profile", response_model=EmployeeResponse)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    """Perfil do próprio colaborador (com foto e dados pessoais)."""
    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Perfil não encontrado")
    return await _build_employee_response(employee)

@api_router.put("/me/profile", response_model=EmployeeResponse)
async def update_my_profile(profile: SelfProfileUpdate, current_user: dict = Depends(get_current_user)):
    """O colaborador atualiza os seus próprios dados (foto, contactos, etc.)."""
    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")

    update_data = {k: v for k, v in profile.model_dump().items() if v is not None}

    photo = update_data.get("photo")
    if photo:
        if not photo.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="Formato de imagem inválido")
        if len(photo) > 4_000_000:  # ~3MB
            raise HTTPException(status_code=400, detail="Imagem demasiado grande (máx. ~3MB)")

    if update_data:
        await db.employees.update_one({"id": employee_id}, {"$set": update_data})

    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    return await _build_employee_response(employee)

@api_router.put("/employees/{employee_id}", response_model=EmployeeResponse)
async def update_employee(employee_id: str, employee: EmployeeUpdate, current_user: dict = Depends(admin_required)):
    update_data = {k: v for k, v in employee.model_dump().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum dado para atualizar")

    validate_photo_data_url(update_data.get("photo"))

    # Also update name in users collection if provided
    if "name" in update_data:
        emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
        if emp:
            await db.users.update_one({"id": emp["user_id"]}, {"$set": {"name": update_data["name"]}})
    
    result = await db.employees.update_one({"id": employee_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    updated = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    company = await db.companies.find_one({"id": updated["company_id"]}, {"_id": 0})
    location = await db.locations.find_one({"id": updated["location_id"]}, {"_id": 0})
    
    return EmployeeResponse(
        **updated,
        company_name=company["name"] if company else None,
        location_name=location["name"] if location else None
    )

@api_router.delete("/employees/{employee_id}")
async def delete_employee(employee_id: str, current_user: dict = Depends(admin_required)):
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    # Delete user account
    await db.users.delete_one({"id": employee["user_id"]})
    
    # Delete employee
    await db.employees.delete_one({"id": employee_id})
    
    # Delete time records
    await db.time_records.delete_many({"employee_id": employee_id})
    
    # Delete leave requests
    await db.leave_requests.delete_many({"employee_id": employee_id})
    
    # Delete folders and documents
    folders = await db.folders.find({"employee_id": employee_id}, {"_id": 0}).to_list(100)
    for folder in folders:
        # Delete files from filesystem
        docs = await db.documents.find({"folder_id": folder["id"]}, {"_id": 0}).to_list(100)
        for doc in docs:
            file_path = Path(doc["file_path"])
            if file_path.exists():
                file_path.unlink()
        await db.documents.delete_many({"folder_id": folder["id"]})
    await db.folders.delete_many({"employee_id": employee_id})
    
    # Delete notifications
    await db.notifications.delete_many({"user_id": employee["user_id"]})
    
    return {"message": "Colaborador eliminado com sucesso"}

# ==================== RESET PASSWORD (Admin function) ====================

class AdminResetPasswordRequest(BaseModel):
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

@api_router.post("/employees/{employee_id}/reset-password")
async def reset_employee_password(employee_id: str, request: AdminResetPasswordRequest, current_user: dict = Depends(admin_required)):
    """Admin can reset employee password (sets must_change_password = True)"""
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    # Update password and set must_change_password to True
    new_password_hash = hash_password(request.new_password)
    await db.users.update_one(
        {"id": employee["user_id"]},
        {"$set": {"password": new_password_hash, "must_change_password": True}}
    )
    
    # Create notification
    notification_doc = {
        "id": str(uuid.uuid4()),
        "user_id": employee["user_id"],
        "title": "Palavra-passe Redefinida",
        "message": "A sua palavra-passe foi redefinida pelo administrador. Por favor, altere-a no próximo acesso.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.notifications.insert_one(notification_doc)
    
    return {"message": "Palavra-passe redefinida com sucesso. O colaborador deverá alterá-la no próximo acesso."}

# ==================== TIME RECORD ROUTES ====================

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre dois pontos GPS (fórmula de Haversine)."""
    R = 6371000.0  # raio da Terra em metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

@api_router.post("/time-records", response_model=TimeRecordResponse)
async def create_time_record(record: TimeRecordCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "colaborador":
        raise HTTPException(status_code=403, detail="Apenas colaboradores podem registar ponto")

    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")

    # Validate record type
    if record.record_type not in ["entrada", "saida"]:
        raise HTTPException(status_code=400, detail="Tipo de registo inválido. Use 'entrada' ou 'saida'")

    # Regra: alternar entrada/saída — não pode repetir o mesmo tipo seguido.
    # (Se deu entrada, o próximo tem de ser saída, e vice-versa.)
    last_record = await db.time_records.find_one(
        {"employee_id": employee_id}, {"_id": 0, "record_type": 1}, sort=[("time", -1)]
    )
    last_type = last_record["record_type"] if last_record else None
    if record.record_type == "entrada" and last_type == "entrada":
        raise HTTPException(status_code=400, detail="Já registou a entrada. A seguir só pode registar a saída.")
    if record.record_type == "saida" and last_type != "entrada":
        raise HTTPException(status_code=400, detail="Ainda não tem uma entrada em aberto. Registe primeiro a entrada.")

    # Cerca geográfica: se o local do colaborador tiver posição e raio definidos,
    # o ponto só é aceite se ele estiver dentro do raio.
    # Colaboradores isentos (ex.: que rodam por várias lojas) não são validados.
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if employee and employee.get("location_id") and not employee.get("geofence_exempt"):
        location = await db.locations.find_one({"id": employee["location_id"]}, {"_id": 0})
        if location and location.get("latitude") is not None and location.get("longitude") is not None and location.get("geofence_radius"):
            radius = location["geofence_radius"]
            if record.latitude is None or record.longitude is None:
                raise HTTPException(
                    status_code=400,
                    detail="Ative a localização no telemóvel para poder registar o ponto neste local."
                )
            distance = haversine_meters(record.latitude, record.longitude, location["latitude"], location["longitude"])
            # Margem para a imprecisão do GPS (sobretudo Safari/iOS em precisão
            # normal, que pode reportar centenas de metros de erro). Aceita-se se,
            # descontando a precisão reportada (com limite), ainda estiver no raio.
            accuracy_slack = min(record.accuracy or 0, max(radius, 150))
            if distance - accuracy_slack > radius:
                raise HTTPException(
                    status_code=403,
                    detail=f"Está a {int(distance)} m do local de trabalho (limite {radius} m). Aproxime-se para registar o ponto."
                )

    record_id = str(uuid.uuid4())
    record_doc = {
        "id": record_id,
        "employee_id": employee_id,
        "record_type": record.record_type,
        "time": datetime.now(timezone.utc).isoformat(),
        "corrected": False,
        "correction_history": [],
        "latitude": record.latitude,
        "longitude": record.longitude,
        "accuracy": record.accuracy
    }
    await db.time_records.insert_one(record_doc)

    return TimeRecordResponse(**record_doc)

@api_router.get("/time-records", response_model=List[TimeRecordResponse])
async def get_time_records(
    employee_id: Optional[str] = None,
    company_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    
    # Colaboradores can only see their own records
    if current_user.get("role") == "colaborador":
        query["employee_id"] = current_user.get("employee_id")
    elif employee_id:
        query["employee_id"] = employee_id
    
    # Filter by company (admin ou gestor)
    if company_id and current_user.get("role") in MANAGER_ROLES:
        employees = await db.employees.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(1000)
        emp_ids = [e["id"] for e in employees]
        query["employee_id"] = {"$in": emp_ids}
    
    # Date filters
    if start_date or end_date:
        query["time"] = {}
        if start_date:
            query["time"]["$gte"] = start_date
        if end_date:
            query["time"]["$lte"] = end_date
    
    records = await db.time_records.find(query, {"_id": 0}).sort("time", -1).to_list(1000)
    
    # Get employee names
    for rec in records:
        employee = await db.employees.find_one({"id": rec["employee_id"]}, {"_id": 0})
        rec["employee_name"] = employee["name"] if employee else None
    
    return [TimeRecordResponse(**r) for r in records]

@api_router.put("/time-records/{record_id}/correct", response_model=TimeRecordResponse)
async def correct_time_record(record_id: str, correction: TimeRecordCorrection, current_user: dict = Depends(admin_required)):
    record = await db.time_records.find_one({"id": record_id}, {"_id": 0})
    if not record:
        raise HTTPException(status_code=404, detail="Registo não encontrado")
    
    # Add to correction history
    correction_entry = {
        "previous_time": record["time"],
        "new_time": correction.time,
        "justification": correction.justification,
        "corrected_by": current_user["user_id"],
        "corrected_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.time_records.update_one(
        {"id": record_id},
        {
            "$set": {"time": correction.time, "corrected": True},
            "$push": {"correction_history": correction_entry}
        }
    )
    
    # Create notification for employee
    employee = await db.employees.find_one({"id": record["employee_id"]}, {"_id": 0})
    if employee:
        notification_doc = {
            "id": str(uuid.uuid4()),
            "user_id": employee["user_id"],
            "title": "Ponto Corrigido",
            "message": f"O seu registo de ponto foi corrigido. Motivo: {correction.justification}",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.notifications.insert_one(notification_doc)
    
    updated = await db.time_records.find_one({"id": record_id}, {"_id": 0})
    updated["employee_name"] = employee["name"] if employee else None
    return TimeRecordResponse(**updated)

@api_router.get("/reports/worked-hours")
async def worked_hours_report(
    company_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(admin_manager_required)
):
    """Relatório de horas trabalhadas por colaborador (pares entrada->saída)."""

    def parse_dt(s: str) -> datetime:
        # Aceita tanto '...Z' como '...+00:00'
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    # Conjunto de colaboradores a considerar
    emp_query = {}
    if company_id:
        emp_query["company_id"] = company_id
    if employee_id:
        emp_query["id"] = employee_id
    employees = await db.employees.find(emp_query, {"_id": 0}).to_list(1000)
    emp_map = {e["id"]: e for e in employees}
    if not emp_map:
        return []

    # Registos de ponto no período
    rec_query = {"employee_id": {"$in": list(emp_map.keys())}}
    if start_date or end_date:
        rec_query["time"] = {}
        if start_date:
            rec_query["time"]["$gte"] = start_date
        if end_date:
            rec_query["time"]["$lte"] = end_date
    records = await db.time_records.find(rec_query, {"_id": 0}).sort("time", 1).to_list(100000)

    by_emp = {}
    for r in records:
        by_emp.setdefault(r["employee_id"], []).append(r)

    results = []
    for emp_id, emp in emp_map.items():
        recs = by_emp.get(emp_id, [])
        total_seconds = 0.0
        days = set()
        pending_in = None
        incomplete = False
        for r in recs:
            t = parse_dt(r["time"])
            days.add(t.date().isoformat())
            if r["record_type"] == "entrada":
                if pending_in is not None:
                    incomplete = True  # duas entradas seguidas sem saída
                pending_in = t
            elif r["record_type"] == "saida":
                if pending_in is not None:
                    delta = (t - pending_in).total_seconds()
                    if delta > 0:
                        total_seconds += delta
                    pending_in = None
                else:
                    incomplete = True  # saída sem entrada
        if pending_in is not None:
            incomplete = True  # entrada sem saída no fim do período

        results.append({
            "employee_id": emp_id,
            "employee_name": emp.get("name"),
            "total_hours": round(total_seconds / 3600, 2),
            "days_worked": len(days),
            "incomplete": incomplete,
        })

    results.sort(key=lambda x: (x["employee_name"] or "").lower())
    return results

# ==================== WORK SCHEDULE ROUTES ====================

@api_router.post("/schedules", response_model=WorkScheduleTemplateResponse)
async def create_schedule_template(template: WorkScheduleTemplateCreate, current_user: dict = Depends(admin_manager_required)):
    template_id = str(uuid.uuid4())
    template_doc = {
        "id": template_id,
        "name": template.name,
        "work_days": template.work_days,
        "start_time": template.start_time,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.work_schedule_templates.insert_one(template_doc)
    return WorkScheduleTemplateResponse(**template_doc)

@api_router.get("/schedules", response_model=List[WorkScheduleTemplateResponse])
async def get_schedule_templates(current_user: dict = Depends(admin_manager_required)):
    templates = await db.work_schedule_templates.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [WorkScheduleTemplateResponse(**t) for t in templates]

@api_router.get("/me/schedule")
async def get_my_schedule(current_user: dict = Depends(get_current_user)):
    """Escala ativa do próprio colaborador (dias de trabalho + hora de início),
    para o lembrete de ponto no app. Devolve vazio se não tiver escala."""
    empty = {"work_days": [], "start_time": None, "template_name": None}
    employee_id = current_user.get("employee_id")
    if not employee_id:
        return empty
    assignments = await db.work_schedule_assignments.find(
        {"employee_id": employee_id}, {"_id": 0}
    ).sort("start_date", 1).to_list(200)
    if not assignments:
        return empty
    today = datetime.now(LISBON_TZ).date()
    assignment = find_schedule_assignment(assignments, today) or assignments[-1]
    tpl = await db.work_schedule_templates.find_one(
        {"id": assignment.get("template_id")}, {"_id": 0}
    )
    work_days = assignment.get("work_days") or (tpl.get("work_days", []) if tpl else [])
    return {
        "work_days": work_days or [],
        "start_time": tpl.get("start_time") if tpl else None,
        "template_name": tpl.get("name") if tpl else None,
    }

@api_router.post("/schedules/assign", response_model=WorkScheduleAssignmentResponse)
async def assign_schedule(assignment: WorkScheduleAssignmentCreate, current_user: dict = Depends(admin_manager_required)):
    employee = await db.employees.find_one({"id": assignment.employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    template = await db.work_schedule_templates.find_one({"id": assignment.template_id}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=404, detail="Escala não encontrada")

    try:
        start_dt = datetime.fromisoformat(assignment.start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Data de início inválida")

    end_dt = None
    if assignment.end_date:
        try:
            end_dt = datetime.fromisoformat(assignment.end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Data de fim inválida")

    if end_dt and start_dt > end_dt:
        raise HTTPException(status_code=400, detail="Data de início não pode ser posterior à data de fim")

    existing_assignments = await db.work_schedule_assignments.find(
        {"employee_id": employee["id"]},
        {"_id": 0}
    ).to_list(200)

    new_start = start_dt.date()
    new_end = end_dt.date() if end_dt else None

    for existing in existing_assignments:
        existing_start = datetime.fromisoformat(existing["start_date"]).date()
        existing_end_raw = existing.get("end_date")
        existing_end = datetime.fromisoformat(existing_end_raw).date() if existing_end_raw else None
        existing_end_cmp = existing_end or date.max
        new_end_cmp = new_end or date.max

        if new_start <= existing_end_cmp and new_end_cmp >= existing_start:
            raise HTTPException(status_code=400, detail="Já existe uma escala ativa nesse período")

    assignment_id = str(uuid.uuid4())
    assignment_doc = {
        "id": assignment_id,
        "employee_id": employee["id"],
        "template_id": template["id"],
        "work_days": template.get("work_days", []),
        "start_date": assignment.start_date,
        "end_date": assignment.end_date,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    await db.work_schedule_assignments.insert_one(assignment_doc)

    return WorkScheduleAssignmentResponse(
        **assignment_doc,
        employee_name=employee["name"],
        template_name=template["name"]
    )

@api_router.get("/schedules/assignments", response_model=List[WorkScheduleAssignmentResponse])
async def get_schedule_assignments(employee_id: Optional[str] = None, current_user: dict = Depends(admin_manager_required)):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id

    assignments = await db.work_schedule_assignments.find(query, {"_id": 0}).sort("start_date", -1).to_list(200)

    for assignment in assignments:
        employee = await db.employees.find_one({"id": assignment["employee_id"]}, {"_id": 0})
        template = await db.work_schedule_templates.find_one({"id": assignment["template_id"]}, {"_id": 0})
        assignment["employee_name"] = employee["name"] if employee else None
        assignment["template_name"] = template["name"] if template else None
        if not assignment.get("work_days") and template:
            assignment["work_days"] = template.get("work_days", [])

    return [WorkScheduleAssignmentResponse(**a) for a in assignments]

@api_router.put("/schedules/{template_id}", response_model=WorkScheduleTemplateResponse)
async def update_schedule_template(template_id: str, template: WorkScheduleTemplateCreate, current_user: dict = Depends(admin_manager_required)):
    result = await db.work_schedule_templates.update_one(
        {"id": template_id},
        {"$set": {"name": template.name, "work_days": template.work_days, "start_time": template.start_time}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Escala não encontrada")
    # Manter os dias coerentes nas atribuições que usam esta escala
    await db.work_schedule_assignments.update_many(
        {"template_id": template_id},
        {"$set": {"work_days": template.work_days}}
    )
    updated = await db.work_schedule_templates.find_one({"id": template_id}, {"_id": 0})
    return WorkScheduleTemplateResponse(**updated)

@api_router.delete("/schedules/assignments/{assignment_id}")
async def delete_schedule_assignment(assignment_id: str, current_user: dict = Depends(admin_manager_required)):
    result = await db.work_schedule_assignments.delete_one({"id": assignment_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Atribuição não encontrada")
    return {"message": "Atribuição removida com sucesso"}

@api_router.delete("/schedules/{template_id}")
async def delete_schedule_template(template_id: str, current_user: dict = Depends(admin_manager_required)):
    result = await db.work_schedule_templates.delete_one({"id": template_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Escala não encontrada")
    # Remove também as atribuições desta escala
    await db.work_schedule_assignments.delete_many({"template_id": template_id})
    return {"message": "Escala eliminada com sucesso"}

# ==================== LEAVE REQUEST ROUTES ====================

@api_router.post("/admin/leave", response_model=LeaveRequestResponse)
async def create_admin_leave(request: AdminLeaveCreate, current_user: dict = Depends(admin_manager_required)):
    """
    Create leave directly by admin/manager without approval flow.
    """
    employee = await db.employees.find_one({"id": request.user_id}, {"_id": 0})
    if not employee:
        employee = await db.employees.find_one({"user_id": request.user_id}, {"_id": 0})

    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    try:
        start_dt = datetime.fromisoformat(request.start_date)
        end_dt = datetime.fromisoformat(request.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Datas inválidas. Use o formato AAAA-MM-DD")

    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="Data de início não pode ser posterior à data de fim")

    overlapping = await db.leave_requests.find_one(
        {
            "employee_id": employee["id"],
            "status": {"$ne": "recusado"},
            "start_date": {"$lte": request.end_date},
            "end_date": {"$gte": request.start_date}
        },
        {"_id": 0}
    )

    if overlapping:
        raise HTTPException(status_code=400, detail="Já existe um registo de férias/ausência nesse período")

    created_by_role = "gestor" if current_user.get("role") == "gerente" else "admin"

    request_id = str(uuid.uuid4())
    counted_days = await calculate_leave_counted_days(employee["id"], request.start_date, request.end_date)
    audit_log = [build_audit_entry("criado_manual", current_user)]
    request_doc = {
        "id": request_id,
        "employee_id": employee["id"],
        "leave_type": request.leave_type,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "status": "aprovado",
        "observation": request.reason,
        "document_id": None,
        "admin_response": None,
        "created_by": created_by_role,
        "is_paid": request.is_paid,
        "counted_days": counted_days,
        "audit_log": audit_log,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    await db.leave_requests.insert_one(request_doc)

    return LeaveRequestResponse(**request_doc, employee_name=employee["name"])

@api_router.post("/leave-requests", response_model=LeaveRequestResponse)
async def create_leave_request(request: LeaveRequestCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["colaborador", "gerente"]:
        raise HTTPException(status_code=403, detail="Apenas colaboradores ou gestores podem criar pedidos")

    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")

    if not current_user.get("name"):
        user_doc = await db.users.find_one({"id": current_user.get("user_id")}, {"_id": 0, "name": 1, "role": 1})
        if user_doc:
            current_user["name"] = user_doc.get("name")
            current_user["role"] = user_doc.get("role", current_user.get("role"))
    valid_types = ["ferias", "falta", "doenca", "folga"]
    if request.leave_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Use: {', '.join(valid_types)}")

    request_id = str(uuid.uuid4())
    counted_days = await calculate_leave_counted_days(employee_id, request.start_date, request.end_date)
    audit_log = [build_audit_entry("criado", current_user)]
    request_doc = {
        "id": request_id,
        "employee_id": employee_id,
        "leave_type": request.leave_type,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "status": "pendente",
        "observation": request.observation,
        "document_id": None,
        "admin_response": None,
        "created_by": "gestor" if current_user.get("role") == "gerente" else "colaborador",
        "is_paid": None,
        "counted_days": counted_days,
        "audit_log": audit_log,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.leave_requests.insert_one(request_doc)

    # Notify admins
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    admins = await db.users.find({"role": "admin"}, {"_id": 0}).to_list(100)

    leave_type_labels = {"ferias": "Férias", "falta": "Falta", "doenca": "Doença", "folga": "Folga"}

    for admin in admins:
        notification_doc = {
            "id": str(uuid.uuid4()),
            "user_id": admin["id"],
            "title": "Novo Pedido de Ausência",
            "message": f"{employee['name'] if employee else 'Colaborador'} solicitou {leave_type_labels.get(request.leave_type, request.leave_type)}",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.notifications.insert_one(notification_doc)

    # Aviso por email aos admins/gestores (não bloqueia se o email falhar)
    await notify_managers_of_leave_request(
        employee["name"] if employee else "Colaborador",
        request.leave_type,
        request.start_date,
        request.end_date,
        request.observation
    )

    return LeaveRequestResponse(**request_doc, employee_name=employee["name"] if employee else None)

@api_router.get("/leave-requests", response_model=List[LeaveRequestResponse])
async def get_leave_requests(
    employee_id: Optional[str] = None,
    company_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    
    # Colaboradores can only see their own requests
    if current_user.get("role") == "colaborador":
        query["employee_id"] = current_user.get("employee_id")
    elif employee_id:
        query["employee_id"] = employee_id
    
    # Filter by company (admin ou gestor)
    if company_id and current_user.get("role") in MANAGER_ROLES:
        employees = await db.employees.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(1000)
        emp_ids = [e["id"] for e in employees]
        query["employee_id"] = {"$in": emp_ids}
    
    if status:
        query["status"] = status
    
    requests = await db.leave_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)

    # Get employee names
    for req in requests:
        employee = await db.employees.find_one({"id": req["employee_id"]}, {"_id": 0})
        req["employee_name"] = employee["name"] if employee else None
        req["counted_days"] = await calculate_leave_counted_days(
            req["employee_id"],
            req["start_date"],
            req["end_date"]
        )

    return [LeaveRequestResponse(**r) for r in requests]

class LeaveRequestResponseModel(BaseModel):
    status: str
    response: Optional[str] = None

class LeaveRequestUpdate(BaseModel):
    start_date: str = Field(alias="startDate")
    end_date: str = Field(alias="endDate")
    observation: Optional[str] = None

    model_config = {"populate_by_name": True}

@api_router.put("/leave-requests/{request_id}", response_model=LeaveRequestResponse)
async def update_leave_request(
    request_id: str,
    data: LeaveRequestUpdate,
    current_user: dict = Depends(admin_manager_required)
):
    leave_request = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not leave_request:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    try:
        start_dt = datetime.fromisoformat(data.start_date)
        end_dt = datetime.fromisoformat(data.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Datas inválidas. Use o formato AAAA-MM-DD")

    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="Data de início não pode ser posterior à data de fim")

    overlapping = await db.leave_requests.find_one(
        {
            "employee_id": leave_request["employee_id"],
            "id": {"$ne": request_id},
            "status": {"$ne": "recusado"},
            "start_date": {"$lte": data.end_date},
            "end_date": {"$gte": data.start_date}
        },
        {"_id": 0}
    )

    if overlapping:
        raise HTTPException(status_code=400, detail="Já existe um registo de férias/ausência nesse período")

    counted_days = await calculate_leave_counted_days(
        leave_request["employee_id"],
        data.start_date,
        data.end_date
    )

    audit_entry = build_audit_entry("editado", current_user)

    await db.leave_requests.update_one(
        {"id": request_id},
        {
            "$set": {
                "start_date": data.start_date,
                "end_date": data.end_date,
                "observation": data.observation,
                "counted_days": counted_days
            },
            "$push": {"audit_log": audit_entry}
        }
    )

    updated = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    employee = await db.employees.find_one({"id": updated["employee_id"]}, {"_id": 0})
    updated["employee_name"] = employee["name"] if employee else None
    updated["counted_days"] = await calculate_leave_counted_days(
        updated["employee_id"],
        updated["start_date"],
        updated["end_date"]
    )

    return LeaveRequestResponse(**updated)

@api_router.put("/leave-requests/{request_id}/respond")
async def respond_leave_request(
    request_id: str,
    data: LeaveRequestResponseModel,
    current_user: dict = Depends(admin_manager_required)
):
    if data.status not in ["aprovado", "recusado"]:
        raise HTTPException(status_code=400, detail="Status inválido. Use 'aprovado' ou 'recusado'")
    
    leave_request = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not leave_request:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    audit_entry = build_audit_entry(
        "aprovado" if data.status == "aprovado" else "recusado",
        current_user
    )

    await db.leave_requests.update_one(
        {"id": request_id},
        {
            "$set": {"status": data.status, "admin_response": data.response},
            "$push": {"audit_log": audit_entry}
        }
    )
    
    # Notify employee
    employee = await db.employees.find_one({"id": leave_request["employee_id"]}, {"_id": 0})
    if employee:
        status_label = "aprovado" if data.status == "aprovado" else "recusado"
        notification_doc = {
            "id": str(uuid.uuid4()),
            "user_id": employee["user_id"],
            "title": f"Pedido {status_label.capitalize()}",
            "message": f"O seu pedido de ausência foi {status_label}." + (f" Resposta: {data.response}" if data.response else ""),
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.notifications.insert_one(notification_doc)

        # Email ao colaborador com a decisão (não bloqueia se o email falhar)
        type_label = "férias" if leave_request.get("leave_type") == "ferias" else "ausência"
        await notify_employee_of_leave_decision(
            employee.get("email"),
            employee.get("name"),
            status_label,
            type_label,
            leave_request.get("start_date"),
            leave_request.get("end_date"),
            data.response,
        )

    updated = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    updated["employee_name"] = employee["name"] if employee else None
    updated["counted_days"] = await calculate_leave_counted_days(
        updated["employee_id"],
        updated["start_date"],
        updated["end_date"]
    )

    return LeaveRequestResponse(**updated)

@api_router.delete("/leave-requests/{request_id}")
async def delete_leave_request(request_id: str, current_user: dict = Depends(admin_manager_required)):
    """Eliminar um pedido de férias/ausência (ex.: limpar os recusados).

    Os dias de férias usados são recalculados automaticamente a partir dos
    pedidos aprovados, por isso não é preciso ajustar nada manualmente.
    """
    leave_request = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not leave_request:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    await db.leave_requests.delete_one({"id": request_id})
    return {"message": "Pedido eliminado com sucesso"}

# ==================== FOLDER ROUTES ====================

@api_router.post("/folders", response_model=FolderResponse)
async def create_folder(folder: FolderCreate, current_user: dict = Depends(admin_required)):
    # Verify employee exists
    employee = await db.employees.find_one({"id": folder.employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    folder_id = str(uuid.uuid4())
    folder_doc = {
        "id": folder_id,
        "name": folder.name,
        "employee_id": folder.employee_id,
        "allow_employee_upload": folder.allow_employee_upload,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.folders.insert_one(folder_doc)
    return FolderResponse(**folder_doc)

@api_router.get("/folders", response_model=List[FolderResponse])
async def get_folders(employee_id: str, current_user: dict = Depends(get_current_user)):
    # Colaboradores can only see their own folders
    if current_user.get("role") == "colaborador" and current_user.get("employee_id") != employee_id:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    folders = await db.folders.find({"employee_id": employee_id}, {"_id": 0}).to_list(100)
    return [FolderResponse(**f) for f in folders]

@api_router.put("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(folder_id: str, folder: FolderCreate, current_user: dict = Depends(admin_required)):
    result = await db.folders.update_one(
        {"id": folder_id},
        {"$set": {"name": folder.name, "allow_employee_upload": folder.allow_employee_upload}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    
    updated = await db.folders.find_one({"id": folder_id}, {"_id": 0})
    return FolderResponse(**updated)

@api_router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current_user: dict = Depends(admin_required)):
    folder = await db.folders.find_one({"id": folder_id}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    
    # Delete documents in folder
    docs = await db.documents.find({"folder_id": folder_id}, {"_id": 0}).to_list(100)
    for doc in docs:
        file_path = Path(doc["file_path"])
        if file_path.exists():
            file_path.unlink()
    await db.documents.delete_many({"folder_id": folder_id})
    
    await db.folders.delete_one({"id": folder_id})
    return {"message": "Pasta eliminada com sucesso"}

# ==================== DOCUMENT ROUTES ====================

@api_router.post("/documents", response_model=DocumentResponse)
async def upload_document(
    folder_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    folder = await db.folders.find_one({"id": folder_id}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    
    # Check permissions
    if current_user.get("role") == "colaborador":
        if current_user.get("employee_id") != folder["employee_id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")
        if not folder["allow_employee_upload"]:
            raise HTTPException(status_code=403, detail="Não tem permissão para enviar documentos para esta pasta")
    
    # Save file
    file_id = str(uuid.uuid4())
    file_extension = Path(file.filename).suffix
    file_name = f"{file_id}{file_extension}"
    file_path = UPLOAD_DIR / file_name
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Get uploader info
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    
    doc_id = str(uuid.uuid4())
    doc_record = {
        "id": doc_id,
        "name": file.filename,
        "folder_id": folder_id,
        "employee_id": folder["employee_id"],
        "uploaded_by": current_user["user_id"],
        "uploaded_by_name": user["name"] if user else None,
        "file_path": str(file_path),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.documents.insert_one(doc_record)
    
    # Notify if a manager uploaded for the employee
    if current_user.get("role") in MANAGER_ROLES:
        employee = await db.employees.find_one({"id": folder["employee_id"]}, {"_id": 0})
        if employee:
            notification_doc = {
                "id": str(uuid.uuid4()),
                "user_id": employee["user_id"],
                "title": "Novo Documento",
                "message": f"Foi adicionado um novo documento na pasta '{folder['name']}'",
                "read": False,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            await db.notifications.insert_one(notification_doc)
    
    return DocumentResponse(**doc_record, folder_name=folder["name"])

@api_router.get("/documents", response_model=List[DocumentResponse])
async def get_documents(
    folder_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    
    if folder_id:
        folder = await db.folders.find_one({"id": folder_id}, {"_id": 0})
        if not folder:
            raise HTTPException(status_code=404, detail="Pasta não encontrada")
        
        # Check permissions
        if current_user.get("role") == "colaborador" and current_user.get("employee_id") != folder["employee_id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")
        
        query["folder_id"] = folder_id
    elif employee_id:
        # Check permissions
        if current_user.get("role") == "colaborador" and current_user.get("employee_id") != employee_id:
            raise HTTPException(status_code=403, detail="Acesso negado")
        query["employee_id"] = employee_id
    elif current_user.get("role") == "colaborador":
        query["employee_id"] = current_user.get("employee_id")
    
    documents = await db.documents.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    
    # Get folder names
    for doc in documents:
        folder = await db.folders.find_one({"id": doc["folder_id"]}, {"_id": 0})
        doc["folder_name"] = folder["name"] if folder else None
    
    return [DocumentResponse(**d) for d in documents]

@api_router.get("/documents/{document_id}/download")
async def download_document(document_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    
    # Check permissions
    if current_user.get("role") == "colaborador" and current_user.get("employee_id") != doc["employee_id"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    file_path = Path(doc["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado")
    
    return FileResponse(file_path, filename=doc["name"])

@api_router.delete("/documents/{document_id}")
async def delete_document(document_id: str, current_user: dict = Depends(admin_required)):
    doc = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    
    # Delete file
    file_path = Path(doc["file_path"])
    if file_path.exists():
        file_path.unlink()
    
    await db.documents.delete_one({"id": document_id})
    return {"message": "Documento eliminado com sucesso"}

# ==================== NOTIFICATION ROUTES ====================

@api_router.get("/notifications", response_model=List[NotificationResponse])
async def get_notifications(current_user: dict = Depends(get_current_user)):
    notifications = await db.notifications.find(
        {"user_id": current_user["user_id"]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return [NotificationResponse(**n) for n in notifications]

@api_router.put("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.notifications.update_one(
        {"id": notification_id, "user_id": current_user["user_id"]},
        {"$set": {"read": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notificação não encontrada")
    return {"message": "Notificação marcada como lida"}

@api_router.put("/notifications/read-all")
async def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    await db.notifications.update_many(
        {"user_id": current_user["user_id"]},
        {"$set": {"read": True}}
    )
    return {"message": "Todas as notificações marcadas como lidas"}

# ==================== DASHBOARD ROUTES ====================

@api_router.get("/dashboard/admin")
async def get_admin_dashboard(company_id: Optional[str] = None, current_user: dict = Depends(admin_manager_required)):
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    # Total employees
    total_employees = await db.employees.count_documents(query)
    
    # Total companies
    total_companies = await db.companies.count_documents({})
    
    # Pending requests
    pending_query = {"status": "pendente"}
    if company_id:
        employees = await db.employees.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(1000)
        emp_ids = [e["id"] for e in employees]
        pending_query["employee_id"] = {"$in": emp_ids}
    pending_requests = await db.leave_requests.count_documents(pending_query)
    
    # "Hoje" no fuso de Portugal (não em UTC), senão a hora/o dia ficam errados.
    now_lis = datetime.now(LISBON_TZ)
    today_date = now_lis.date()
    today_str = today_date.isoformat()
    # Instante UTC da meia-noite de hoje em Lisboa: limite inferior para
    # selecionar os registos de ponto (guardados em UTC).
    day_start_utc = now_lis.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    today_query = {"time": {"$gte": day_start_utc}}
    if company_id:
        today_query["employee_id"] = {"$in": emp_ids}
    today_records = await db.time_records.count_documents(today_query)
    
    # Employees by company
    companies = await db.companies.find({}, {"_id": 0}).to_list(100)
    employees_by_company = []
    for company in companies:
        count = await db.employees.count_documents({"company_id": company["id"]})
        employees_by_company.append({"company": company["name"], "count": count})
    
    # Recent requests
    recent_query = {}
    if company_id:
        recent_query["employee_id"] = {"$in": emp_ids}
    recent_requests = await db.leave_requests.find(recent_query, {"_id": 0}).sort("created_at", -1).to_list(5)
    for req in recent_requests:
        employee = await db.employees.find_one({"id": req["employee_id"]}, {"_id": 0})
        req["employee_name"] = employee["name"] if employee else None
    
    # ===== Enriquecimento: quem está hoje + aniversários =====
    emp_filter = {"company_id": company_id} if company_id else {}
    all_emps = await db.employees.find(
        emp_filter,
        {"_id": 0, "id": 1, "name": 1, "photo": 1, "birth_date": 1,
         "position": 1, "location_id": 1, "company_id": 1},
    ).to_list(2000)
    emp_id_set = {e["id"] for e in all_emps}
    emp_by_id = {e["id"]: e for e in all_emps}

    # Mapas de apoio para enriquecer os cartões (poucos queries, sem loops)
    locations_all = await db.locations.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    location_name_by_id = {loc["id"]: loc.get("name") for loc in locations_all}
    companies_all = await db.companies.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(200)
    company_name_by_id = {c["id"]: c.get("name") for c in companies_all}

    # (today_date / today_str já calculados acima, no fuso de Lisboa)

    # De férias/ausência hoje (aprovado e cobre hoje)
    on_leave_ids = set()
    leave_type_by_emp = {}
    leave_end_by_emp = {}
    leaves_today = await db.leave_requests.find(
        {"status": "aprovado", "start_date": {"$lte": today_str}, "end_date": {"$gte": today_str}},
        {"_id": 0, "employee_id": 1, "leave_type": 1, "end_date": 1}
    ).to_list(2000)
    for lv in leaves_today:
        if lv["employee_id"] in emp_id_set:
            on_leave_ids.add(lv["employee_id"])
            # férias > folga > ausência (prioridade se houver mais do que um)
            existing = leave_type_by_emp.get(lv["employee_id"])
            if existing != "ferias":
                leave_type_by_emp[lv["employee_id"]] = lv.get("leave_type")
                leave_end_by_emp[lv["employee_id"]] = lv.get("end_date")

    # A trabalhar agora (último registo de hoje = entrada)
    rec_q = {"time": {"$gte": day_start_utc}}
    if company_id:
        rec_q["employee_id"] = {"$in": list(emp_id_set)}
    records_today = await db.time_records.find(
        rec_q, {"_id": 0, "employee_id": 1, "record_type": 1, "time": 1}
    ).sort("time", 1).to_list(5000)
    last_type = {}
    first_entry_by_emp = {}  # hora "HH:MM" da PRIMEIRA entrada de hoje
    for r in records_today:
        eid = r["employee_id"]
        last_type[eid] = r["record_type"]
        if r["record_type"] == "entrada" and eid not in first_entry_by_emp:
            t = r.get("time")
            if t:
                try:
                    _dt = datetime.fromisoformat(t)
                    if _dt.tzinfo is None:
                        _dt = _dt.replace(tzinfo=timezone.utc)
                    first_entry_by_emp[eid] = _dt.astimezone(LISBON_TZ).strftime("%H:%M")
                except (ValueError, TypeError):
                    first_entry_by_emp[eid] = None
    working_ids = [eid for eid, t in last_type.items() if t == "entrada" and eid not in on_leave_ids and eid in emp_id_set]

    # Atribuições de escala por colaborador (pré-carregadas, sem query por pessoa)
    assignments_all = await db.work_schedule_assignments.find(
        {"employee_id": {"$in": list(emp_id_set)}}, {"_id": 0}
    ).to_list(5000)
    # Agrupar atribuições por colaborador (dict simples, sem defaultdict)
    assignments_by_emp = {}
    for a in assignments_all:
        assignments_by_emp.setdefault(a["employee_id"], []).append(a)

    # Mapa de templates (work_days + nome), para resolver a escala ativa hoje
    template_ids = {a.get("template_id") for a in assignments_all if a.get("template_id")}
    templates_by_id = {}
    if template_ids:
        templates = await db.work_schedule_templates.find(
            {"id": {"$in": list(template_ids)}}, {"_id": 0, "id": 1, "name": 1, "work_days": 1}
        ).to_list(500)
        templates_by_id = {t["id"]: t for t in templates}

    def _schedule_today(eid):
        """Escala ativa hoje. Devolve (work_days, name) com a atribuição ativa,
        ou (None, None) se não houver atribuição a cobrir hoje. work_days pode ser
        lista vazia se a atribuição não definir dias."""
        assignment = find_schedule_assignment(assignments_by_emp.get(eid, []), today_date)
        if not assignment:
            return None, None
        tpl = templates_by_id.get(assignment.get("template_id"), {})
        work_days = assignment.get("work_days") or tpl.get("work_days") or []
        return list(work_days), tpl.get("name")

    def _mini(eid):
        e = emp_by_id.get(eid, {})
        sched_days, sched_name = _schedule_today(eid)
        item = {
            "id": eid,
            "name": e.get("name"),
            "photo": e.get("photo"),
            "position": e.get("position"),
            "location_name": location_name_by_id.get(e.get("location_id")),
            "company_name": company_name_by_id.get(e.get("company_id")),
            # Para o frontend: só consideramos "tem escala" se houver dias definidos
            "schedule_days": sched_days if sched_days else None,
            "schedule_name": sched_name if sched_days else None,
        }
        if eid in working_ids:
            item["since"] = first_entry_by_emp.get(eid)
        if eid in on_leave_ids:
            item["until"] = leave_end_by_emp.get(eid)
        return item

    vacation_ids = [eid for eid in on_leave_ids if leave_type_by_emp.get(eid) == "ferias"]
    dayoff_ids = [eid for eid in on_leave_ids if leave_type_by_emp.get(eid) == "folga"]
    absent_ids = [eid for eid in on_leave_ids if leave_type_by_emp.get(eid) not in ("ferias", "folga")]

    # Folga pela escala: tem escala ativa hoje mas hoje não é dia de trabalho
    today_weekday = today_date.weekday()  # 0=Seg ... 5=Sáb, 6=Dom
    schedule_dayoff_ids = []
    for eid in emp_id_set:
        # Ausência aprovada e "a trabalhar" têm prioridade
        if eid in on_leave_ids or eid in working_ids:
            continue
        sched_days, _ = _schedule_today(eid)
        if sched_days is None:
            continue
        if today_weekday not in sched_days:
            schedule_dayoff_ids.append(eid)

    # Juntar folga por pedido + folga por escala, sem duplicar
    dayoff_all = list(dayoff_ids)
    for eid in schedule_dayoff_ids:
        if eid not in dayoff_all:
            dayoff_all.append(eid)

    whos_in = {
        "working": [_mini(eid) for eid in working_ids[:18]],
        "vacation": [_mini(eid) for eid in vacation_ids[:18]],
        "dayoff": [_mini(eid) for eid in dayoff_all[:18]],
        "absent": [_mini(eid) for eid in absent_ids[:18]],
        "on_leave": [_mini(eid) for eid in list(on_leave_ids)[:18]],
    }

    # Aniversários nos próximos 30 dias
    birthdays = []
    for e in all_emps:
        bd = e.get("birth_date")
        if not bd:
            continue
        try:
            d = datetime.fromisoformat(bd).date()
            try:
                nb = d.replace(year=today_date.year)
            except ValueError:
                nb = d.replace(year=today_date.year, day=28)  # 29 fev
            if nb < today_date:
                try:
                    nb = d.replace(year=today_date.year + 1)
                except ValueError:
                    nb = d.replace(year=today_date.year + 1, day=28)
            days = (nb - today_date).days
            if days <= 30:
                birthdays.append({
                    "name": e.get("name"),
                    "photo": e.get("photo"),
                    "position": e.get("position"),
                    "company_name": company_name_by_id.get(e.get("company_id")),
                    "location_name": location_name_by_id.get(e.get("location_id")),
                    "date": nb.isoformat(),
                    "days_until": days,
                })
        except ValueError:
            continue
    birthdays.sort(key=lambda x: x["days_until"])
    birthdays = birthdays[:6]

    # Próximas férias: pedidos aprovados que começam depois de hoje
    upcoming_leaves = []
    q = {"status": "aprovado", "leave_type": "ferias", "start_date": {"$gt": today_str}}
    if company_id:
        q["employee_id"] = {"$in": list(emp_id_set)}
    rows = await db.leave_requests.find(q, {"_id": 0}).sort("start_date", 1).to_list(30)
    for lv in rows:
        emp = emp_by_id.get(lv["employee_id"])
        if not emp:  # fora do scope da empresa
            continue
        start = datetime.fromisoformat(lv["start_date"]).date()
        days_until = (start - today_date).days
        upcoming_leaves.append({
            "employee_name": emp.get("name"),
            "photo": emp.get("photo"),
            "position": emp.get("position"),
            "company_name": company_name_by_id.get(emp.get("company_id")),
            "location_name": location_name_by_id.get(emp.get("location_id")),
            "leave_type": lv.get("leave_type"),
            "start_date": lv["start_date"],
            "end_date": lv["end_date"],
            "days_until": days_until,
        })
    upcoming_leaves = upcoming_leaves[:6]

    return {
        "total_employees": total_employees,
        "total_companies": total_companies,
        "pending_requests": pending_requests,
        "today_records": today_records,
        "on_leave_today": len(on_leave_ids),
        "working_now": len(working_ids),
        "employees_by_company": employees_by_company,
        "recent_requests": recent_requests,
        "whos_in": whos_in,
        "upcoming_birthdays": birthdays,
        "upcoming_leaves": upcoming_leaves,
    }

@api_router.get("/dashboard/employee")
async def get_employee_dashboard(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "colaborador":
        raise HTTPException(status_code=403, detail="Apenas para colaboradores")
    
    employee_id = current_user.get("employee_id")
    
    # Get employee info
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    
    # Calculate vacation days used and available
    if employee:
        vacation_used = await calculate_vacation_days_used(employee_id)
        employee["vacation_days_used"] = vacation_used
        employee["vacation_days_available"] = employee["vacation_days"] - vacation_used
    
    # Upcoming leave ("hoje" no fuso de Lisboa)
    today = datetime.now(LISBON_TZ).strftime("%Y-%m-%d")
    upcoming_leave = await db.leave_requests.find(
        {"employee_id": employee_id, "status": "aprovado", "start_date": {"$gte": today}},
        {"_id": 0}
    ).sort("start_date", 1).to_list(5)
    
    # Recent time records
    recent_records = await db.time_records.find(
        {"employee_id": employee_id},
        {"_id": 0}
    ).sort("time", -1).to_list(10)
    
    # Pending requests
    pending_requests = await db.leave_requests.find(
        {"employee_id": employee_id, "status": "pendente"},
        {"_id": 0}
    ).to_list(10)

    for request in pending_requests:
        request["counted_days"] = await calculate_leave_counted_days(
            employee_id,
            request["start_date"],
            request["end_date"]
        )
    
    # Unread notifications count
    unread_count = await db.notifications.count_documents(
        {"user_id": current_user["user_id"], "read": False}
    )
    
    return {
        "employee": employee,
        "upcoming_leave": upcoming_leave,
        "recent_records": recent_records,
        "pending_requests": pending_requests,
        "unread_notifications": unread_count
    }

@api_router.get("/calendar/leaves")
async def get_calendar_leaves(
    company_id: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {"status": "aprovado"}
    
    # Filter by company for managers
    if company_id and current_user.get("role") in MANAGER_ROLES:
        employees = await db.employees.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(1000)
        emp_ids = [e["id"] for e in employees]
        query["employee_id"] = {"$in": emp_ids}
    elif current_user.get("role") == "colaborador":
        query["employee_id"] = current_user.get("employee_id")
    
    # Date filtering
    if month and year:
        start = f"{year}-{month:02d}-01"
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"
        query["$or"] = [
            {"start_date": {"$gte": start, "$lt": end}},
            {"end_date": {"$gte": start, "$lt": end}},
            {"$and": [{"start_date": {"$lt": start}}, {"end_date": {"$gte": end}}]}
        ]
    
    leaves = await db.leave_requests.find(query, {"_id": 0}).to_list(1000)

    # Get employee names
    for leave in leaves:
        employee = await db.employees.find_one({"id": leave["employee_id"]}, {"_id": 0})
        leave["employee_name"] = employee["name"] if employee else None
        leave["counted_days"] = await calculate_leave_counted_days(
            leave["employee_id"],
            leave["start_date"],
            leave["end_date"]
        )

    return leaves

# ====================================================================
# ==================== FINANCEIRO (módulo Lisbonb) ===================
# ====================================================================
# Port do app financeiro (PHP) para o stack do RH. Coleções novas com
# prefixo `fin_` (aditivas, não afetam o RH). Multi-empresa POR PERTENÇA:
# cada utilizador vê apenas as empresas onde é membro (fin_company_members).
# Reutiliza o JWT do RH (get_current_user) e a coleção `users` para a equipa.
# Fase 2: empresas, unidades/lojas e equipa global. (Ref.: PORTING_GUIDE §3, §4, §10.1)

FIN_ROLES = ["owner", "partner", "accountant"]


def _fin_norm_nif(v):
    """NIF normalizado: apenas dígitos (ou None se vazio)."""
    if v is None:
        return None
    digits = re.sub(r"\D+", "", str(v))
    return digits or None


# ---------- Modelos Pydantic ----------

class FinCompanyCreate(BaseModel):
    name: str
    nif: Optional[str] = None

class FinCompanyResponse(BaseModel):
    id: str
    name: str
    nif: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[str] = None

class FinUnitCreate(BaseModel):
    company_id: str
    name: str
    type: Optional[str] = None
    sort: Optional[int] = 0

class FinUnitResponse(BaseModel):
    id: str
    company_id: str
    name: str
    type: Optional[str] = None
    sort: int = 0

# Fase 6 — corpo dos endpoints de ligação RH<->Financeiro
class FinLinkRhCompany(BaseModel):
    rh_company_id: Optional[str] = None

class FinLinkRhUnit(BaseModel):
    rh_location_id: Optional[str] = None

class FinTeamAdd(BaseModel):
    email: str
    role: str = "partner"

class FinRoleUpdate(BaseModel):
    role: str

class FinTeamMemberResponse(BaseModel):
    member_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: str


# ---------- Helpers de pertença (equivalentes a _bootstrap.php) ----------

async def fin_role_of(company_id: str, user_id: str):
    """Papel do utilizador nessa empresa (ou None)."""
    m = await db.fin_company_members.find_one(
        {"company_id": company_id, "user_id": user_id}, {"_id": 0, "role": 1}
    )
    return m["role"] if m else None

async def fin_require_member(company_id: str, current_user: dict):
    """Qualquer papel. Bloqueia acesso a empresas onde não é membro (anti-IDOR)."""
    role = await fin_role_of(company_id, current_user["user_id"])
    if not role:
        raise HTTPException(status_code=403, detail="Sem acesso a esta empresa.")
    return role

async def fin_require_editor(company_id: str, current_user: dict):
    """owner ou partner (contabilista = só leitura)."""
    role = await fin_require_member(company_id, current_user)
    if role not in ("owner", "partner"):
        raise HTTPException(status_code=403, detail="Sem permissão (acesso de leitura).")
    return role

async def fin_require_owner(company_id: str, current_user: dict):
    """Apenas o dono (ex.: gerir empresa/equipa)."""
    role = await fin_require_member(company_id, current_user)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Apenas o dono pode fazer isto.")
    return role

async def fin_owned_company_ids(user_id: str):
    """Ids das empresas de que ESTE utilizador é dono."""
    members = await db.fin_company_members.find(
        {"user_id": user_id, "role": "owner"}, {"_id": 0, "company_id": 1}
    ).to_list(500)
    return [m["company_id"] for m in members]

async def fin_member_company_ids(user_id: str):
    """Ids de TODAS as empresas onde o utilizador é membro (qualquer papel).
    Usado pelo modo 'Todas as empresas' (company_id="all") nas listagens."""
    members = await db.fin_company_members.find(
        {"user_id": user_id}, {"_id": 0, "company_id": 1}
    ).to_list(500)
    return [m["company_id"] for m in members]


# ---------- Empresas ----------

@api_router.get("/fin/companies", response_model=List[FinCompanyResponse])
async def fin_get_companies(current_user: dict = Depends(get_current_user)):
    """Empresas a que o utilizador tem acesso (com o seu papel)."""
    uid = current_user["user_id"]
    members = await db.fin_company_members.find(
        {"user_id": uid}, {"_id": 0, "company_id": 1, "role": 1}
    ).to_list(500)
    roles = {m["company_id"]: m["role"] for m in members}
    if not roles:
        return []
    companies = await db.fin_companies.find(
        {"id": {"$in": list(roles.keys())}}, {"_id": 0}
    ).to_list(500)
    companies.sort(key=lambda c: (c.get("name") or "").lower())
    return [FinCompanyResponse(**c, role=roles.get(c["id"])) for c in companies]

@api_router.post("/fin/companies", response_model=FinCompanyResponse)
async def fin_create_company(payload: FinCompanyCreate, current_user: dict = Depends(get_current_user)):
    """Cria empresa, torna o criador 'owner' e herda a equipa global do dono."""
    uid = current_user["user_id"]
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Indica o nome da empresa.")
    company_id = str(uuid.uuid4())
    doc = {
        "id": company_id,
        "name": name,
        "nif": _fin_norm_nif(payload.nif),
        "created_by": uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.fin_companies.insert_one(doc)
    await db.fin_company_members.insert_one(
        {"company_id": company_id, "user_id": uid, "role": "owner"}
    )
    # Herdar a equipa global do dono (acesso a todas as empresas dele)
    team = await db.fin_team_members.find(
        {"owner_id": uid}, {"_id": 0, "member_id": 1, "role": 1}
    ).to_list(500)
    for t in team:
        if t["member_id"] == uid:
            continue
        await db.fin_company_members.update_one(
            {"company_id": company_id, "user_id": t["member_id"]},
            {"$set": {"company_id": company_id, "user_id": t["member_id"], "role": t["role"]}},
            upsert=True,
        )
    return FinCompanyResponse(**doc, role="owner")

@api_router.put("/fin/companies/{company_id}", response_model=FinCompanyResponse)
async def fin_update_company(company_id: str, payload: FinCompanyCreate, current_user: dict = Depends(get_current_user)):
    await fin_require_owner(company_id, current_user)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Indica o nome da empresa.")
    await db.fin_companies.update_one(
        {"id": company_id}, {"$set": {"name": name, "nif": _fin_norm_nif(payload.nif)}}
    )
    updated = await db.fin_companies.find_one({"id": company_id}, {"_id": 0})
    return FinCompanyResponse(**updated, role="owner")

@api_router.delete("/fin/companies/{company_id}")
async def fin_delete_company(company_id: str, current_user: dict = Depends(get_current_user)):
    await fin_require_owner(company_id, current_user)
    await db.fin_units.delete_many({"company_id": company_id})
    await db.fin_company_members.delete_many({"company_id": company_id})
    await db.fin_companies.delete_one({"id": company_id})
    return {"message": "Empresa eliminada com sucesso"}


# ---------- Unidades / Lojas ----------

@api_router.get("/fin/units", response_model=List[FinUnitResponse])
async def fin_get_units(company_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Unidades das empresas do utilizador (filtro opcional por empresa)."""
    uid = current_user["user_id"]
    members = await db.fin_company_members.find(
        {"user_id": uid}, {"_id": 0, "company_id": 1}
    ).to_list(500)
    allowed = {m["company_id"] for m in members}
    if company_id:
        if company_id not in allowed:
            raise HTTPException(status_code=403, detail="Sem acesso a esta empresa.")
        allowed = {company_id}
    if not allowed:
        return []
    units = await db.fin_units.find(
        {"company_id": {"$in": list(allowed)}}, {"_id": 0}
    ).to_list(1000)
    units.sort(key=lambda u: (u.get("company_id") or "", u.get("sort", 0), (u.get("name") or "").lower()))
    return [FinUnitResponse(**u) for u in units]

@api_router.post("/fin/units", response_model=FinUnitResponse)
async def fin_create_unit(payload: FinUnitCreate, current_user: dict = Depends(get_current_user)):
    await fin_require_editor(payload.company_id, current_user)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Indica o nome da unidade.")
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": payload.company_id,
        "name": name,
        "type": (payload.type or "").strip() or None,
        "sort": payload.sort or 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.fin_units.insert_one(doc)
    return FinUnitResponse(**doc)

@api_router.put("/fin/units/{unit_id}", response_model=FinUnitResponse)
async def fin_update_unit(unit_id: str, payload: FinUnitCreate, current_user: dict = Depends(get_current_user)):
    unit = await db.fin_units.find_one({"id": unit_id}, {"_id": 0})
    if not unit:
        raise HTTPException(status_code=404, detail="Unidade não encontrada.")
    await fin_require_editor(unit["company_id"], current_user)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Indica o nome da unidade.")
    await db.fin_units.update_one(
        {"id": unit_id},
        {"$set": {"name": name, "type": (payload.type or "").strip() or None, "sort": payload.sort or 0}},
    )
    updated = await db.fin_units.find_one({"id": unit_id}, {"_id": 0})
    return FinUnitResponse(**updated)

@api_router.delete("/fin/units/{unit_id}")
async def fin_delete_unit(unit_id: str, current_user: dict = Depends(get_current_user)):
    unit = await db.fin_units.find_one({"id": unit_id}, {"_id": 0})
    if not unit:
        raise HTTPException(status_code=404, detail="Unidade não encontrada.")
    await fin_require_owner(unit["company_id"], current_user)
    await db.fin_units.delete_one({"id": unit_id})
    return {"message": "Unidade eliminada com sucesso"}


# ---------- Equipa global ----------
# Quem é adicionado fica com acesso a TODAS as empresas do dono (atuais e futuras).

@api_router.get("/fin/team", response_model=List[FinTeamMemberResponse])
async def fin_get_team(current_user: dict = Depends(get_current_user)):
    uid = current_user["user_id"]
    team = await db.fin_team_members.find({"owner_id": uid}, {"_id": 0}).to_list(500)
    result = []
    for t in team:
        u = await db.users.find_one({"id": t["member_id"]}, {"_id": 0, "email": 1, "name": 1})
        if not u:
            continue
        result.append(FinTeamMemberResponse(
            member_id=t["member_id"], email=u.get("email"), name=u.get("name"), role=t["role"]
        ))
    result.sort(key=lambda m: (m.email or "").lower())
    return result

@api_router.post("/fin/team", response_model=FinTeamMemberResponse)
async def fin_add_team_member(payload: FinTeamAdd, current_user: dict = Depends(get_current_user)):
    """Adiciona por email (a pessoa tem de já ter conta) e propaga às empresas do dono."""
    uid = current_user["user_id"]
    email = (payload.email or "").strip().lower()
    role = payload.role if payload.role in FIN_ROLES else "partner"
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Email inválido.")
    u = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "email": 1, "name": 1})
    if not u:
        raise HTTPException(
            status_code=404,
            detail="Essa pessoa ainda não tem conta. Pede-lhe para criar conta no sistema (com este email) e depois adiciona-a.",
        )
    if u["id"] == uid:
        raise HTTPException(status_code=409, detail="És tu — já tens acesso a tudo.")
    await db.fin_team_members.update_one(
        {"owner_id": uid, "member_id": u["id"]},
        {"$set": {"owner_id": uid, "member_id": u["id"], "role": role}},
        upsert=True,
    )
    for cid in await fin_owned_company_ids(uid):
        existing = await db.fin_company_members.find_one(
            {"company_id": cid, "user_id": u["id"]}, {"_id": 0, "role": 1}
        )
        if existing and existing.get("role") == "owner":
            continue  # nunca rebaixar um dono
        await db.fin_company_members.update_one(
            {"company_id": cid, "user_id": u["id"]},
            {"$set": {"company_id": cid, "user_id": u["id"], "role": role}},
            upsert=True,
        )
    return FinTeamMemberResponse(member_id=u["id"], email=u["email"], name=u.get("name"), role=role)

@api_router.put("/fin/team/{member_id}", response_model=FinTeamMemberResponse)
async def fin_update_team_member(member_id: str, payload: FinRoleUpdate, current_user: dict = Depends(get_current_user)):
    uid = current_user["user_id"]
    role = payload.role
    if role not in FIN_ROLES:
        raise HTTPException(status_code=400, detail="Papel inválido.")
    existing = await db.fin_team_members.find_one(
        {"owner_id": uid, "member_id": member_id}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Membro não encontrado na equipa.")
    await db.fin_team_members.update_one(
        {"owner_id": uid, "member_id": member_id}, {"$set": {"role": role}}
    )
    for cid in await fin_owned_company_ids(uid):
        await db.fin_company_members.update_one(
            {"company_id": cid, "user_id": member_id, "role": {"$ne": "owner"}},
            {"$set": {"role": role}},
        )
    u = await db.users.find_one({"id": member_id}, {"_id": 0, "email": 1, "name": 1}) or {}
    return FinTeamMemberResponse(member_id=member_id, email=u.get("email"), name=u.get("name"), role=role)

@api_router.delete("/fin/team/{member_id}")
async def fin_remove_team_member(member_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["user_id"]
    await db.fin_team_members.delete_one({"owner_id": uid, "member_id": member_id})
    for cid in await fin_owned_company_ids(uid):
        await db.fin_company_members.delete_one(
            {"company_id": cid, "user_id": member_id, "role": {"$ne": "owner"}}
        )
    return {"message": "Membro removido da equipa."}


# ====================================================================
# ============ FINANCEIRO · FASE 3 — PAGAMENTOS (faturas) ============
# ====================================================================
# Faturas de fornecedor (coleção fin_invoices) + regras por fornecedor
# (fin_supplier_rules, partilhadas pela equipa). Reimplementação fiel das
# regras do PHP (invoices.php / supplier_rules.php). Ref.: PORTING_GUIDE §5.1, §5.2.

import calendar as _calendar


def _fin_clean_date(v):
    """Devolve a data (string) ou None se vazia."""
    s = str(v).strip() if v is not None else ""
    return s or None

def _fin_clean_num(v):
    """Número (float) ou None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _fin_norm_sup(s):
    """Normaliza nome de fornecedor (igual ao supKey do frontend PHP)."""
    s = (s or "").lower()
    trans = str.maketrans(
        "áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn"
    )
    s = s.translate(trans)
    s = re.sub(r"\b(lda|ld|limitada|unipessoal|s\.?a|sa|sociedade)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fin_supplier_key_of(nif, supplier):
    """Chave do fornecedor: 'n:'+NIF se houver NIF, senão 't:'+nome normalizado."""
    d = re.sub(r"\D+", "", str(nif or ""))
    return ("n:" + d) if d else ("t:" + _fin_norm_sup(supplier))

async def fin_supplier_rule(nif, supplier):
    """Regra do fornecedor (ou None)."""
    return await db.fin_supplier_rules.find_one(
        {"supplier_key": fin_supplier_key_of(nif, supplier)}, {"_id": 0}
    )

def _fin_effective_due(inv, rule):
    """Vencimento efetivo (espelho de effectiveDue do frontend): se a regra do
    fornecedor tiver prazo, usa emissão + N dias (ignora o vencimento da fatura);
    senão, due_date ou, na falta, issue_date."""
    if rule and rule.get("pay_term_days") is not None and inv.get("issue_date"):
        try:
            base = datetime.fromisoformat(str(inv["issue_date"])[:10]).date()
            return (base + timedelta(days=int(rule["pay_term_days"]))).isoformat()
        except (ValueError, TypeError):
            pass
    return inv.get("due_date") or inv.get("issue_date") or None

async def fin_single_unit_id(company_id):
    """Se a empresa tiver exatamente 1 unidade, devolve-a (auto-atribuição)."""
    units = await db.fin_units.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(2)
    return units[0]["id"] if len(units) == 1 else None

async def fin_resolve_unit(company_id, given_unit_id):
    """Usa a unidade indicada (se pertencer à empresa), senão auto-atribui."""
    given = (given_unit_id or "").strip()
    if given:
        u = await db.fin_units.find_one(
            {"id": given, "company_id": company_id}, {"_id": 0, "id": 1}
        )
        if u:
            return given
    return await fin_single_unit_id(company_id)

def _fin_occurrence_date(anchor, freq, k):
    """k-ésima ocorrência a partir da âncora. Mensal/trim./anual mantém o dia
    com clamp ao último dia do mês (31 -> 28/30)."""
    d = date.fromisoformat(anchor)
    if freq == "weekly":
        return (d + timedelta(days=7 * k)).isoformat()
    step = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(freq, 1) * k
    total = (d.year * 12 + (d.month - 1)) + step
    y, m = total // 12, total % 12 + 1
    dim = _calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, dim)).isoformat()


# ---------- Modelos ----------

class FinInvoiceCreate(BaseModel):
    company_id: str
    unit_id: Optional[str] = None
    kind: Optional[str] = "invoice"
    supplier: Optional[str] = None
    nif: Optional[str] = None
    customer_nif: Optional[str] = None
    invoice_number: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    amount: Optional[float] = None
    amount_net: Optional[float] = None
    vat_amount: Optional[float] = None
    vat_rate: Optional[float] = None
    description: Optional[str] = None
    paid: Optional[bool] = False
    paid_date: Optional[str] = None
    source: Optional[str] = "manual"
    recurrence: Optional[str] = "none"
    file_name: Optional[str] = None
    category: Optional[str] = None  # FASE 17: categoria de despesa (livre; opções no frontend)

class FinApprovalAction(BaseModel):
    note: Optional[str] = None

class FinTogglePaid(BaseModel):
    paid: bool = False
    paid_date: Optional[str] = None

class FinReclassify(BaseModel):
    company_id: str

class FinSetUnit(BaseModel):
    unit_id: Optional[str] = None

class FinSupplierRuleUpsert(BaseModel):
    supplier_key: str
    supplier_name: Optional[str] = None
    pay_term_days: Optional[int] = None
    direct_debit: Optional[bool] = False
    auto_paid: Optional[bool] = False
    recurring: Optional[bool] = False


# ---------- Insert de fatura (aplica regra auto_paid) ----------

async def _fin_insert_invoice(company_id, kind, approval, data: dict, freq, group, user_id, apply_auto_paid=True):
    inv_id = str(uuid.uuid4())
    unit = await fin_resolve_unit(company_id, data.get("unit_id"))
    rule = await fin_supplier_rule(data.get("nif"), data.get("supplier"))
    # "Pago no ato" (auto_paid) só se aplica a uma fatura avulsa entrada à mão.
    # NUNCA a ocorrências futuras de recorrência (não se paga o mês que vem) nem
    # a faturas ingeridas por email (não há pagamento/movimento associado).
    auto_paid = bool(rule and rule.get("auto_paid")) if apply_auto_paid else False
    paid = bool(data.get("paid") or auto_paid)
    paid_date = _fin_clean_date(data.get("paid_date"))
    if paid and not paid_date:
        paid_date = _fin_clean_date(data.get("issue_date")) or datetime.now(timezone.utc).date().isoformat()
    doc = {
        "id": inv_id,
        "company_id": company_id,
        "unit_id": unit,
        "kind": kind,
        "supplier": data.get("supplier"),
        "nif": data.get("nif"),
        "customer_nif": data.get("customer_nif"),
        "invoice_number": data.get("invoice_number"),
        "issue_date": _fin_clean_date(data.get("issue_date")),
        "due_date": _fin_clean_date(data.get("due_date")),
        "amount": _fin_clean_num(data.get("amount")),
        "amount_net": _fin_clean_num(data.get("amount_net")),
        "vat_amount": _fin_clean_num(data.get("vat_amount")),
        "vat_rate": _fin_clean_num(data.get("vat_rate")),
        "description": data.get("description"),
        "category": data.get("category"),  # FASE 17: propaga-se às ocorrências (occ = dict(data))
        "paid": paid,
        "paid_date": paid_date,
        "approval_status": approval,
        "approval_note": None,
        "approval_by": None,
        "approval_at": None,
        "source": data.get("source") or "manual",
        "recurrence": freq,
        "recur_group": group,
        "file_name": data.get("file_name"),
        "pdf_path": None,
        "created_by": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.fin_invoices.insert_one(doc)
    return inv_id


# ---------- Faturas ----------

@api_router.get("/fin/invoices")
async def fin_get_invoices(company_id: str, current_user: dict = Depends(get_current_user)):
    # "all" = todas as empresas onde o utilizador é membro (vista agregada).
    if company_id == "all":
        ids = await fin_member_company_ids(current_user["user_id"])
        q = {"company_id": {"$in": ids}}
    else:
        await fin_require_member(company_id, current_user)
        q = {"company_id": company_id}
    invoices = await db.fin_invoices.find(q, {"_id": 0}).to_list(10000)
    invoices.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return invoices

@api_router.get("/fin/invoices/{invoice_id}")
async def fin_get_invoice_detail(invoice_id: str, current_user: dict = Depends(get_current_user)):
    """Ficha de detalhe da fatura: doc completo + movimento do extrato ligado
    (fin_movements com invoice_id == esta fatura) ou None."""
    inv = await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    await fin_require_member(inv["company_id"], current_user)
    inv["linked_movement"] = await db.fin_movements.find_one(
        {"invoice_id": invoice_id}, {"_id": 0}
    )
    return inv

@api_router.get("/fin/invoices/{invoice_id}/pdf")
async def fin_get_invoice_pdf(invoice_id: str, current_user: dict = Depends(get_current_user)):
    """Serve o PDF guardado da fatura (valida pertença). Faturas migradas do
    sistema antigo podem ter pdf_path de ficheiros não migrados — o exists()
    devolve 404 nesses casos."""
    inv = await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    await fin_require_member(inv["company_id"], current_user)
    pdf_path = inv.get("pdf_path")
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="Esta fatura não tem PDF guardado.")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"fatura-{inv.get('invoice_number') or invoice_id}.pdf",
    )

@api_router.post("/fin/invoices")
async def fin_create_invoice(payload: FinInvoiceCreate, current_user: dict = Depends(get_current_user)):
    await fin_require_editor(payload.company_id, current_user)
    uid = current_user["user_id"]
    data = payload.model_dump()
    kind = "payment" if data.get("kind") == "payment" else "invoice"
    # Sem fluxo de aprovação: faturas e pagamentos entram sempre válidos.
    approval = "approved"
    freq = data.get("recurrence") if data.get("recurrence") in ("weekly", "monthly", "quarterly", "yearly") else "none"
    group = str(uuid.uuid4()) if freq != "none" else None
    # auto_paid só na fatura avulsa (freq="none"); numa série nem a âncora é paga.
    inv_id = await _fin_insert_invoice(payload.company_id, kind, approval, data, freq, group, uid,
                                       apply_auto_paid=(freq == "none"))
    # Recorrência: gerar as próximas ocorrências (por pagar) da série.
    if freq != "none":
        anchor = _fin_clean_date(data.get("due_date")) or _fin_clean_date(data.get("issue_date"))
        if anchor:
            counts = {"weekly": 12, "monthly": 12, "quarterly": 4, "yearly": 3}
            for k in range(1, counts[freq]):
                d = _fin_occurrence_date(anchor, freq, k)
                occ = dict(data)
                occ.update({"issue_date": d, "due_date": d, "paid": False, "paid_date": ""})
                await _fin_insert_invoice(payload.company_id, kind, approval, occ, freq, group, uid,
                                          apply_auto_paid=False)
    return await db.fin_invoices.find_one({"id": inv_id}, {"_id": 0})

@api_router.put("/fin/invoices/{invoice_id}")
async def fin_update_invoice(invoice_id: str, payload: FinInvoiceCreate, current_user: dict = Depends(get_current_user)):
    inv = await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    await fin_require_editor(inv["company_id"], current_user)
    data = payload.model_dump()
    unit = await fin_resolve_unit(inv["company_id"], data.get("unit_id"))
    await db.fin_invoices.update_one(
        {"id": invoice_id},
        {"$set": {
            "unit_id": unit,
            "supplier": data.get("supplier"),
            "nif": data.get("nif"),
            "customer_nif": data.get("customer_nif"),
            "invoice_number": data.get("invoice_number"),
            "issue_date": _fin_clean_date(data.get("issue_date")),
            "due_date": _fin_clean_date(data.get("due_date")),
            "amount": _fin_clean_num(data.get("amount")),
            "amount_net": _fin_clean_num(data.get("amount_net")),
            "vat_amount": _fin_clean_num(data.get("vat_amount")),
            "vat_rate": _fin_clean_num(data.get("vat_rate")),
            "description": data.get("description"),
            "category": data.get("category"),  # FASE 17
            "paid": bool(data.get("paid")),
            "paid_date": _fin_clean_date(data.get("paid_date")),
        }},
    )
    return await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})

async def _fin_set_approval(invoice_id, status, note, current_user):
    inv = await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    await fin_require_editor(inv["company_id"], current_user)
    await db.fin_invoices.update_one(
        {"id": invoice_id},
        {"$set": {
            "approval_status": status,
            "approval_note": note,
            "approval_by": current_user["user_id"],
            "approval_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})

@api_router.put("/fin/invoices/{invoice_id}/approve")
async def fin_approve_invoice(invoice_id: str, payload: FinApprovalAction, current_user: dict = Depends(get_current_user)):
    return await _fin_set_approval(invoice_id, "approved", payload.note, current_user)

@api_router.put("/fin/invoices/{invoice_id}/reject")
async def fin_reject_invoice(invoice_id: str, payload: FinApprovalAction, current_user: dict = Depends(get_current_user)):
    return await _fin_set_approval(invoice_id, "rejected", payload.note, current_user)

@api_router.put("/fin/invoices/{invoice_id}/toggle-paid")
async def fin_toggle_paid(invoice_id: str, payload: FinTogglePaid, current_user: dict = Depends(get_current_user)):
    inv = await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    await fin_require_editor(inv["company_id"], current_user)
    await db.fin_invoices.update_one(
        {"id": invoice_id},
        {"$set": {"paid": bool(payload.paid), "paid_date": _fin_clean_date(payload.paid_date)}},
    )
    return await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})

@api_router.put("/fin/invoices/{invoice_id}/reclassify")
async def fin_reclassify_invoice(invoice_id: str, payload: FinReclassify, current_user: dict = Depends(get_current_user)):
    inv = await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    await fin_require_editor(inv["company_id"], current_user)
    await fin_require_editor(payload.company_id, current_user)
    await db.fin_invoices.update_one({"id": invoice_id}, {"$set": {"company_id": payload.company_id}})
    return await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})

@api_router.put("/fin/invoices/{invoice_id}/set-unit")
async def fin_set_invoice_unit(invoice_id: str, payload: FinSetUnit, current_user: dict = Depends(get_current_user)):
    inv = await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    await fin_require_editor(inv["company_id"], current_user)
    u = (payload.unit_id or "").strip()
    unit = None
    if u:
        chk = await db.fin_units.find_one({"id": u, "company_id": inv["company_id"]}, {"_id": 0, "id": 1})
        if not chk:
            raise HTTPException(status_code=400, detail="Unidade inválida para esta empresa.")
        unit = u
    await db.fin_invoices.update_one({"id": invoice_id}, {"$set": {"unit_id": unit}})
    return await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})

@api_router.delete("/fin/invoices/{invoice_id}")
async def fin_delete_invoice(invoice_id: str, series: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    inv = await db.fin_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    await fin_require_editor(inv["company_id"], current_user)
    # Cancelar série recorrente: apaga as ocorrências FUTURAS por pagar do mesmo grupo.
    if series == "future" and inv.get("recur_group"):
        today = datetime.now(timezone.utc).date().isoformat()
        res = await db.fin_invoices.delete_many({
            "recur_group": inv["recur_group"],
            "paid": {"$ne": True},
            "$or": [{"due_date": None}, {"due_date": {"$gte": today}}],
        })
        return {"ok": True, "cancelled": res.deleted_count}
    await db.fin_invoices.delete_one({"id": invoice_id})
    return {"ok": True}


# ---------- Regras por fornecedor (partilhadas) ----------

@api_router.get("/fin/supplier-rules")
async def fin_get_supplier_rules(current_user: dict = Depends(get_current_user)):
    # Regras globais: só quem trabalha no Financeiro (membro de alguma empresa)
    # as pode ler — evita fuga de fornecedores/NIF a logins sem pertença.
    if not await _fin_user_is_member_somewhere(current_user):
        raise HTTPException(status_code=403, detail="Sem acesso ao Financeiro.")
    return await db.fin_supplier_rules.find({}, {"_id": 0}).to_list(5000)

@api_router.post("/fin/supplier-rules")
async def fin_upsert_supplier_rule(payload: FinSupplierRuleUpsert, current_user: dict = Depends(get_current_user)):
    # Escrita (auto_paid/direct_debit/prazos mexem em dinheiro): só editor/owner.
    if not await _fin_user_is_editor_somewhere(current_user):
        raise HTTPException(status_code=403, detail="Sem permissão para gerir regras de fornecedor.")
    key = (payload.supplier_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Falta o fornecedor.")
    term = payload.pay_term_days
    if term is not None:
        term = max(0, int(term))
    doc = {
        "supplier_key": key,
        "supplier_name": (payload.supplier_name or "").strip(),
        "pay_term_days": term,
        "direct_debit": bool(payload.direct_debit),
        "auto_paid": bool(payload.auto_paid),
        "recurring": bool(payload.recurring),
        "updated_by": current_user["user_id"],
    }
    await db.fin_supplier_rules.update_one({"supplier_key": key}, {"$set": doc}, upsert=True)
    return doc

@api_router.delete("/fin/supplier-rules")
async def fin_delete_supplier_rule(key: str, current_user: dict = Depends(get_current_user)):
    if not await _fin_user_is_editor_somewhere(current_user):
        raise HTTPException(status_code=403, detail="Sem permissão para gerir regras de fornecedor.")
    await db.fin_supplier_rules.delete_one({"supplier_key": key})
    return {"ok": True}

# ==================== MARKETING — CAMPANHAS ====================

class CampaignCreate(BaseModel):
    name: str
    type: str = "campanha"          # campanha | promocao | evento | cupao
    company_id: Optional[str] = None  # None = todo o grupo
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "planeada"        # planeada | ativa | terminada
    channel: Optional[str] = None   # ex.: Instagram, Facebook, Loja...
    budget: Optional[float] = None
    description: Optional[str] = None
    result: Optional[str] = None

class CampaignResponse(BaseModel):
    id: str
    name: str
    type: str
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str
    channel: Optional[str] = None
    budget: Optional[float] = None
    description: Optional[str] = None
    result: Optional[str] = None
    created_at: str

async def _campaign_response(doc: dict) -> CampaignResponse:
    company_name = None
    if doc.get("company_id"):
        company = await db.companies.find_one({"id": doc["company_id"]}, {"_id": 0, "name": 1})
        company_name = company["name"] if company else None
    return CampaignResponse(**doc, company_name=company_name)

@api_router.get("/marketing/campaigns", response_model=List[CampaignResponse])
async def list_campaigns(company_id: Optional[str] = None, status: Optional[str] = None,
                         current_user: dict = Depends(admin_required)):
    query = {}
    if company_id:
        query["company_id"] = company_id
    if status:
        query["status"] = status
    docs = await db.mkt_campaigns.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return [await _campaign_response(d) for d in docs]

@api_router.post("/marketing/campaigns", response_model=CampaignResponse)
async def create_campaign(campaign: CampaignCreate, current_user: dict = Depends(admin_required)):
    if campaign.company_id:
        company = await db.companies.find_one({"id": campaign.company_id}, {"_id": 0})
        if not company:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
    doc = {
        "id": str(uuid.uuid4()),
        **campaign.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.get("user_id"),
    }
    await db.mkt_campaigns.insert_one(doc)
    return await _campaign_response(doc)

@api_router.put("/marketing/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(campaign_id: str, campaign: CampaignCreate, current_user: dict = Depends(admin_required)):
    result = await db.mkt_campaigns.update_one({"id": campaign_id}, {"$set": campaign.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    doc = await db.mkt_campaigns.find_one({"id": campaign_id}, {"_id": 0})
    return await _campaign_response(doc)

@api_router.delete("/marketing/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, current_user: dict = Depends(admin_required)):
    result = await db.mkt_campaigns.delete_one({"id": campaign_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    return {"message": "Campanha eliminada com sucesso"}

# ==================== MARKETING — CALENDÁRIO DE CONTEÚDOS ====================

class PostCreate(BaseModel):
    title: str
    channel: str = "instagram"      # instagram | facebook | tiktok | google | website | outro
    company_id: Optional[str] = None
    scheduled_date: Optional[str] = None  # AAAA-MM-DD (None = ideia sem data)
    scheduled_time: Optional[str] = None  # HH:MM
    status: str = "ideia"           # ideia | agendado | publicado
    content: Optional[str] = None

class PostResponse(BaseModel):
    id: str
    title: str
    channel: str
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    scheduled_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    status: str
    content: Optional[str] = None
    created_at: str

async def _post_response(doc: dict) -> PostResponse:
    company_name = None
    if doc.get("company_id"):
        company = await db.companies.find_one({"id": doc["company_id"]}, {"_id": 0, "name": 1})
        company_name = company["name"] if company else None
    return PostResponse(**doc, company_name=company_name)

@api_router.get("/marketing/posts", response_model=List[PostResponse])
async def list_posts(status: Optional[str] = None, channel: Optional[str] = None,
                     company_id: Optional[str] = None, current_user: dict = Depends(admin_required)):
    query = {}
    if status:
        query["status"] = status
    if channel:
        query["channel"] = channel
    if company_id:
        query["company_id"] = company_id
    docs = await db.mkt_posts.find(query, {"_id": 0}).sort("scheduled_date", 1).to_list(2000)
    return [await _post_response(d) for d in docs]

@api_router.post("/marketing/posts", response_model=PostResponse)
async def create_post(post: PostCreate, current_user: dict = Depends(admin_required)):
    if post.company_id:
        company = await db.companies.find_one({"id": post.company_id}, {"_id": 0})
        if not company:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
    doc = {
        "id": str(uuid.uuid4()),
        **post.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.get("user_id"),
    }
    await db.mkt_posts.insert_one(doc)
    return await _post_response(doc)

@api_router.put("/marketing/posts/{post_id}", response_model=PostResponse)
async def update_post(post_id: str, post: PostCreate, current_user: dict = Depends(admin_required)):
    result = await db.mkt_posts.update_one({"id": post_id}, {"$set": post.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Publicação não encontrada")
    doc = await db.mkt_posts.find_one({"id": post_id}, {"_id": 0})
    return await _post_response(doc)

@api_router.delete("/marketing/posts/{post_id}")
async def delete_post(post_id: str, current_user: dict = Depends(admin_required)):
    result = await db.mkt_posts.delete_one({"id": post_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Publicação não encontrada")
    return {"message": "Publicação eliminada com sucesso"}

# ==================== MARKETING — AVALIAÇÕES (GOOGLE) ====================
# Liga-se à Google Places API para mostrar a reputação de cada loja:
# classificação (estrelas), total de avaliações e as avaliações mais recentes.
# A chave (GOOGLE_PLACES_API_KEY) vive só no servidor. Para evitar gastar
# quota a cada abertura, guardamos um snapshot em cache (mkt_reviews_cache).

GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"


async def _google_places_get(path: str, params: dict) -> dict:
    """Chamada GET à Google Places API. Devolve o JSON ou {'error': ...}."""
    if not GOOGLE_PLACES_API_KEY:
        return {"error": "Chave da API Google não configurada no servidor."}
    if not HTTPX_AVAILABLE:
        return {"error": "Biblioteca httpx indisponível no servidor."}
    params = {**params, "key": GOOGLE_PLACES_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=12) as http_client:
            resp = await http_client.get(f"{GOOGLE_PLACES_BASE}/{path}", params=params)
        data = resp.json()
    except Exception as exc:  # rede/timeout/JSON inválido
        logging.warning(f"Google Places erro de rede: {exc}")
        return {"error": "Não foi possível contactar a Google."}
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        # Mensagens amigáveis para os erros mais comuns da Google.
        friendly = {
            "REQUEST_DENIED": "Pedido recusado pela Google (verifique a chave / Places API ativada).",
            "OVER_QUERY_LIMIT": "Limite de pedidos da Google atingido. Tente mais tarde.",
            "INVALID_REQUEST": "Pedido inválido (Place ID em falta ou incorreto).",
            "NOT_FOUND": "Local não encontrado na Google.",
        }
        msg = friendly.get(status, data.get("error_message") or f"Erro Google: {status}")
        return {"error": msg}
    return data


def _normalize_reviews(result: dict) -> list:
    """Extrai e normaliza as avaliações do resultado da Google."""
    out = []
    for r in (result.get("reviews") or []):
        out.append({
            "author": r.get("author_name"),
            "author_photo": r.get("profile_photo_url"),
            "author_url": r.get("author_url"),
            "rating": r.get("rating"),
            "text": r.get("text") or "",
            "relative_time": r.get("relative_time_description"),
            "time": r.get("time"),  # epoch (segundos)
        })
    return out


async def _fetch_place_reviews(place_id: str, force: bool = False) -> dict:
    """Devolve a reputação de um Place ID, usando cache quando possível."""
    now = datetime.now(timezone.utc)
    cached = await db.mkt_reviews_cache.find_one({"place_id": place_id}, {"_id": 0})
    if cached and not force:
        try:
            fetched_at = datetime.fromisoformat(cached["fetched_at"])
            age_min = (now - fetched_at).total_seconds() / 60
            if age_min < GOOGLE_REVIEWS_CACHE_MINUTES:
                return {**cached["data"], "fetched_at": cached["fetched_at"], "cached": True}
        except Exception:
            pass

    data = await _google_places_get("details/json", {
        "place_id": place_id,
        "language": "pt-PT",
        "reviews_sort": "newest",
        "fields": "name,rating,user_ratings_total,url,reviews",
    })
    if "error" in data:
        # Em erro, devolve a última cache disponível (se houver) com o aviso.
        if cached:
            return {**cached["data"], "fetched_at": cached["fetched_at"],
                    "cached": True, "error": data["error"]}
        return {"rating": None, "total": 0, "reviews": [], "google_url": None,
                "name": None, "error": data["error"], "fetched_at": None, "cached": False}

    result = data.get("result", {})
    payload = {
        "name": result.get("name"),
        "rating": result.get("rating"),
        "total": result.get("user_ratings_total", 0),
        "google_url": result.get("url"),
        "reviews": _normalize_reviews(result),
        "error": None,
    }
    await db.mkt_reviews_cache.update_one(
        {"place_id": place_id},
        {"$set": {"place_id": place_id, "data": payload, "fetched_at": now.isoformat()}},
        upsert=True,
    )
    return {**payload, "fetched_at": now.isoformat(), "cached": False}


@api_router.get("/marketing/reviews")
async def list_reviews(company_id: Optional[str] = None, refresh: bool = False,
                       current_user: dict = Depends(admin_required)):
    """Reputação por loja (e agregada). Cada loja precisa de google_place_id."""
    query = {}
    if company_id:
        query["company_id"] = company_id
    locations = await db.locations.find(query, {"_id": 0}).to_list(200)

    # nomes das empresas (cache local simples)
    company_names = {}
    items = []
    for loc in locations:
        cid = loc.get("company_id")
        if cid not in company_names:
            comp = await db.companies.find_one({"id": cid}, {"_id": 0})
            company_names[cid] = comp["name"] if comp else None
        place_id = loc.get("google_place_id")
        entry = {
            "location_id": loc["id"],
            "location_name": loc["name"],
            "company_id": cid,
            "company_name": company_names[cid],
            "google_place_id": place_id,
            "configured": bool(place_id),
            "rating": None,
            "total": 0,
            "reviews": [],
            "google_url": None,
            "fetched_at": None,
            "cached": False,
            "error": None,
        }
        if place_id:
            entry.update(await _fetch_place_reviews(place_id, force=refresh))
        items.append(entry)

    # resumo agregado (média ponderada pelo nº de avaliações)
    rated = [i for i in items if i.get("rating") and i.get("total")]
    total_reviews = sum(i["total"] for i in items if i.get("total"))
    avg_rating = None
    if rated:
        avg_rating = round(sum(i["rating"] * i["total"] for i in rated) / sum(i["total"] for i in rated), 2)

    return {
        "api_configured": bool(GOOGLE_PLACES_API_KEY),
        "summary": {
            "total_locations": len(items),
            "configured_locations": sum(1 for i in items if i["configured"]),
            "total_reviews": total_reviews,
            "avg_rating": avg_rating,
        },
        "locations": items,
    }


@api_router.get("/marketing/reviews/find-place")
async def find_place(query: str, current_user: dict = Depends(admin_required)):
    """Procura o Place ID de uma loja a partir do nome/morada (para configurar)."""
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(status_code=400, detail="Chave da API Google não configurada no servidor.")
    data = await _google_places_get("findplacefromtext/json", {
        "input": query,
        "inputtype": "textquery",
        "language": "pt-PT",
        "fields": "place_id,name,formatted_address,rating,user_ratings_total",
    })
    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])
    candidates = [{
        "place_id": c.get("place_id"),
        "name": c.get("name"),
        "address": c.get("formatted_address"),
        "rating": c.get("rating"),
        "total": c.get("user_ratings_total", 0),
    } for c in (data.get("candidates") or [])]
    return {"candidates": candidates}


# ==================== MARKETING — RELATÓRIOS / MÉTRICAS ====================
# Agrega o que já existe no sistema (campanhas + calendário de conteúdos),
# por empresa e por período. Sem dependências externas.

@api_router.get("/marketing/reports")
async def marketing_reports(company_id: Optional[str] = None,
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None,
                            current_user: dict = Depends(admin_required)):
    base = {}
    if company_id:
        base["company_id"] = company_id

    def in_range(d: Optional[str]) -> bool:
        # Datas em AAAA-MM-DD ordenam por string. Sem período => conta tudo.
        if not (start_date or end_date):
            return True
        if not d:
            return False
        if start_date and d < start_date:
            return False
        if end_date and d > end_date:
            return False
        return True

    today = date.today().isoformat()

    # --- Campanhas ---
    campaigns = await db.mkt_campaigns.find(dict(base), {"_id": 0}).to_list(5000)
    campaigns_f = [c for c in campaigns if in_range(c.get("start_date"))]
    camp_by_status, camp_by_type, camp_by_channel, budget_by_channel = {}, {}, {}, {}
    total_budget = 0.0
    active_now = 0
    for c in campaigns_f:
        st = c.get("status") or "—"
        camp_by_status[st] = camp_by_status.get(st, 0) + 1
        tp = c.get("type") or "—"
        camp_by_type[tp] = camp_by_type.get(tp, 0) + 1
        ch = (c.get("channel") or "").strip() or "Sem canal"
        camp_by_channel[ch] = camp_by_channel.get(ch, 0) + 1
        try:
            b = float(c.get("budget")) if c.get("budget") not in (None, "") else 0.0
        except (TypeError, ValueError):
            b = 0.0
        total_budget += b
        budget_by_channel[ch] = round(budget_by_channel.get(ch, 0.0) + b, 2)
        if st == "ativa":
            active_now += 1

    # --- Publicações (calendário) ---
    posts = await db.mkt_posts.find(dict(base), {"_id": 0}).to_list(10000)
    posts_f = [p for p in posts if in_range(p.get("scheduled_date"))]
    post_by_status, post_by_channel = {}, {}
    for p in posts_f:
        st = p.get("status") or "—"
        post_by_status[st] = post_by_status.get(st, 0) + 1
        ch = p.get("channel") or "outro"
        post_by_channel[ch] = post_by_channel.get(ch, 0) + 1

    upcoming = sorted(
        [p for p in posts if p.get("status") == "agendado" and (p.get("scheduled_date") or "") >= today],
        key=lambda p: (p.get("scheduled_date") or "", p.get("scheduled_time") or "")
    )[:6]
    upcoming_slim = [{
        "id": p.get("id"),
        "title": p.get("title"),
        "channel": p.get("channel"),
        "scheduled_date": p.get("scheduled_date"),
        "scheduled_time": p.get("scheduled_time"),
    } for p in upcoming]

    return {
        "campaigns": {
            "total": len(campaigns_f),
            "active_now": active_now,
            "total_budget": round(total_budget, 2),
            "by_status": camp_by_status,
            "by_type": camp_by_type,
            "by_channel": camp_by_channel,
            "budget_by_channel": budget_by_channel,
        },
        "posts": {
            "total": len(posts_f),
            "published": post_by_status.get("publicado", 0),
            "scheduled": post_by_status.get("agendado", 0),
            "ideas": post_by_status.get("ideia", 0),
            "by_status": post_by_status,
            "by_channel": post_by_channel,
            "upcoming": upcoming_slim,
        },
    }


# ==================== FERIADOS PERSONALIZADOS (MUNICIPAIS) ====================
# Feriados que recorrem todos os anos numa data fixa (mês/dia), além dos
# nacionais. Âmbito: todo o grupo, uma empresa, ou uma loja específica.

class HolidayCreate(BaseModel):
    name: str
    month: int
    day: int
    company_id: Optional[str] = None
    location_id: Optional[str] = None

    @field_validator("month")
    @classmethod
    def _month_ok(cls, v):
        if not 1 <= v <= 12:
            raise ValueError("Mês inválido (1-12)")
        return v

    @field_validator("day")
    @classmethod
    def _day_ok(cls, v):
        if not 1 <= v <= 31:
            raise ValueError("Dia inválido (1-31)")
        return v

class HolidayResponse(BaseModel):
    id: str
    name: str
    month: int
    day: int
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    location_id: Optional[str] = None
    location_name: Optional[str] = None

async def _holiday_response(doc: dict) -> HolidayResponse:
    company_name = None
    location_name = None
    if doc.get("company_id"):
        c = await db.companies.find_one({"id": doc["company_id"]}, {"_id": 0, "name": 1})
        company_name = c["name"] if c else None
    if doc.get("location_id"):
        l = await db.locations.find_one({"id": doc["location_id"]}, {"_id": 0, "name": 1})
        location_name = l["name"] if l else None
    return HolidayResponse(**doc, company_name=company_name, location_name=location_name)

@api_router.get("/holidays", response_model=List[HolidayResponse])
async def list_holidays(current_user: dict = Depends(admin_required)):
    docs = await db.holidays.find({}, {"_id": 0}).sort([("month", 1), ("day", 1)]).to_list(500)
    return [await _holiday_response(d) for d in docs]

@api_router.post("/holidays", response_model=HolidayResponse)
async def create_holiday(holiday: HolidayCreate, current_user: dict = Depends(admin_required)):
    doc = {
        "id": str(uuid.uuid4()),
        **holiday.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.holidays.insert_one(doc)
    return await _holiday_response(doc)

@api_router.put("/holidays/{holiday_id}", response_model=HolidayResponse)
async def update_holiday(holiday_id: str, holiday: HolidayCreate, current_user: dict = Depends(admin_required)):
    result = await db.holidays.update_one({"id": holiday_id}, {"$set": holiday.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Feriado não encontrado")
    doc = await db.holidays.find_one({"id": holiday_id}, {"_id": 0})
    return await _holiday_response(doc)

@api_router.delete("/holidays/{holiday_id}")
async def delete_holiday(holiday_id: str, current_user: dict = Depends(admin_required)):
    result = await db.holidays.delete_one({"id": holiday_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Feriado não encontrado")
    return {"message": "Feriado eliminado com sucesso"}

# ===== FINANCEIRO · FASE 4 — EXTRATO/TESOURARIA =====
# ====================================================================
# Extrato bancário (contas + movimentos do .xlsx do banco) e conciliação
# automática fatura↔movimento. Reimplementação fiel do PHP (movements.php).
# Ref.: PORTING_GUIDE §5.6. Coleções: fin_bank_accounts, fin_movements.

# ---------- Modelos ----------

class FinBankAccountUpsert(BaseModel):
    company_id: str
    account_number: str
    bank: Optional[str] = None
    name: Optional[str] = None
    currency: Optional[str] = "EUR"

class FinMovementRow(BaseModel):
    date_lancamento: Optional[str] = None
    date_valor: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[str] = None      # STRING crua do ficheiro (ex.: "-994.34")
    balance: Optional[str] = None     # STRING crua do ficheiro
    currency: Optional[str] = None

class FinMovementImport(BaseModel):
    company_id: str
    account_number: str
    bank: Optional[str] = None
    account_name: Optional[str] = None
    rows: List[FinMovementRow] = []

class FinMovementTitle(BaseModel):
    title: Optional[str] = None

class FinMovementLink(BaseModel):
    invoice_id: str

class FinCompanyIdBody(BaseModel):
    company_id: str


# ---------- Contas bancárias ----------

@api_router.get("/fin/bank-accounts")
async def fin_get_bank_accounts(company_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Contas de uma empresa (ou de TODAS as empresas do utilizador se vazio)."""
    cid = (company_id or "").strip()
    if cid:
        await fin_require_member(cid, current_user)
        company_ids = [cid]
    else:
        members = await db.fin_company_members.find(
            {"user_id": current_user["user_id"]}, {"_id": 0, "company_id": 1}
        ).to_list(500)
        company_ids = [m["company_id"] for m in members]
        if not company_ids:
            return []
    accounts = await db.fin_bank_accounts.find(
        {"company_id": {"$in": company_ids}}, {"_id": 0}
    ).to_list(2000)
    accounts.sort(key=lambda a: (a.get("name") or "").lower())
    return accounts

@api_router.post("/fin/bank-accounts")
async def fin_upsert_bank_account(payload: FinBankAccountUpsert, current_user: dict = Depends(get_current_user)):
    """Upsert por account_number (nº de conta único, auto-rota o import)."""
    await fin_require_editor(payload.company_id, current_user)
    acc_num = (payload.account_number or "").strip()
    if not acc_num:
        raise HTTPException(status_code=400, detail="Falta o nº de conta.")
    existing = await db.fin_bank_accounts.find_one({"account_number": acc_num}, {"_id": 0})
    # Anti-IDOR cross-empresa: o nº de conta é único e identifica a empresa dona.
    # Se já pertence a OUTRA empresa, não reatribuir (senão roubava-se a conta).
    if existing and existing.get("company_id") != payload.company_id:
        raise HTTPException(
            status_code=409,
            detail="Este nº de conta já está registado noutra empresa. Não é possível reatribuí-lo.",
        )
    doc = {
        "company_id": payload.company_id,
        "bank": (payload.bank or "").strip() or None,
        "account_number": acc_num,
        "name": (payload.name or "").strip() or None,
        "currency": (payload.currency or "EUR").strip() or "EUR",
    }
    if existing:
        await db.fin_bank_accounts.update_one({"account_number": acc_num}, {"$set": doc})
        return await db.fin_bank_accounts.find_one({"account_number": acc_num}, {"_id": 0})
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.fin_bank_accounts.insert_one(doc)
    return await db.fin_bank_accounts.find_one({"account_number": acc_num}, {"_id": 0})


# ---------- Helper: obtém/cria conta por nº ----------

async def _fin_get_or_create_account(company_id, account_number, bank, name):
    """Encontra a conta por nº nessa empresa; cria-a se não existir."""
    acc_num = (account_number or "").strip()
    acc = await db.fin_bank_accounts.find_one({"account_number": acc_num}, {"_id": 0})
    if acc:
        return acc
    acc = {
        "id": str(uuid.uuid4()),
        "company_id": company_id,
        "bank": (bank or "").strip() or None,
        "account_number": acc_num,
        "name": (name or "").strip() or None,
        "currency": "EUR",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.fin_bank_accounts.insert_one(acc)
    acc.pop("_id", None)
    return acc


# ---------- Movimentos ----------

@api_router.get("/fin/movements")
async def fin_get_movements(
    company_id: str,
    account_id: Optional[str] = None,
    month: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Movimentos de uma empresa, filtráveis por conta e mês (YYYY-MM).
    company_id="all" = todas as empresas onde o utilizador é membro."""
    if company_id == "all":
        ids = await fin_member_company_ids(current_user["user_id"])
        q = {"company_id": {"$in": ids}}
    else:
        await fin_require_member(company_id, current_user)
        q = {"company_id": company_id}
    acc = (account_id or "").strip()
    if acc:
        q["account_id"] = acc
    mon = (month or "").strip()
    if mon:
        q["date_lancamento"] = {"$regex": "^" + re.escape(mon)}
    movements = await db.fin_movements.find(q, {"_id": 0}).to_list(20000)
    movements.sort(key=lambda m: m.get("date_lancamento") or "", reverse=True)
    return movements

@api_router.post("/fin/movements/import")
async def fin_import_movements(payload: FinMovementImport, current_user: dict = Depends(get_current_user)):
    """Importa movimentos do .xlsx (já parseados pelo frontend). Dedup seguro:
    reimportar não duplica. `amount`/`balance` chegam como STRING crua e são
    usadas TAL E QUAL no dedup_key; gravadas como float (com sinal)."""
    await fin_require_editor(payload.company_id, current_user)
    acc = await _fin_get_or_create_account(
        payload.company_id, payload.account_number, payload.bank, payload.account_name
    )
    account_number = (payload.account_number or "").strip()
    inserted = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    for row in payload.rows:
        date_lancamento = (row.date_lancamento or "").strip() or None
        amount_raw = "" if row.amount is None else str(row.amount)
        balance_raw = "" if row.balance is None else str(row.balance)
        description = row.description or ""
        dedup_key = hashlib.sha1(
            f"{account_number}|{date_lancamento}|{amount_raw}|{balance_raw}|{description}".encode()
        ).hexdigest()
        exists = await db.fin_movements.find_one({"dedup_key": dedup_key}, {"_id": 0, "id": 1})
        if exists:
            skipped += 1
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "account_id": acc["id"],
            "company_id": payload.company_id,
            "date_lancamento": date_lancamento,
            "date_valor": (row.date_valor or "").strip() or None,
            "description": description or None,
            "amount": _fin_clean_num(amount_raw),
            "balance": _fin_clean_num(balance_raw),
            "currency": (row.currency or "").strip() or acc.get("currency") or "EUR",
            "title": None,
            "invoice_id": None,
            "link_auto": False,
            "attachment_path": None,
            "dedup_key": dedup_key,
            "source": "bank_import",
            "created_by": current_user["user_id"],
            "created_at": now,
        }
        await db.fin_movements.insert_one(doc)
        inserted += 1
    return {"inserted": inserted, "skipped": skipped, "account_id": acc["id"]}

@api_router.put("/fin/movements/{movement_id}/set-title")
async def fin_set_movement_title(movement_id: str, payload: FinMovementTitle, current_user: dict = Depends(get_current_user)):
    """Justificação/título editável do movimento."""
    mv = await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(status_code=404, detail="Movimento não encontrado.")
    await fin_require_editor(mv["company_id"], current_user)
    title = (payload.title or "").strip() or None
    await db.fin_movements.update_one({"id": movement_id}, {"$set": {"title": title}})
    return await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})

@api_router.put("/fin/movements/{movement_id}/link")
async def fin_link_movement(movement_id: str, payload: FinMovementLink, current_user: dict = Depends(get_current_user)):
    """Liga (manualmente) uma fatura ao movimento e marca-a paga."""
    mv = await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(status_code=404, detail="Movimento não encontrado.")
    await fin_require_editor(mv["company_id"], current_user)
    inv = await db.fin_invoices.find_one({"id": payload.invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    if inv["company_id"] != mv["company_id"]:
        raise HTTPException(status_code=400, detail="A fatura é de outra empresa.")
    await db.fin_movements.update_one(
        {"id": movement_id}, {"$set": {"invoice_id": inv["id"], "link_auto": False}}
    )
    await db.fin_invoices.update_one(
        {"id": inv["id"]}, {"$set": {"paid": True, "paid_date": mv.get("date_lancamento")}}
    )
    return await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})

@api_router.put("/fin/movements/{movement_id}/unlink")
async def fin_unlink_movement(movement_id: str, current_user: dict = Depends(get_current_user)):
    """Desliga a fatura do movimento e reverte-a a 'por pagar'."""
    mv = await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(status_code=404, detail="Movimento não encontrado.")
    await fin_require_editor(mv["company_id"], current_user)
    inv_id = mv.get("invoice_id")
    await db.fin_movements.update_one(
        {"id": movement_id}, {"$set": {"invoice_id": None, "link_auto": False}}
    )
    if inv_id:
        await db.fin_invoices.update_one(
            {"id": inv_id}, {"$set": {"paid": False, "paid_date": None}}
        )
    return await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})

@api_router.post("/fin/movements/{movement_id}/attach")
async def fin_attach_movement(
    movement_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Anexa um PDF (justificativo) a um movimento (saída sem fatura)."""
    mv = await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(status_code=404, detail="Movimento não encontrado.")
    await fin_require_editor(mv["company_id"], current_user)
    dest_dir = UPLOAD_DIR / "fin_movements"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{movement_id}.pdf"
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    await db.fin_movements.update_one(
        {"id": movement_id}, {"$set": {"attachment_path": str(dest_path)}}
    )
    return await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})

@api_router.get("/fin/movements/{movement_id}/attachment")
async def fin_get_movement_attachment(movement_id: str, current_user: dict = Depends(get_current_user)):
    """Serve o PDF anexado ao movimento (valida pertença)."""
    mv = await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(status_code=404, detail="Movimento não encontrado.")
    await fin_require_member(mv["company_id"], current_user)
    path = mv.get("attachment_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Sem anexo.")
    return FileResponse(path, filename=f"movimento-{movement_id}.pdf")


# ---------- Conciliação automática (#4) ----------

@api_router.post("/fin/movements/automatch")
async def fin_automatch_movements(payload: FinCompanyIdBody, current_user: dict = Depends(get_current_user)):
    """Concilia automaticamente saídas (amount < 0) sem fatura ligada.
    Candidato = fatura da MESMA empresa com |montante| == amount (2 casas) E
    nome do fornecedor (normalizado, não-vazio) contido na descrição
    (normalizada). Preferir por pagar; só liga se houver EXATAMENTE 1."""
    await fin_require_editor(payload.company_id, current_user)
    invoices = await db.fin_invoices.find(
        {"company_id": payload.company_id}, {"_id": 0, "id": 1, "supplier": 1, "amount": 1, "paid": 1}
    ).to_list(20000)
    movements = await db.fin_movements.find(
        {"company_id": payload.company_id, "invoice_id": None},
        {"_id": 0, "id": 1, "amount": 1, "description": 1, "date_lancamento": 1},
    ).to_list(20000)
    linked = 0
    used = set()  # faturas já ligadas nesta corrida — nunca reutilizar
    for mv in movements:
        amount = mv.get("amount")
        if amount is None or amount >= 0:
            continue
        target = round(abs(amount), 2)
        desc_n = _fin_norm_sup(mv.get("description"))
        cands = []
        for inv in invoices:
            if inv["id"] in used:
                continue
            inv_amount = inv.get("amount")
            if inv_amount is None:
                continue
            if round(float(inv_amount), 2) != target:
                continue
            sup_n = _fin_norm_sup(inv.get("supplier"))
            if not sup_n or sup_n not in desc_n:
                continue
            cands.append(inv)
        if not cands:
            continue
        unpaid = [i for i in cands if not i.get("paid")]
        pick = unpaid if unpaid else cands
        if len(pick) != 1:
            continue  # conservador: 0 ou >1 → não liga
        inv = pick[0]
        await db.fin_movements.update_one(
            {"id": mv["id"]}, {"$set": {"invoice_id": inv["id"], "link_auto": True}}
        )
        await db.fin_invoices.update_one(
            {"id": inv["id"]}, {"$set": {"paid": True, "paid_date": mv.get("date_lancamento")}}
        )
        inv["paid"] = True  # evita re-uso da mesma fatura noutro movimento
        used.add(inv["id"])
        linked += 1
    return {"linked": linked}


# ===== FINANCEIRO · FASE 4B — INGESTÃO IMAP + IA (#1) =====
# ==========================================================
# Endpoint de cron (protegido por CRON_KEY, sem JWT) que lê N caixas IMAP,
# manda cada PDF anexo à Claude (Haiku) para extrair os dados da fatura,
# descarta não-faturas e duplicados, associa à empresa pelo NIF do ADQUIRENTE,
# aplica as regras do fornecedor, guarda o PDF e cria a fatura.
# Reimplementação do PHP cron_ingest.php (ref.: PORTING_GUIDE §5.3).
#
# IMAP/HTTP são síncronos (stdlib imaplib + httpx.Client): essa parte corre em
# threads via asyncio.to_thread, enquanto as operações de BD (motor) ficam no
# event loop. Cada caixa/mensagem/anexo está envolvido em try/except para que
# uma falha não aborte a execução inteira.

import imaplib
import email as _email
import base64

# Janela de pesquisa: mensagens recebidas nos últimos 7 dias.
_FIN_INGEST_DAYS = 7
# Limite defensivo de anexos processados por execução (evita timeouts).
_FIN_INGEST_LIMIT = 120

# Capturado no IMPORT (defensivo: usado como fallback se o os.environ vier vazio
# em runtime) e registado no log para diagnóstico do que a app realmente recebe.
_FIN_IMAP_RAW = os.environ.get("IMAP_MAILBOXES", "")
try:
    logger.info(
        "[fin-ingest] import: IMAP_MAILBOXES len=%d | CRON_KEY set=%s | GEMINI_API_KEY len=%d",
        len(_FIN_IMAP_RAW), bool(os.environ.get("CRON_KEY")), len(os.environ.get("GEMINI_API_KEY", "")),
    )
except Exception:  # noqa: BLE001
    pass

_FIN_INGEST_PROMPT = (
    "Esta é uma fatura de fornecedor (Portugal). Devolve APENAS um JSON válido com: "
    '{"supplier":"nome do fornecedor/emitente",'
    '"nif":"NIF do FORNECEDOR (9 dígitos) ou null",'
    '"customerNif":"NIF do ADQUIRENTE/cliente (9 dígitos) ou null",'
    '"customerName":"nome do adquirente ou null",'
    '"invoiceNumber":"número da fatura",'
    '"issueDate":"YYYY-MM-DD ou null",'
    '"dueDate":"YYYY-MM-DD ou null",'
    '"amount":valor TOTAL com IVA (número) ou null,'
    '"amountNet":valor sem IVA (número) ou null,'
    '"vatAmount":valor do IVA (número) ou null,'
    '"vatRate":taxa de IVA principal em % (número) ou null,'
    '"description":"breve descrição",'
    '"isInvoice":true se for mesmo uma fatura/recibo de compra, false caso contrário}'
)


def _fin_only_digits(s):
    """Só os dígitos de uma string (ex.: NIF)."""
    return re.sub(r"\D+", "", str(s or ""))


def _fin_gemini_call(pdf_bytes, prompt, max_tokens, timeout):
    """Chama a API do Google Gemini (síncrono) com o PDF em base64 e um prompt.
    Devolve (raw_text, finish_reason). Em falha de rede/HTTP, finish_reason vem
    como 'ERROR:<mensagem>' (e raw_text ''). Corre em thread.

    finish_reason típico: 'STOP' (completo), 'MAX_TOKENS' (resposta cortada).
    generationConfig.responseMimeType=application/json força saída JSON válida."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "", "ERROR:sem GEMINI_API_KEY"
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    body = {
        "contents": [{
            "parts": [
                {"inline_data": {
                    "mime_type": "application/pdf",
                    "data": base64.b64encode(pdf_bytes).decode(),
                }},
                {"text": prompt},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            # Extração pura: desliga o "pensamento" do Gemini 2.5 (senão consome
            # o orçamento de tokens a pensar e devolve conteúdo vazio).
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        with httpx.Client(timeout=timeout) as http_client:
            # Chave no HEADER (não no URL): evita que apareça nos logs do httpx.
            resp = http_client.post(
                url,
                headers={"content-type": "application/json", "x-goog-api-key": api_key},
                json=body,
            )
    except Exception as exc:  # noqa: BLE001
        return "", f"ERROR:rede IA: {exc}"
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {}).get("message")
        except Exception:  # noqa: BLE001
            err = None
        return "", f"ERROR:{err or f'HTTP {resp.status_code}'}"
    try:
        data = resp.json()
        cand = (data.get("candidates") or [{}])[0]
        finish = cand.get("finishReason") or "STOP"
        parts = (cand.get("content") or {}).get("parts") or [{}]
        raw = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except Exception:  # noqa: BLE001
        return "", "ERROR:resposta IA inválida"
    return raw, finish


def _fin_extract_pdf_sync(pdf_bytes):
    """Lê a fatura em PDF com o Gemini e devolve o dict extraído, ou
    {'error': '...'} em caso de falha. Corre em thread."""
    raw, finish = _fin_gemini_call(pdf_bytes, _FIN_INGEST_PROMPT, 2048, 120)
    if finish.startswith("ERROR:"):
        return {"error": finish[len("ERROR:"):]}
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return {"error": "resposta IA inválida"}
    try:
        parsed = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {"error": "json IA inválido"}
    return parsed if isinstance(parsed, dict) else {"error": "json IA inválido"}


def _fin_fetch_pdf_attachments_sync(mb):
    """Liga a uma caixa IMAP, lê as mensagens da janela e devolve uma lista de
    {'file_name': str, 'bytes': bytes}. Síncrono — corre em thread."""
    host = mb.get("host")
    port = int(mb.get("port") or 993)
    imap = imaplib.IMAP4_SSL(host, port)
    try:
        imap.login(mb.get("user"), mb.get("pass"))
        imap.select("INBOX")
        since = (datetime.now(timezone.utc) - timedelta(days=_FIN_INGEST_DAYS)).strftime("%d-%b-%Y")
        typ, msgnums = imap.search(None, "SINCE", since)
        ids = msgnums[0].split() if (typ == "OK" and msgnums and msgnums[0]) else []
        ids = list(reversed(ids))  # mais recentes primeiro
        out = []
        for num in ids:
            try:
                typ, msgdata = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not msgdata or not msgdata[0]:
                    continue
                raw = msgdata[0][1]
                msg = _email.message_from_bytes(raw)
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    ctype = (part.get_content_type() or "").lower()
                    fn = part.get_filename() or ""
                    is_pdf = ctype == "application/pdf" or fn.lower().endswith(".pdf")
                    if not is_pdf:
                        continue
                    payload = part.get_payload(decode=True)
                    if not payload or len(payload) < 200:
                        continue
                    out.append({"file_name": fn or "fatura.pdf", "bytes": payload})
            except Exception:  # noqa: BLE001
                continue
        return out
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass


def _fin_looks_like_invoice(ex):
    """Heurística: é fatura, tem número e tem total."""
    is_inv = ex.get("isInvoice")
    is_inv = True if is_inv is None else bool(is_inv)
    has_num = bool(str(ex.get("invoiceNumber") or "").strip())
    has_amount = _fin_clean_num(ex.get("amount")) is not None
    return is_inv and has_num and has_amount


async def _fin_is_duplicate(invoice_number, supplier_nif, supplier):
    """Duplicado se já existir fatura com o mesmo invoice_number normalizado
    (minúsculas, sem espaços) E (mesmo NIF de fornecedor OU mesmo nome
    normalizado)."""
    num = re.sub(r"\s+", "", str(invoice_number or "").lower())
    if not num:
        return False
    nif = _fin_only_digits(supplier_nif)
    sup = _fin_norm_sup(supplier)
    cands = await db.fin_invoices.find(
        {}, {"_id": 0, "invoice_number": 1, "nif": 1, "supplier": 1}
    ).to_list(20000)
    for r in cands:
        rnum = re.sub(r"\s+", "", str(r.get("invoice_number") or "").lower())
        if rnum != num:
            continue
        if nif and _fin_only_digits(r.get("nif")) == nif:
            return True
        if sup and _fin_norm_sup(r.get("supplier")) == sup:
            return True
    return False


async def _fin_match_company(companies, customer_nif, customer_name, fallback_nif):
    """Associa à empresa pelo NIF do adquirente, com os fallbacks do PHP:
    1) NIF do adquirente == company.nif
    2) nome do adquirente normalizado contido/igual ao da empresa
    3) empresa do company_nif da caixa (fallback)
    4) empresa cujo nome normalizado seja 'por classificar'
    senão None."""
    n = _fin_only_digits(customer_nif)
    if n:
        for c in companies:
            if _fin_only_digits(c.get("nif")) == n:
                return c
    nn = _fin_norm_sup(customer_name)
    if nn:
        for c in companies:
            cn = _fin_norm_sup(c.get("name"))
            if cn and (cn == nn or nn in cn or cn in nn):
                return c
    fb = _fin_only_digits(fallback_nif)
    if fb:
        for c in companies:
            if _fin_only_digits(c.get("nif")) == fb:
                return c
    for c in companies:
        if _fin_norm_sup(c.get("name")) == "por classificar":
            return c
    return None


@api_router.post("/fin/cron/ingest")
async def fin_cron_ingest(key: str = Query(...)):
    """Ingestão automática de faturas por email (IMAP + IA). Protegido por
    CRON_KEY. Não usa JWT."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or not secrets.compare_digest(str(key), str(cron_key)):
        raise HTTPException(status_code=403, detail="Acesso negado.")

    raw = os.environ.get("IMAP_MAILBOXES") or _FIN_IMAP_RAW or "[]"
    try:
        mailboxes = json.loads(raw)
        if not isinstance(mailboxes, list):
            mailboxes = []
    except Exception as _e:  # noqa: BLE001
        logger.warning("[fin-ingest] IMAP_MAILBOXES invalido (len=%d): %s", len(raw), _e)
        mailboxes = []
    logger.info("[fin-ingest] pedido: raw_len=%d mailboxes=%d", len(raw), len(mailboxes))

    summary = {
        "mailboxes": len(mailboxes),
        "attachments_seen": 0,
        "invoices_created": 0,
        "skipped_not_invoice": 0,
        "skipped_duplicate": 0,
        "errors": [],
    }
    if not mailboxes:
        return summary

    companies = await db.fin_companies.find({}, {"_id": 0}).to_list(5000)
    processed = 0

    for bi, mb in enumerate(mailboxes):
        try:
            attachments = await asyncio.to_thread(_fin_fetch_pdf_attachments_sync, mb)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"caixa #{bi} ({mb.get('user')}): {exc}")
            continue

        for att in attachments:
            if processed >= _FIN_INGEST_LIMIT:
                break
            fn = att.get("file_name") or "fatura.pdf"
            pdf_bytes = att.get("bytes") or b""
            try:
                k = hashlib.sha1(pdf_bytes).hexdigest()
                if await db.fin_ingest_log.find_one({"k": k}):
                    continue  # já visto
                summary["attachments_seen"] += 1
                processed += 1

                ex = await asyncio.to_thread(_fin_extract_pdf_sync, pdf_bytes)

                if not isinstance(ex, dict) or ex.get("error"):
                    # Erro transitório (chave/rede/502): NÃO marcar como visto -> repete na próxima.
                    summary["errors"].append(f"{fn}: {ex.get('error') if isinstance(ex, dict) else 'IA inválida'}")
                    continue

                # Resultado definitivo (fatura / não-fatura / duplicado): marcar como visto.
                await db.fin_ingest_log.update_one(
                    {"k": k},
                    {"$setOnInsert": {"k": k, "at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True,
                )

                if not _fin_looks_like_invoice(ex):
                    summary["skipped_not_invoice"] += 1
                    continue

                if await _fin_is_duplicate(ex.get("invoiceNumber"), ex.get("nif"), ex.get("supplier")):
                    summary["skipped_duplicate"] += 1
                    continue

                comp = await _fin_match_company(
                    companies, ex.get("customerNif"), ex.get("customerName"), mb.get("company_nif")
                )
                company_id = comp.get("id") if comp else None
                if not company_id:
                    summary["errors"].append(f"{fn}: sem empresa correspondente — ignorada")
                    continue

                nifd = _fin_only_digits(ex.get("nif")) or None
                supplier = ex.get("supplier")
                rule = await fin_supplier_rule(nifd, supplier)
                is_recurring = bool(rule and rule.get("recurring"))
                # Sem fluxo de aprovação: entram sempre válidas. is_recurring
                # só decide a nota informativa (fornecedor recorrente) abaixo.
                approval = "approved"

                data = {
                    "supplier": supplier,
                    "nif": nifd,
                    "customer_nif": _fin_only_digits(ex.get("customerNif")) or None,
                    "invoice_number": ex.get("invoiceNumber"),
                    "issue_date": ex.get("issueDate"),
                    "due_date": ex.get("dueDate"),
                    "amount": ex.get("amount"),
                    "amount_net": ex.get("amountNet"),
                    "vat_amount": ex.get("vatAmount"),
                    "vat_rate": ex.get("vatRate"),
                    "description": ex.get("description"),
                    "source": "email",
                    "file_name": fn,
                }
                # Ingestão por email: NÃO aplicar auto_paid — uma fatura recebida
                # não está paga só porque o fornecedor é "pago no ato" (sem
                # pagamento/movimento real). Entra por pagar e trata-se na Agenda.
                invoice_id = await _fin_insert_invoice(
                    company_id, "invoice", approval, data, "none", None, "cron",
                    apply_auto_paid=False,
                )

                # Guarda o PDF em UPLOAD_DIR/fin_invoices/<company_id>/<invoice_id>.pdf
                try:
                    dest_dir = UPLOAD_DIR / "fin_invoices" / company_id
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    pdf_path = dest_dir / f"{invoice_id}.pdf"
                    pdf_path.write_bytes(pdf_bytes)
                    update = {"pdf_path": str(pdf_path)}
                    if is_recurring:
                        update["approval_note"] = "Aprovada automaticamente (fornecedor recorrente)"
                        update["approval_at"] = datetime.now(timezone.utc).isoformat()
                    await db.fin_invoices.update_one({"id": invoice_id}, {"$set": update})
                except Exception as exc:  # noqa: BLE001
                    summary["errors"].append(f"{fn}: PDF não guardado: {exc}")

                summary["invoices_created"] += 1
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"{fn}: {exc}")
                continue

    return summary


# ===== FINANCEIRO · FASE 12 — IMPORTAÇÃO DE EXTRATO PDF (Millennium BCP) =====
# POST /fin/movements/import-pdf: recebe o PDF do extrato do Millennium BCP
# (extrato mensal oficial OU consulta de movimentos de um período), extrai os
# movimentos com a IA, valida a cadeia de saldos (defesa contra extrações
# erradas: só importa se a aritmética bater a 100%), roteia para a empresa
# certa pelo NÚMERO DE CONTA (ignora a empresa selecionada no UI) e insere
# sem duplicar (2 níveis de dedup — o nível 2 protege contra os movimentos
# migrados do .xlsx, que têm dedup_key noutro formato).

# Limite defensivo do ficheiro (extratos maiores → usar .xlsx ou período menor).
_FIN_STATEMENT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

_FIN_STATEMENT_ERR_TRUNC = (
    "Não consegui ler o extrato completo (documento demasiado grande?). "
    "Tenta um período mais curto ou o ficheiro .xlsx."
)

_FIN_STATEMENT_PROMPT = (
    "Isto é um extrato bancário do Millennium BCP (Portugal) — extrato mensal "
    "oficial ou consulta de movimentos de um período. Devolve APENAS um JSON "
    "válido, sem texto antes nem depois, com exatamente esta forma: "
    '{"account_number":"número da conta bancária (dígitos, como aparece no '
    'cabeçalho; pode ser NIB/IBAN)",'
    '"holder":"nome do titular da conta ou null",'
    '"movements":[{"date_lancamento":"YYYY-MM-DD",'
    '"date_valor":"YYYY-MM-DD ou null",'
    '"description":"descrição do movimento",'
    '"amount":-994.34,'
    '"balance":336.24}]} '
    "Regras: 'amount' é o valor do movimento COM SINAL (negativo = "
    "débito/saída, positivo = crédito/entrada); 'balance' é o saldo "
    "contabilístico APÓS o movimento (a coluna de saldo dessa linha); inclui "
    "TODOS os movimentos do documento, pela ordem em que aparecem; números "
    "com ponto decimal e sem separador de milhares; NÃO inventes linhas — "
    "totais, saldos iniciais/finais e cabeçalhos NÃO são movimentos."
)


def _fin_extract_statement_sync(pdf_bytes):
    """Irmã de _fin_extract_pdf_sync mas para EXTRATOS bancários (prompt
    próprio e max_tokens 8192 — um extrato tem dezenas/centenas de linhas).
    Lê com o Gemini. Devolve o dict extraído ou {'error': '...'} ('truncado' =
    JSON cortado ou inválido → o endpoint devolve 422). Corre em thread."""
    if not HTTPX_AVAILABLE:
        return {"error": "httpx indisponível"}
    raw, finish = _fin_gemini_call(pdf_bytes, _FIN_STATEMENT_PROMPT, 8192, 300)
    if finish.startswith("ERROR:"):
        return {"error": finish[len("ERROR:"):]}
    if finish == "MAX_TOKENS":
        return {"error": "truncado"}  # resposta cortada a meio → não confiar
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return {"error": "truncado"}
    try:
        parsed = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {"error": "truncado"}  # JSON inválido = provavelmente cortado
    return parsed if isinstance(parsed, dict) else {"error": "truncado"}


def _fin_acct_digits(s):
    """Normaliza um nº de conta para comparação: só dígitos, sem zeros à
    esquerda (torna comparáveis NIB/IBAN e nº interno)."""
    return re.sub(r"\D+", "", str(s or "")).lstrip("0")


def _fin_acct_match(a, b):
    """True se as duas contas (já normalizadas) forem a mesma: iguais, ou o
    mais curto (mín. 8 dígitos) contido no mais longo. Cobre NIB/IBAN vs nº
    interno: o NIB PT contém o nº de conta (seguido de 2 dígitos de controlo,
    por isso 'contido' e não apenas sufixo)."""
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 8 and shorter in longer


def _fin_chain_check(movs):
    """Valida a cadeia de saldos (lista JÁ em ordem cronológica antigo→recente):
    balance[i] deve ser balance[i-1] + amount[i] (tolerância 0.01). Devolve o
    índice do 1.º movimento que falha, ou None se a cadeia for 100% válida.
    Com 0 ou 1 movimentos a cadeia é trivialmente válida."""
    for i in range(1, len(movs)):
        if abs(movs[i]["balance"] - (movs[i - 1]["balance"] + movs[i]["amount"])) > 0.01:
            return i
    return None


@api_router.post("/fin/movements/import-pdf")
async def fin_import_movements_pdf(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Importa movimentos a partir do PDF do extrato Millennium BCP.
    Roteia pela CONTA (não pela empresa do UI); valida a cadeia de saldos
    antes de importar; nunca duplica (dedup_key + comparação com migrados)."""
    # ---- 1) Ficheiro ----
    pdf_bytes = await file.read()
    if len(pdf_bytes) > _FIN_STATEMENT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Ficheiro demasiado grande (máx. 10 MB). Tenta um período mais curto ou o ficheiro .xlsx.",
        )
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="O ficheiro não parece ser um PDF.")

    # ---- 2) Extração via IA (HTTP síncrono em thread) ----
    ex = await asyncio.to_thread(_fin_extract_statement_sync, pdf_bytes)
    if not isinstance(ex, dict):
        raise HTTPException(status_code=422, detail=_FIN_STATEMENT_ERR_TRUNC)
    if ex.get("error"):
        if ex["error"] == "truncado":
            raise HTTPException(status_code=422, detail=_FIN_STATEMENT_ERR_TRUNC)
        raise HTTPException(status_code=502, detail=f"Falha na leitura do extrato (IA): {ex['error']}")

    movs_raw = ex.get("movements")
    if not isinstance(movs_raw, list):
        raise HTTPException(status_code=422, detail=_FIN_STATEMENT_ERR_TRUNC)
    total = len(movs_raw)
    holder = str(ex.get("holder") or "").strip() or None

    # ---- 3) Validação linha a linha (nunca inserir dados corrompidos) ----
    date_re = re.compile(r"\d{4}-\d{2}-\d{2}$")
    movs = []
    for r in movs_raw:
        if not isinstance(r, dict):
            raise HTTPException(status_code=422, detail=_FIN_STATEMENT_ERR_TRUNC)
        d = str(r.get("date_lancamento") or "").strip()
        amount = _fin_clean_num(r.get("amount"))
        balance = _fin_clean_num(r.get("balance"))
        if not date_re.match(d) or amount is None or balance is None:
            raise HTTPException(
                status_code=422,
                detail="O extrato tem um movimento com data ou valores ilegíveis: a extração pode ter falhado. Nada foi importado.",
            )
        dv = str(r.get("date_valor") or "").strip()
        movs.append({
            "date_lancamento": d,
            "date_valor": dv if date_re.match(dv) else None,
            "description": str(r.get("description") or "").strip() or None,
            "amount": amount,
            "balance": balance,
        })

    # ---- 4) Ordenação cronológica (o Millennium lista recente→antigo, mas
    # não assumimos: detetamos pela primeira vs última data) ----
    if len(movs) >= 2:
        first_d, last_d = movs[0]["date_lancamento"], movs[-1]["date_lancamento"]
        if first_d > last_d:
            # documento recente→antigo: inverter a lista TODA preserva
            # corretamente a ordem relativa dos empates (mesmo dia)
            movs = list(reversed(movs))
        elif first_d == last_d and _fin_chain_check(movs) is not None:
            # datas inconclusivas (tudo no mesmo dia): tenta a ordem inversa
            rev = list(reversed(movs))
            if _fin_chain_check(rev) is None:
                movs = rev

    # ---- 5) Validação aritmética da cadeia de saldos (OBRIGATÓRIA) ----
    bad = _fin_chain_check(movs)
    if bad is not None:
        mv = movs[bad]
        desc = re.sub(r"\s+", " ", mv.get("description") or "").strip()[:60]
        raise HTTPException(
            status_code=422,
            detail=(
                f"Validação de saldos falhou no movimento de {mv['date_lancamento']} "
                f"('{desc}'): a extração pode ter falhado. Nada foi importado."
            ),
        )

    # ---- 6) Roteamento pela conta (IGNORA a empresa selecionada no UI) ----
    acct_digits = _fin_acct_digits(ex.get("account_number"))
    if not acct_digits:
        raise HTTPException(
            status_code=422,
            detail="Não consegui identificar o número de conta no extrato. Nada foi importado.",
        )
    accounts = await db.fin_bank_accounts.find({}, {"_id": 0}).to_list(2000)
    matches = [a for a in accounts if _fin_acct_match(acct_digits, _fin_acct_digits(a.get("account_number")))]
    exact = [a for a in matches if _fin_acct_digits(a.get("account_number")) == acct_digits]
    acc = exact[0] if exact else (matches[0] if matches else None)
    if not acc:
        # 404 estruturado: o frontend usa isto para oferecer o registo da conta
        raise HTTPException(
            status_code=404,
            detail={"code": "conta_desconhecida", "account_number": acct_digits, "holder": holder or ""},
        )
    company_id = acc["company_id"]
    await fin_require_editor(company_id, current_user)

    # ---- 7) Anti-duplicação (2 níveis) + inserção ----
    # Nível 1: dedup_key canónico deste importador (nº de conta REGISTADO
    # normalizado, para que IBAN/NIB/nº interno no cabeçalho dêem a mesma key).
    # Nível 2: mesma conta + mesma data + amount e balance iguais a 2 casas —
    # apanha os movimentos migrados do .xlsx (dedup_key noutro formato e
    # descrições ligeiramente diferentes). Pré-carrega os candidatos do
    # período numa só query e compara com round(...,2) em Python.
    canon = _fin_acct_digits(acc.get("account_number")) or acct_digits
    d_min = movs[0]["date_lancamento"] if movs else None
    d_max = movs[-1]["date_lancamento"] if movs else None
    seen_lvl2 = set()
    if movs:
        existing = await db.fin_movements.find(
            {"account_id": acc["id"], "date_lancamento": {"$gte": d_min, "$lte": d_max}},
            {"_id": 0, "date_lancamento": 1, "amount": 1, "balance": 1},
        ).to_list(50000)
        for e in existing:
            ea = _fin_clean_num(e.get("amount"))
            eb = _fin_clean_num(e.get("balance"))
            if ea is None or eb is None:
                continue
            seen_lvl2.add((e.get("date_lancamento"), round(ea, 2), round(eb, 2)))

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0
    batch_keys = set()  # dedup dentro do próprio ficheiro
    for mv in movs:
        desc_norm = re.sub(r"\s+", " ", mv.get("description") or "").strip().upper()
        dedup_key = hashlib.sha1(
            f"{canon}|{mv['date_lancamento']}|{mv['amount']:.2f}|{mv['balance']:.2f}|{desc_norm}".encode()
        ).hexdigest()
        lvl2 = (mv["date_lancamento"], round(mv["amount"], 2), round(mv["balance"], 2))
        if dedup_key in batch_keys or lvl2 in seen_lvl2:
            skipped += 1
            continue
        if await db.fin_movements.find_one({"dedup_key": dedup_key}, {"_id": 0, "id": 1}):
            skipped += 1
            seen_lvl2.add(lvl2)
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "account_id": acc["id"],
            "company_id": company_id,
            "date_lancamento": mv["date_lancamento"],
            "date_valor": mv["date_valor"],
            "description": mv["description"],
            "amount": float(mv["amount"]),
            "balance": float(mv["balance"]),
            "currency": "EUR",
            "title": None,
            "invoice_id": None,
            "link_auto": False,
            "attachment_path": None,
            "dedup_key": dedup_key,
            "source": "bank_pdf",
            "created_by": current_user["user_id"],
            "created_at": now,
        }
        await db.fin_movements.insert_one(doc)
        batch_keys.add(dedup_key)
        seen_lvl2.add(lvl2)
        inserted += 1

    comp = await db.fin_companies.find_one({"id": company_id}, {"_id": 0, "name": 1})
    logger.info(
        "[fin-extrato-pdf] conta=***%s empresa=%s total_no_pdf=%d inseridos=%d ignorados=%d periodo=%s..%s",
        acct_digits[-4:], company_id, total, inserted, skipped, d_min, d_max,
    )
    return {
        "account_number": acct_digits,
        "company_id": company_id,
        "company_name": (comp or {}).get("name"),
        "inserted": inserted,
        "skipped": skipped,
        "total_no_pdf": total,
        "periodo": {"de": d_min, "ate": d_max},
        "holder": holder,
    }


# ===== FINANCEIRO · FASE 5 — VENDAS =====
# Vendas (coleção fin_sales). Base do módulo Vendas: lançamento manual e CRUD.
# A sincronização Vendus/Moloni é OUTRA fase. Aqui só CRUD manual.
# Campos: id, company_id, unit_id, date ("YYYY-MM-DD"), amount (bruto c/IVA),
# amount_net (líquido), amount_cost (CMV), net_nocost (líquido sem custo conhecido),
# vat_rate, note, source ("manual"|"vendus"|"moloni"), created_by, created_at.

# ---------- Modelo ----------

class FinSaleCreate(BaseModel):
    company_id: str
    unit_id: Optional[str] = None
    date: Optional[str] = None
    amount: Optional[float] = None
    amount_net: Optional[float] = None
    amount_cost: Optional[float] = None
    vat_rate: Optional[float] = None
    note: Optional[str] = None


# ---------- Helper: documento de venda a partir do payload ----------

def _fin_sale_doc_from_payload(data: dict) -> dict:
    """Calcula os campos derivados de uma venda manual a partir do body."""
    amount = _fin_clean_num(data.get("amount"))
    amount_net = _fin_clean_num(data.get("amount_net"))
    amount_cost = _fin_clean_num(data.get("amount_cost"))
    vat_rate = _fin_clean_num(data.get("vat_rate"))
    # Se não vier o líquido mas houver taxa de IVA, calcula a partir do bruto.
    if amount_net is None and amount is not None and vat_rate:
        amount_net = round(amount / (1 + vat_rate / 100), 2)
    return {
        "company_id": data["company_id"],
        "unit_id": data.get("unit_id"),
        "date": _fin_clean_date(data.get("date")),
        "amount": amount,
        "amount_net": amount_net,
        "amount_cost": amount_cost,
        "net_nocost": 0.0,
        "vat_rate": vat_rate,
        "note": data.get("note"),
    }


# ---------- Vendas ----------

@api_router.get("/fin/sales")
async def fin_get_sales(
    company_id: str,
    month: Optional[str] = None,
    unit_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Vendas de uma empresa, filtráveis por mês (YYYY-MM) e unidade.
    company_id="all" = todas as empresas onde o utilizador é membro."""
    if company_id == "all":
        ids = await fin_member_company_ids(current_user["user_id"])
        q = {"company_id": {"$in": ids}}
    else:
        await fin_require_member(company_id, current_user)
        q = {"company_id": company_id}
    mon = (month or "").strip()
    if mon:
        q["date"] = {"$regex": "^" + re.escape(mon)}
    uni = (unit_id or "").strip()
    if uni:
        q["unit_id"] = uni
    sales = await db.fin_sales.find(q, {"_id": 0}).to_list(20000)
    sales.sort(key=lambda s: s.get("date") or "", reverse=True)
    return sales

@api_router.post("/fin/sales")
async def fin_create_sale(payload: FinSaleCreate, current_user: dict = Depends(get_current_user)):
    """Lançamento MANUAL de venda."""
    await fin_require_editor(payload.company_id, current_user)
    data = payload.model_dump()
    doc = _fin_sale_doc_from_payload(data)
    doc.update({
        "id": str(uuid.uuid4()),
        "source": "manual",
        "created_by": current_user["user_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.fin_sales.insert_one(doc)
    return await db.fin_sales.find_one({"id": doc["id"]}, {"_id": 0})

@api_router.put("/fin/sales/{sale_id}")
async def fin_update_sale(sale_id: str, payload: FinSaleCreate, current_user: dict = Depends(get_current_user)):
    """Editar uma venda (validação de pertença pela empresa da venda)."""
    sale = await db.fin_sales.find_one({"id": sale_id}, {"_id": 0})
    if not sale:
        raise HTTPException(status_code=404, detail="Venda não encontrada.")
    await fin_require_editor(sale["company_id"], current_user)
    data = payload.model_dump()
    doc = _fin_sale_doc_from_payload(data)
    # Não deixar trocar a venda para outra empresa.
    doc.pop("company_id", None)
    await db.fin_sales.update_one({"id": sale_id}, {"$set": doc})
    return await db.fin_sales.find_one({"id": sale_id}, {"_id": 0})

@api_router.delete("/fin/sales/{sale_id}")
async def fin_delete_sale(sale_id: str, current_user: dict = Depends(get_current_user)):
    """Apagar uma venda (validação de pertença pela empresa da venda)."""
    sale = await db.fin_sales.find_one({"id": sale_id}, {"_id": 0})
    if not sale:
        raise HTTPException(status_code=404, detail="Venda não encontrada.")
    await fin_require_editor(sale["company_id"], current_user)
    await db.fin_sales.delete_one({"id": sale_id})
    return {"ok": True}


# ====================================================================
# ===== FINANCEIRO · FASE 6 — INTEGRAÇÃO GLOBAL =====
# ====================================================================
# Fundação para cruzar setores: liga a empresa/loja do Financeiro à do RH
# e expõe um Painel Global que junta KPIs de Financeiro + RH + Marketing.
# Reutiliza os helpers de pertença (fin_require_*) e o estilo dos /fin/*.


# ---------- Ligação RH <-> Financeiro ----------

@api_router.put("/fin/companies/{company_id}/link-rh")
async def fin_link_company_rh(
    company_id: str,
    payload: FinLinkRhCompany,
    current_user: dict = Depends(get_current_user),
):
    """Liga (ou desliga, com null) a empresa do Financeiro a uma empresa do RH.
    Só o dono. Se o id do RH vier preenchido, tem de existir em db.companies."""
    await fin_require_owner(company_id, current_user)
    fin_company = await db.fin_companies.find_one({"id": company_id}, {"_id": 0})
    if not fin_company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    rh_company_id = (payload.rh_company_id or "").strip() or None
    if rh_company_id:
        rh = await db.companies.find_one({"id": rh_company_id}, {"_id": 0, "id": 1})
        if not rh:
            raise HTTPException(status_code=400, detail="Empresa de RH inexistente.")
    await db.fin_companies.update_one(
        {"id": company_id}, {"$set": {"rh_company_id": rh_company_id}}
    )
    return await db.fin_companies.find_one({"id": company_id}, {"_id": 0})


@api_router.put("/fin/units/{unit_id}/link-rh")
async def fin_link_unit_rh(
    unit_id: str,
    payload: FinLinkRhUnit,
    current_user: dict = Depends(get_current_user),
):
    """Liga (ou desliga, com null) a unidade do Financeiro a um local do RH.
    Editor da empresa dona da unidade. Se preenchido, valida em db.locations."""
    unit = await db.fin_units.find_one({"id": unit_id}, {"_id": 0})
    if not unit:
        raise HTTPException(status_code=404, detail="Unidade não encontrada.")
    await fin_require_editor(unit["company_id"], current_user)
    rh_location_id = (payload.rh_location_id or "").strip() or None
    if rh_location_id:
        loc = await db.locations.find_one({"id": rh_location_id}, {"_id": 0, "id": 1})
        if not loc:
            raise HTTPException(status_code=400, detail="Local de RH inexistente.")
    await db.fin_units.update_one(
        {"id": unit_id}, {"$set": {"rh_location_id": rh_location_id}}
    )
    return await db.fin_units.find_one({"id": unit_id}, {"_id": 0})


# ---------- Painel Global (KPIs cruzados) ----------

@api_router.get("/fin/global/dashboard")
async def fin_global_dashboard(
    company_id: str,
    month: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Cruza KPIs de Financeiro + RH + Marketing para uma empresa e mês.
    `month` no formato AAAA-MM (por omissão, o mês atual). Cada setor é lido
    de forma defensiva: se um estiver em falta não derruba o painel todo.
    company_id="all" = vista agregada de todas as empresas do utilizador."""
    if company_id == "all":
        member_ids = await fin_member_company_ids(current_user["user_id"])
        cid_q = {"$in": member_ids}
        rh_company_id = None
        company_out = {"id": "all", "name": "Todas as empresas", "nif": None, "rh_company_id": None}
    else:
        await fin_require_member(company_id, current_user)
        fin_company = await db.fin_companies.find_one({"id": company_id}, {"_id": 0})
        if not fin_company:
            raise HTTPException(status_code=404, detail="Empresa não encontrada.")
        cid_q = company_id
        rh_company_id = fin_company.get("rh_company_id")
        company_out = {
            "id": fin_company.get("id"),
            "name": fin_company.get("name"),
            "nif": fin_company.get("nif"),
            "rh_company_id": rh_company_id,
        }

    mon = (month or "").strip()
    if not mon:
        mon = datetime.now(timezone.utc).strftime("%Y-%m")

    # ----- Financeiro -----
    financeiro = {
        "vendas_mes": 0.0,
        "a_pagar": 0.0,
        "pago": 0.0,
        "pendentes": 0,
        "vencidas": 0,
        "saldo_banco": 0.0,
    }
    try:
        # Vendas do mês (soma de fin_sales.amount cuja date começa por AAAA-MM)
        sales = await db.fin_sales.find(
            {"company_id": cid_q, "date": {"$regex": "^" + re.escape(mon)}},
            {"_id": 0, "amount": 1},
        ).to_list(100000)
        financeiro["vendas_mes"] = round(
            sum(float(s.get("amount") or 0) for s in sales), 2
        )

        # Faturas: a pagar (por pagar e não rejeitadas) e já pago
        invoices = await db.fin_invoices.find(
            {"company_id": cid_q},
            {"_id": 0, "amount": 1, "paid": 1, "approval_status": 1,
             "due_date": 1, "issue_date": 1, "nif": 1, "supplier": 1},
        ).to_list(100000)
        # Regras de fornecedor (partilhadas): para o vencimento efetivo e para
        # excluir os débitos diretos das "vencidas" (esses saem da conta sozinhos).
        rules_map = {}
        for r in await db.fin_supplier_rules.find({}, {"_id": 0}).to_list(5000):
            if r.get("supplier_key"):
                rules_map[r["supplier_key"]] = r
        a_pagar = 0.0
        pago = 0.0
        pendentes = 0
        vencidas = 0
        today_iso = datetime.now(timezone.utc).date().isoformat()
        for inv in invoices:
            amt = float(inv.get("amount") or 0)
            is_paid = inv.get("paid") is True
            appr = inv.get("approval_status")
            if is_paid:
                pago += amt
            elif appr != "rejected":
                a_pagar += amt
            if appr == "pending":
                pendentes += 1
            # Vencidas: por pagar, não rejeitadas, com vencimento EFETIVO (regras
            # de prazo do fornecedor aplicadas) anterior a hoje. Débitos diretos
            # não contam (saem por débito automático). Coerente com a Agenda.
            if (not is_paid) and appr != "rejected":
                rule = rules_map.get(fin_supplier_key_of(inv.get("nif"), inv.get("supplier")))
                if not (rule and rule.get("direct_debit")):
                    eff = _fin_effective_due(inv, rule)
                    if eff and str(eff) < today_iso:
                        vencidas += 1
        financeiro["a_pagar"] = round(a_pagar, 2)
        financeiro["pago"] = round(pago, 2)
        financeiro["pendentes"] = pendentes
        financeiro["vencidas"] = vencidas

        # Saldo em banco: para cada conta da empresa, o saldo (balance) do
        # movimento mais recente (maior date_lancamento). Soma de todas as contas.
        accounts = await db.fin_bank_accounts.find(
            {"company_id": cid_q}, {"_id": 0, "id": 1}
        ).to_list(2000)
        saldo_banco = 0.0
        for acc in accounts:
            last = await db.fin_movements.find_one(
                {"account_id": acc.get("id")},
                {"_id": 0, "balance": 1, "date_lancamento": 1},
                sort=[("date_lancamento", -1)],
            )
            if last and last.get("balance") is not None:
                saldo_banco += float(last.get("balance") or 0)
        financeiro["saldo_banco"] = round(saldo_banco, 2)
    except Exception:
        # Falha defensiva: mantém os valores por omissão sem derrubar o painel.
        pass

    # ----- RH -----
    rh = {"linked": False}
    colaboradores = 0
    try:
        if company_id == "all":
            # Vista agregada: totais do grupo (sem depender de ligações).
            rh["linked"] = True
            colaboradores = await db.employees.count_documents({})
            rh["colaboradores"] = colaboradores
            rh["ausencias_pendentes"] = await db.leave_requests.count_documents(
                {"status": "pendente"}
            )
        elif rh_company_id:
            rh_company = await db.companies.find_one(
                {"id": rh_company_id}, {"_id": 0, "id": 1}
            )
            if rh_company:
                rh["linked"] = True
                colaboradores = await db.employees.count_documents(
                    {"company_id": rh_company_id}
                )
                rh["colaboradores"] = colaboradores
                # Ausências pendentes: primeiro os employees dessa empresa RH,
                # depois conta os leave_requests pendentes desses colaboradores.
                emp_docs = await db.employees.find(
                    {"company_id": rh_company_id}, {"_id": 0, "id": 1}
                ).to_list(100000)
                emp_ids = [e["id"] for e in emp_docs if e.get("id")]
                if emp_ids:
                    rh["ausencias_pendentes"] = await db.leave_requests.count_documents(
                        {"employee_id": {"$in": emp_ids}, "status": "pendente"}
                    )
                else:
                    rh["ausencias_pendentes"] = 0
    except Exception:
        rh = {"linked": bool(rh_company_id)}
        colaboradores = 0

    # Quem está a trabalhar AGORA e em que loja (último registo de hoje =
    # entrada; mesma lógica do dashboard do RH). Empresa ligada -> só os dela;
    # sem ligação -> grupo todo (mais útil do que um aviso).
    try:
        emp_q = {"company_id": rh_company_id} if (rh.get("linked") and rh_company_id) else {}
        emps = await db.employees.find(
            emp_q, {"_id": 0, "id": 1, "name": 1, "location_id": 1}
        ).to_list(100000)
        emp_by_id = {e["id"]: e for e in emps if e.get("id")}
        a_trabalhar = []
        if emp_by_id:
            now_lis = datetime.now(LISBON_TZ)
            day_start_utc = now_lis.replace(
                hour=0, minute=0, second=0, microsecond=0
            ).astimezone(timezone.utc).isoformat()
            recs = await db.time_records.find(
                {"time": {"$gte": day_start_utc},
                 "employee_id": {"$in": list(emp_by_id)}},
                {"_id": 0, "employee_id": 1, "record_type": 1, "time": 1},
            ).sort("time", 1).to_list(10000)
            last_type = {}
            entry_at = {}
            for r in recs:
                eid = r["employee_id"]
                last_type[eid] = r.get("record_type")
                if r.get("record_type") == "entrada":
                    try:
                        _dt = datetime.fromisoformat(r.get("time"))
                        if _dt.tzinfo is None:
                            _dt = _dt.replace(tzinfo=timezone.utc)
                        entry_at[eid] = _dt.astimezone(LISBON_TZ).strftime("%H:%M")
                    except (ValueError, TypeError):
                        entry_at[eid] = None
            loc_ids = {e.get("location_id") for e in emp_by_id.values() if e.get("location_id")}
            locs = await db.locations.find(
                {"id": {"$in": list(loc_ids)}}, {"_id": 0, "id": 1, "name": 1}
            ).to_list(2000) if loc_ids else []
            loc_name = {l["id"]: l.get("name") for l in locs}
            for eid, t in last_type.items():
                if t != "entrada":
                    continue
                e = emp_by_id.get(eid) or {}
                a_trabalhar.append({
                    "nome": e.get("name") or "?",
                    "loja": loc_name.get(e.get("location_id")) or "—",
                    "desde": entry_at.get(eid),
                })
            a_trabalhar.sort(key=lambda x: (x["loja"], x["nome"]))
        rh["a_trabalhar"] = a_trabalhar[:60]
    except Exception:
        rh["a_trabalhar"] = []

    # ----- Marketing -----
    marketing = {"campanhas_ativas": 0}
    try:
        mkt_q = ({"status": "ativa"} if company_id == "all" else {
            "status": "ativa",
            "$or": [
                {"company_id": company_id},
                {"company_id": None},
                {"company_id": {"$exists": False}},
            ],
        })
        marketing["campanhas_ativas"] = await db.mkt_campaigns.count_documents(
            mkt_q
        )
    except Exception:
        pass

    # ----- Cruzados -----
    receita_por_colaborador = None
    if colaboradores and colaboradores > 0:
        receita_por_colaborador = round(
            financeiro["vendas_mes"] / colaboradores, 2
        )
    cruzados = {"receita_por_colaborador": receita_por_colaborador}

    return {
        "company": company_out,
        "month": mon,
        "financeiro": financeiro,
        "rh": rh,
        "marketing": marketing,
        "cruzados": cruzados,
    }


# ====================================================================
# ===== FINANCEIRO · FASE 5B — INTEGRAÇÃO VENDUS =====
# ====================================================================
# Sincronização de vendas do POS Vendus -> coleção fin_sales.
# Reimplementação fiel do PHP vendus_engine.php / vendus_sync.php.
#
# Regra de VENDAS: soma de faturas (FT/FS/FR/VD) menos notas de crédito (NC).
# Exclui recibos (RG), documentos de conferência (DC) e tudo o resto.
# Agrega por loja e por dia; grava idempotente (delete+insert) por loja,
# e SÓ se a loja foi lida por completo no intervalo.
#
# Como na ingestão IMAP (Fase 4B): o HTTP à API Vendus é síncrono (httpx.Client)
# e corre em threads via asyncio.to_thread; as escritas Mongo (motor) ficam no
# event loop. Tudo defensivo — uma conta/loja com falha não aborta as restantes.
#
# Config: VENDUS_ACCOUNTS no .env (JSON array numa linha), uma entrada por
# conta Vendus: [{"key":"CHAVE_API","company_nif":"NIF"}]. A empresa é
# encontrada em fin_companies pelo NIF.

import time as _time
import random as _random

_FIN_VENDUS_BASE = "https://www.vendus.pt/ws/v1.1/"
_FIN_VENDUS_SALES = ("FT", "FS", "FR", "VD")   # sinal +
_FIN_VENDUS_CREDIT = ("NC",)                    # sinal −
_FIN_VENDUS_COST_TTL = 6 * 3600                 # cache do mapa de custos: 6h
_FIN_VENDUS_MAX_DOC_PAGES = 60                  # >6000 docs/loja -> reduz o período
_FIN_VENDUS_MAX_PROD_PAGES = 100


def _fin_vendus_accounts():
    """Lê VENDUS_ACCOUNTS do ambiente (JSON array). Lista vazia se ausente/inválido."""
    raw = os.environ.get("VENDUS_ACCOUNTS") or "[]"
    try:
        accounts = json.loads(raw)
        return accounts if isinstance(accounts, list) else []
    except Exception as _e:  # noqa: BLE001
        logger.warning("[fin-vendus] VENDUS_ACCOUNTS inválido: %s", _e)
        return []


def _fin_vendus_http(key, path, tries=3):
    """GET à API Vendus com HTTP Basic (chave, ''). Devolve o JSON (list/dict)
    ou None. Erro de rede/timeout/429/>=500 -> repete com backoff exponencial
    (0.3s*2^n + jitter) até `tries`; 4xx (exceto 429) -> desiste e devolve None.
    Síncrono — corre em thread via asyncio.to_thread."""
    attempt = 0
    while True:
        attempt += 1
        resp = None
        retriable = False
        try:
            with httpx.Client(
                timeout=httpx.Timeout(18.0, connect=6.0), auth=(key, "")
            ) as http_client:
                resp = http_client.get(
                    _FIN_VENDUS_BASE + path, headers={"Accept": "application/json"}
                )
            retriable = resp.status_code == 429 or resp.status_code >= 500
        except Exception:  # noqa: BLE001 — rede/timeout
            retriable = True
        if retriable and attempt < tries:
            _time.sleep(0.3 * (2 ** (attempt - 1)) + _random.uniform(0, 0.2))
            continue
        if resp is None or resp.status_code < 200 or resp.status_code >= 300:
            return None
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return None
        return data if isinstance(data, (list, dict)) else None


def _fin_vendus_norm(s):
    """Nome normalizado p/ mapear loja Vendus -> unidade: minúsculas, sem
    acentos, só [a-z0-9 ], espaços colapsados (equivalente ao vendus_norm PHP)."""
    s = str(s or "").strip().lower()
    s = s.translate(str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn"))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fin_vendus_match_unit(units, store_title):
    """Mapeia uma loja Vendus para uma unidade da empresa: 1 unidade = direta;
    senão por nome normalizado (igualdade, depois 'contém' em qualquer direção).
    Devolve o unit_id ou None."""
    if len(units) == 1:
        return units[0]["id"]
    nt = _fin_vendus_norm(store_title)
    for u in units:
        if _fin_vendus_norm(u.get("name")) == nt:
            return u["id"]
    if nt:
        for u in units:
            un = _fin_vendus_norm(u.get("name"))
            if un and (un in nt or nt in un):
                return u["id"]
    return None


def _fin_vendus_cost_map(key, ttl=_FIN_VENDUS_COST_TTL):
    """Mapa preço-de-custo por referência de produto (supply_price), p/ calcular
    o CMV. Cacheado em UPLOAD_DIR/vendus (TTL 6h) para não repetir o fetch de
    produtos a cada sync. Síncrono — corre em thread."""
    cache_dir = UPLOAD_DIR / "vendus"
    cache_f = cache_dir / ("costmap_" + hashlib.sha1(str(key).encode()).hexdigest() + ".json")
    try:
        if cache_f.is_file() and (_time.time() - cache_f.stat().st_mtime) < ttl:
            cached = json.loads(cache_f.read_text())
            if isinstance(cached, dict) and cached:
                return cached
    except Exception:  # noqa: BLE001 — cache corrompida: refaz
        pass
    cmap = {}
    page = 1
    while True:
        ps = _fin_vendus_http(key, f"products/?per_page=100&page={page}")
        if not isinstance(ps, list) or not ps:
            break
        for p in ps:
            if not isinstance(p, dict):
                continue
            ref = p.get("reference")
            ref = str(ref) if ref not in (None, "") else str(p.get("title") or "")
            if ref:
                cmap[ref] = _fin_clean_num(p.get("supply_price")) or 0.0
        if len(ps) < 100:
            break
        page += 1
        if page > _FIN_VENDUS_MAX_PROD_PAGES:
            break
    if cmap:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_f.write_text(json.dumps(cmap))
        except Exception:  # noqa: BLE001 — sem cache não é fatal
            pass
    return cmap


def _fin_vendus_fetch_store_days(key, store_id, since, until, with_cost, cost_map):
    """Lê os documentos paginados de UMA loja no intervalo e agrega por dia.
    Devolve (by_day, complete, error): by_day = {dia: [gross, net, cmv,
    net_sem_custo]}. Só HTTP e agregação (sem BD) — corre em thread.

    CMV: lê as linhas de cada fatura (qty × custo do produto). É pesado
    (1 chamada por documento) -> só no cron (with_cost=True). O botão web
    sincroniza as vendas depressa (sem CMV) e o custo é preenchido pelo cron."""
    by_day = {}
    page = 1
    while True:
        docs = _fin_vendus_http(
            key,
            f"documents/?since={since}&until={until}&store_id={store_id}&per_page=100&page={page}",
        )
        if not isinstance(docs, list) or not docs:
            break
        for x in docs:
            if not isinstance(x, dict):
                continue
            t = x.get("type") or ""
            if t in _FIN_VENDUS_SALES:
                sign = 1
            elif t in _FIN_VENDUS_CREDIT:
                sign = -1
            else:
                continue  # RG, DC, etc. — ignorados
            g = _fin_clean_num(x.get("amount_gross")) or 0.0
            n = _fin_clean_num(x.get("amount_net")) or 0.0
            day = str(x.get("date") or "")[:10]
            if not day:
                continue
            acc = by_day.setdefault(day, [0.0, 0.0, 0.0, 0.0])
            acc[0] += sign * g
            acc[1] += sign * n
            if with_cost:
                det = _fin_vendus_http(key, f"documents/{x.get('id')}/")
                if isinstance(det, list):  # a resposta pode vir como lista
                    det = det[0] if det else None
                items = det.get("items") if isinstance(det, dict) else None
                if not isinstance(items, list):
                    items = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    qty = _fin_clean_num(it.get("qty")) or 0.0
                    ref = it.get("reference")
                    ref = str(ref) if ref not in (None, "") else str(it.get("title") or "")
                    amounts = it.get("amounts") if isinstance(it.get("amounts"), dict) else {}
                    itnet = _fin_clean_num(amounts.get("net_total")) or 0.0
                    cost = _fin_clean_num(cost_map.get(ref)) if ref else None
                    if cost and cost > 0:
                        acc[2] += sign * qty * cost
                    else:
                        acc[3] += sign * itnet
        if len(docs) < 100:
            break
        page += 1
        if page > _FIN_VENDUS_MAX_DOC_PAGES:
            # Leitura incompleta: NÃO gravar (o PHP gravava mesmo assim; aqui
            # é tratado como incompleto para nunca subcontar vendas).
            return by_day, False, "demasiados documentos (>6000) no intervalo — reduz o período"
    return by_day, True, None


async def _fin_vendus_write_store(company_id, unit_id, since, until, by_day, with_cost, store_title):
    """Grava os dias agregados de uma loja em fin_sales de forma idempotente:
    delete_many do intervalo (source vendus, mesma empresa/loja) + insert dos
    dias com valores. Sync rápido (with_cost=False): preserva amount_cost/
    net_nocost já calculados pelo cron, para não os apagar até à próxima
    passagem noturna. Devolve o número de linhas escritas."""
    flt = {
        "source": "vendus",
        "company_id": company_id,
        "unit_id": unit_id,
        "date": {"$gte": since, "$lte": until},
    }
    prev = {}
    if not with_cost:
        old = await db.fin_sales.find(
            flt, {"_id": 0, "date": 1, "amount_cost": 1, "net_nocost": 1}
        ).to_list(20000)
        for r in old:
            d = str(r.get("date") or "")[:10]
            prev[d] = (
                _fin_clean_num(r.get("amount_cost")) or 0.0,
                _fin_clean_num(r.get("net_nocost")) or 0.0,
            )
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for day in sorted(by_day):
        gross, net, cmv, nocost = by_day[day]
        g = round(gross, 2)
        n = round(net, 2)
        if g == 0 and n == 0:
            continue  # dias sem vendas não geram linha
        if with_cost:
            cost, nc = round(cmv, 2), round(nocost, 2)
        else:
            pc = prev.get(day, (0.0, 0.0))
            cost, nc = round(pc[0], 2), round(pc[1], 2)
        rate = round((g / n - 1) * 100, 2) if n > 0 else None
        docs.append({
            "id": str(uuid.uuid4()),
            "company_id": company_id,
            "unit_id": unit_id,
            "date": day,
            "amount": g,
            "amount_net": n,
            "amount_cost": cost,
            "net_nocost": nc,
            "vat_rate": rate,
            "note": store_title,
            "source": "vendus",
            "created_by": None,
            "created_at": now,
        })
    await db.fin_sales.delete_many(flt)
    if docs:
        await db.fin_sales.insert_many(docs)
    return len(docs)


async def _fin_vendus_run_account(acc, since, until, with_cost):
    """Sincroniza UMA conta Vendus (todas as lojas dela). Devolve
    {'written': n, 'stores': [{'store','nif','days','net','cmv','complete'}],
    'errors': [...]}. Defensivo: uma loja com falha não aborta as restantes."""
    out = {"written": 0, "stores": [], "errors": []}
    key = str(acc.get("key") or "")
    nif = _fin_only_digits(acc.get("company_nif"))
    if not key or not nif:
        out["errors"].append("conta Vendus mal configurada (key/company_nif em falta)")
        return out

    # Empresa pelo NIF (comparação só por dígitos, como no PHP).
    company = None
    companies = await db.fin_companies.find({}, {"_id": 0, "id": 1, "nif": 1}).to_list(5000)
    for c in companies:
        if _fin_only_digits(c.get("nif")) == nif:
            company = c
            break
    if not company:
        out["errors"].append(f"empresa NIF {nif} não encontrada")
        return out
    company_id = company["id"]
    units = await db.fin_units.find(
        {"company_id": company_id}, {"_id": 0, "id": 1, "name": 1}
    ).to_list(1000)

    stores = await asyncio.to_thread(_fin_vendus_http, key, "stores/")
    if not isinstance(stores, list):
        out["errors"].append(f"falha a obter lojas (NIF {nif}) — chave inválida?")
        return out
    cost_map = (await asyncio.to_thread(_fin_vendus_cost_map, key)) if with_cost else {}

    for store in stores:
        if not isinstance(store, dict):
            continue
        sid = store.get("id")
        title = str(store.get("title") or "")
        unit_id = _fin_vendus_match_unit(units, title)
        if not unit_id:
            out["errors"].append(
                f"loja Vendus '{title}' (store_id={sid}) sem unidade correspondente (NIF {nif})"
            )
            continue
        try:
            by_day, complete, err = await asyncio.to_thread(
                _fin_vendus_fetch_store_days, key, sid, since, until, with_cost, cost_map
            )
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"loja '{title}' (NIF {nif}): falha a ler — {exc}")
            continue
        if err:
            out["errors"].append(f"loja '{title}': {err}")

        # Só gravamos se a loja foi lida por COMPLETO no intervalo: assim o
        # delete+insert nunca deixa dias apagados sem voltarem a ser inseridos.
        if complete:
            try:
                out["written"] += await _fin_vendus_write_store(
                    company_id, unit_id, since, until, by_day, with_cost, title
                )
            except Exception:  # noqa: BLE001
                out["errors"].append(f"loja '{title}' (NIF {nif}): falha a gravar")

        sn = round(sum(v[1] for v in by_day.values()), 2)
        sc = round(sum(v[2] for v in by_day.values()), 2)
        out["stores"].append({
            "store": title,
            "nif": nif,
            "days": len(by_day),
            "net": sn,
            "cmv": sc,
            "complete": complete,
        })
    return out


def _fin_vendus_default_range(since, until):
    """Aplica as omissões do PHP: until=hoje, since=há 3 dias (UTC)."""
    today = datetime.now(timezone.utc)
    u = (until or "").strip() or today.strftime("%Y-%m-%d")
    s = (since or "").strip() or (today - timedelta(days=3)).strftime("%Y-%m-%d")
    return s, u


# ---------- Modelo ----------

class FinVendusSyncRequest(BaseModel):
    company_id: str
    since: Optional[str] = None
    until: Optional[str] = None
    with_cost: Optional[bool] = False


# ---------- Endpoints ----------

@api_router.post("/fin/vendus/sync")
async def fin_vendus_sync(payload: FinVendusSyncRequest, current_user: dict = Depends(get_current_user)):
    """Sincronização manual (botão 'Sincronizar' no frontend). Corre o motor
    SÓ para a conta Vendus da empresa indicada. Por omissão sem CMV
    (with_cost=False): rápido; o custo é preenchido pelo cron noturno."""
    await fin_require_editor(payload.company_id, current_user)

    accounts = _fin_vendus_accounts()
    if not accounts:
        raise HTTPException(
            status_code=400, detail="Integração Vendus não configurada (VENDUS_ACCOUNTS)."
        )
    company = await db.fin_companies.find_one({"id": payload.company_id}, {"_id": 0, "nif": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    nif = _fin_only_digits(company.get("nif"))
    acc = None
    if nif:
        for a in accounts:
            if isinstance(a, dict) and _fin_only_digits(a.get("company_nif")) == nif:
                acc = a
                break
    if not acc:
        raise HTTPException(status_code=400, detail="Empresa sem conta Vendus configurada.")

    since, until = _fin_vendus_default_range(payload.since, payload.until)
    logger.info(
        "[fin-vendus] sync manual: empresa=%s %s..%s with_cost=%s",
        payload.company_id, since, until, bool(payload.with_cost),
    )
    result = await _fin_vendus_run_account(acc, since, until, bool(payload.with_cost))
    logger.info(
        "[fin-vendus] sync manual fim: written=%d lojas=%d erros=%d",
        result["written"], len(result["stores"]), len(result["errors"]),
    )
    return {"since": since, "until": until, **result}


@api_router.post("/fin/cron/vendus")
async def fin_cron_vendus(
    key: str = Query(...),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    with_cost: bool = Query(True),
):
    """Sincronização automática (cron). Protegido por CRON_KEY, sem JWT.
    Corre TODAS as contas de VENDUS_ACCOUNTS. `with_cost=false` = sync rápido
    horário (sem CMV, preserva o custo já calculado pelo noturno)."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or not secrets.compare_digest(str(key), str(cron_key)):
        raise HTTPException(status_code=403, detail="Acesso negado.")

    since_s, until_s = _fin_vendus_default_range(since, until)
    accounts = _fin_vendus_accounts()
    logger.info("[fin-vendus] cron: %s..%s contas=%d cmv=%s", since_s, until_s, len(accounts), with_cost)

    out = {
        "since": since_s,
        "until": until_s,
        "accounts": len(accounts),
        "written": 0,
        "stores": [],
        "errors": [],
    }
    for ai, acc in enumerate(accounts):
        if not isinstance(acc, dict):
            out["errors"].append(f"entrada #{ai} inválida em VENDUS_ACCOUNTS")
            continue
        try:
            r = await _fin_vendus_run_account(acc, since_s, until_s, with_cost)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(
                f"conta NIF {_fin_only_digits(acc.get('company_nif'))}: {exc}"
            )
            continue
        out["written"] += r["written"]
        out["stores"].extend(r["stores"])
        out["errors"].extend(r["errors"])

    logger.info(
        "[fin-vendus] cron fim: written=%d lojas=%d erros=%d",
        out["written"], len(out["stores"]), len(out["errors"]),
    )
    return out


# ====================================================================
# ===== FINANCEIRO · FASE 7 — INTEGRAÇÃO MOLONI =====
# ====================================================================
# Sincronização de vendas do software de faturação Moloni -> fin_sales,
# com a MESMA arquitetura do motor Vendus (Fase 5B): HTTP síncrono
# (httpx.Client) em threads via asyncio.to_thread; escritas Mongo (motor)
# no event loop; gravação idempotente (delete+insert) SÓ com leitura completa.
#
# Regra de VENDAS por dia: Σ(faturas + faturas-recibo + faturas simplificadas)
# − Σ(notas de crédito), no intervalo [since, until]. Só documentos FECHADOS
# (status=1); rascunhos (0) e anulados (2) são ignorados.
#
# API Moloni (confirmado em https://www.moloni.pt/dev/):
#   - OAuth2:    GET https://api.moloni.pt/v1/grant/  grant_type=password
#                (client_id, client_secret, username, password) e
#                grant_type=refresh_token; resposta {access_token,
#                refresh_token, expires_in (3600), ...}. O access_token vai
#                como parâmetro GET em todas as chamadas seguintes.
#   - Empresas:  GET companies/getAll/ -> [{company_id, name, vat, ...}]
#   - Documentos: GET invoices/getAll/, invoiceReceipts/getAll/,
#                simplifiedInvoices/getAll/, creditNotes/getAll/
#                params: company_id (obrig.), qty (máx 50), offset, year, ...
#                campos: date, gross_value, taxes_value, net_value, status.
#                NOTA: net_value é o TOTAL do documento c/ impostos (o plugin
#                oficial Moloni↔WooCommerce compara-o ao total da encomenda);
#                total s/ IVA = net_value − taxes_value.
#   O getAll NÃO tem filtro de intervalo de datas (só data exata/ano):
#   defensivamente pagina-se por `year` e filtra-se o dia do lado do cliente.
#
# Config (.env): MOLONI_CLIENT_ID, MOLONI_CLIENT_SECRET, MOLONI_USERNAME,
# MOLONI_PASSWORD, MOLONI_COMPANY_NIF. A empresa DESTINO é a de fin_companies
# com esse NIF. Nunca logar tokens/credenciais (vão nos params do URL).

import threading as _threading

_FIN_MOLONI_BASE = "https://api.moloni.pt/v1/"
_FIN_MOLONI_DOC_TYPES = (
    ("invoices", 1),            # faturas (FT)             sinal +
    ("invoiceReceipts", 1),     # faturas-recibo (FR)      sinal +
    ("simplifiedInvoices", 1),  # faturas simplificadas    sinal +
    ("creditNotes", -1),        # notas de crédito (NC)    sinal −
)
_FIN_MOLONI_QTY = 50            # máximo da API por página
_FIN_MOLONI_MAX_PAGES = 100     # orçamento de páginas por tipo de documento

# Token OAuth2 em memória (partilhado pelas threads do motor).
_fin_moloni_token = {"access": None, "refresh": None, "exp": 0.0}
_fin_moloni_token_lock = _threading.Lock()


def _fin_moloni_config():
    """Lê MOLONI_* do ambiente. Devolve o dict de config (NIF só dígitos) ou
    None se faltar qualquer variável."""
    cfg = {
        "client_id": (os.environ.get("MOLONI_CLIENT_ID") or "").strip(),
        "client_secret": (os.environ.get("MOLONI_CLIENT_SECRET") or "").strip(),
        "username": (os.environ.get("MOLONI_USERNAME") or "").strip(),
        "password": (os.environ.get("MOLONI_PASSWORD") or "").strip(),
        "company_nif": _fin_only_digits(os.environ.get("MOLONI_COMPANY_NIF")),
    }
    return cfg if all(cfg.values()) else None


def _fin_moloni_http(path, params, tries=3):
    """Chamada à API Moloni. O `grant/` vai por GET (params na query); os
    restantes endpoints exigem POST form-encoded com o access_token na query
    (confirmado contra a API real: getAll por GET falha). Devolve o JSON
    (list/dict) ou None. Retries iguais ao Vendus: rede/timeout/429/>=500 ->
    repete com backoff exponencial até `tries`; 4xx (exceto 429) -> desiste.
    Síncrono — corre em thread.
    NUNCA logar o URL/params (levam credenciais e o access_token)."""
    attempt = 0
    while True:
        attempt += 1
        resp = None
        retriable = False
        try:
            with httpx.Client(timeout=httpx.Timeout(18.0, connect=6.0)) as http_client:
                if path.startswith("grant/"):
                    resp = http_client.get(
                        _FIN_MOLONI_BASE + path,
                        params=params,
                        headers={"Accept": "application/json"},
                    )
                else:
                    form = dict(params)
                    query = {"access_token": form.pop("access_token", "")}
                    resp = http_client.post(
                        _FIN_MOLONI_BASE + path,
                        params=query,
                        data=form,
                        headers={"Accept": "application/json"},
                    )
            retriable = resp.status_code == 429 or resp.status_code >= 500
        except Exception:  # noqa: BLE001 — rede/timeout
            retriable = True
        if retriable and attempt < tries:
            _time.sleep(0.3 * (2 ** (attempt - 1)) + _random.uniform(0, 0.2))
            continue
        if resp is None or resp.status_code < 200 or resp.status_code >= 300:
            return None
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return None
        return data if isinstance(data, (list, dict)) else None


def _fin_moloni_grant(cfg):
    """Garante um access_token válido (cache em memória). Renova quando
    faltar <60s para expirar: primeiro via refresh_token, com fallback a novo
    grant password. Devolve o token ou None. Síncrono — corre em thread."""
    with _fin_moloni_token_lock:
        now = _time.time()
        if _fin_moloni_token["access"] and now < _fin_moloni_token["exp"] - 60:
            return _fin_moloni_token["access"]
        data = None
        if _fin_moloni_token["refresh"]:
            data = _fin_moloni_http("grant/", {
                "grant_type": "refresh_token",
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "refresh_token": _fin_moloni_token["refresh"],
            })
        if not isinstance(data, dict) or not data.get("access_token"):
            data = _fin_moloni_http("grant/", {
                "grant_type": "password",
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "username": cfg["username"],
                "password": cfg["password"],
            })
        if not isinstance(data, dict) or not data.get("access_token"):
            _fin_moloni_token.update({"access": None, "refresh": None, "exp": 0.0})
            return None
        expires = _fin_clean_num(data.get("expires_in")) or 3600.0
        _fin_moloni_token["access"] = str(data["access_token"])
        _fin_moloni_token["refresh"] = str(data.get("refresh_token") or "") or None
        _fin_moloni_token["exp"] = now + expires
        return _fin_moloni_token["access"]


def _fin_moloni_api(cfg, path, params):
    """Chamada autenticada à API Moloni: injeta o access_token nos params.
    Se falhar (ex.: token invalidado a meio), força um grant novo e repete
    UMA vez. Devolve o JSON ou None. Síncrono — corre em thread."""
    token = _fin_moloni_grant(cfg)
    if not token:
        return None
    data = _fin_moloni_http(path, {**params, "access_token": token})
    if data is None:
        with _fin_moloni_token_lock:
            _fin_moloni_token["exp"] = 0.0  # invalida a cache
        token = _fin_moloni_grant(cfg)
        if not token:
            return None
        data = _fin_moloni_http(path, {**params, "access_token": token})
    return data


def _fin_moloni_company_id(cfg):
    """companies/getAll -> company_id da empresa Moloni cujo NIF (campo `vat`,
    só dígitos) coincide com MOLONI_COMPANY_NIF. Devolve (company_id, None) ou
    (None, erro). Síncrono — corre em thread."""
    companies = _fin_moloni_api(cfg, "companies/getAll/", {})
    if not isinstance(companies, list):
        return None, "falha a obter as empresas Moloni — credenciais inválidas?"
    for c in companies:
        if isinstance(c, dict) and _fin_only_digits(c.get("vat")) == cfg["company_nif"]:
            cid = c.get("company_id")
            if cid:
                return int(cid), None
    return None, f"empresa NIF {cfg['company_nif']} não encontrada na conta Moloni"


def _fin_moloni_fetch_days(cfg, moloni_company_id, since, until):
    """Lê os 4 tipos de documentos de venda, paginados (qty=50), e agrega por
    dia no intervalo [since, until]. Devolve (by_day, complete, error) com
    by_day = {dia: [total_c_iva, total_s_iva]}.

    Como o getAll não filtra por intervalo de datas, pede-se por `year`
    (parâmetro documentado) e filtra-se o dia do lado do cliente. Ignora
    documentos não fechados (status != 1: rascunho/anulado). Se o orçamento de
    páginas esgotar ou uma leitura falhar -> complete=False e NADA é gravado
    (nunca subcontar vendas). Só HTTP e agregação (sem BD) — corre em thread."""
    by_day = {}
    years = range(int(since[:4]), int(until[:4]) + 1)
    for path, sign in _FIN_MOLONI_DOC_TYPES:
        pages_left = _FIN_MOLONI_MAX_PAGES
        for year in years:
            offset = 0
            while True:
                if pages_left <= 0:
                    return by_day, False, (
                        f"{path}: demasiados documentos no intervalo — reduz o período"
                    )
                pages_left -= 1
                docs = _fin_moloni_api(cfg, f"{path}/getAll/", {
                    "company_id": moloni_company_id,
                    "year": year,
                    "qty": _FIN_MOLONI_QTY,
                    "offset": offset,
                })
                if docs is None:
                    return by_day, False, f"{path}: falha a ler os documentos (ano {year})"
                if not isinstance(docs, list) or not docs:
                    break
                for x in docs:
                    if not isinstance(x, dict):
                        continue
                    st = _fin_clean_num(x.get("status"))
                    if st is not None and int(st) != 1:
                        continue  # 0=rascunho, 2=anulado — ignorados
                    day = str(x.get("date") or "")[:10]
                    if not day or day < since or day > until:
                        continue  # filtro de datas do lado do cliente
                    total = _fin_clean_num(x.get("net_value")) or 0.0    # c/ IVA
                    taxes = _fin_clean_num(x.get("taxes_value")) or 0.0
                    acc = by_day.setdefault(day, [0.0, 0.0])
                    acc[0] += sign * total
                    acc[1] += sign * (total - taxes)                     # s/ IVA
                if len(docs) < _FIN_MOLONI_QTY:
                    break
                offset += _FIN_MOLONI_QTY
    return by_day, True, None


async def _fin_moloni_write(company_id, unit_id, since, until, by_day):
    """Grava os dias agregados em fin_sales de forma idempotente: delete_many
    do intervalo (source moloni, mesma empresa) + insert dos dias com valores.
    CMV Moloni fica para depois: amount_cost/net_nocost = 0.0.
    Devolve o número de linhas escritas."""
    flt = {
        "source": "moloni",
        "company_id": company_id,
        "date": {"$gte": since, "$lte": until},
    }
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for day in sorted(by_day):
        gross, net = by_day[day]
        g = round(gross, 2)
        n = round(net, 2)
        if g == 0 and n == 0:
            continue  # dias sem vendas não geram linha
        rate = round((g / n - 1) * 100, 2) if n > 0 else None
        docs.append({
            "id": str(uuid.uuid4()),
            "company_id": company_id,
            "unit_id": unit_id,
            "date": day,
            "amount": g,
            "amount_net": n,
            "amount_cost": 0.0,
            "net_nocost": 0.0,
            "vat_rate": rate,
            "note": "Moloni",
            "source": "moloni",
            "created_by": None,
            "created_at": now,
        })
    await db.fin_sales.delete_many(flt)
    if docs:
        await db.fin_sales.insert_many(docs)
    return len(docs)


async def _fin_moloni_run(cfg, since, until):
    """Sincroniza a conta Moloni configurada no intervalo. Devolve
    {'written': n, 'days': n, 'net': x, 'complete': bool, 'errors': [...]}.
    Defensivo: qualquer falha vai para errors sem levantar exceção."""
    out = {"written": 0, "days": 0, "net": 0.0, "complete": False, "errors": []}

    # Empresa DESTINO no app: fin_companies com o NIF configurado.
    company = None
    companies = await db.fin_companies.find({}, {"_id": 0, "id": 1, "nif": 1}).to_list(5000)
    for c in companies:
        if _fin_only_digits(c.get("nif")) == cfg["company_nif"]:
            company = c
            break
    if not company:
        out["errors"].append(
            f"empresa NIF {cfg['company_nif']} não encontrada em fin_companies"
        )
        return out
    company_id = company["id"]

    # unit_id: se a empresa tem exatamente 1 unidade, usa-a; senão None.
    units = await db.fin_units.find(
        {"company_id": company_id}, {"_id": 0, "id": 1}
    ).to_list(1000)
    unit_id = units[0]["id"] if len(units) == 1 else None

    moloni_cid, err = await asyncio.to_thread(_fin_moloni_company_id, cfg)
    if err:
        out["errors"].append(err)
        return out

    try:
        by_day, complete, err = await asyncio.to_thread(
            _fin_moloni_fetch_days, cfg, moloni_cid, since, until
        )
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"Moloni: falha a ler — {exc}")
        return out
    if err:
        out["errors"].append(err)

    # Só gravamos com leitura COMPLETA: o delete+insert nunca deixa dias
    # apagados sem voltarem a ser inseridos.
    if complete:
        try:
            out["written"] = await _fin_moloni_write(
                company_id, unit_id, since, until, by_day
            )
        except Exception:  # noqa: BLE001
            out["errors"].append("Moloni: falha a gravar em fin_sales")

    out["days"] = len(by_day)
    out["net"] = round(sum(v[1] for v in by_day.values()), 2)
    out["complete"] = complete
    return out


# ---------- Modelos ----------

class FinMoloniSyncRequest(BaseModel):
    company_id: str
    since: Optional[str] = None
    until: Optional[str] = None


class FinSalesSyncRequest(BaseModel):
    company_id: str
    since: Optional[str] = None
    until: Optional[str] = None
    with_cost: Optional[bool] = False


# ---------- Endpoints ----------

@api_router.post("/fin/moloni/sync")
async def fin_moloni_sync(payload: FinMoloniSyncRequest, current_user: dict = Depends(get_current_user)):
    """Sincronização manual Moloni (botão no frontend). Por omissão:
    until=hoje, since=há 3 dias — como no Vendus."""
    await fin_require_editor(payload.company_id, current_user)

    cfg = _fin_moloni_config()
    if not cfg:
        raise HTTPException(status_code=400, detail="Integração Moloni não configurada.")
    company = await db.fin_companies.find_one({"id": payload.company_id}, {"_id": 0, "nif": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    if _fin_only_digits(company.get("nif")) != cfg["company_nif"]:
        raise HTTPException(
            status_code=400,
            detail="Esta empresa não corresponde ao NIF configurado no Moloni.",
        )

    since, until = _fin_vendus_default_range(payload.since, payload.until)
    logger.info(
        "[fin-moloni] sync manual: empresa=%s %s..%s", payload.company_id, since, until
    )
    result = await _fin_moloni_run(cfg, since, until)
    logger.info(
        "[fin-moloni] sync manual fim: written=%d dias=%d erros=%d",
        result["written"], result["days"], len(result["errors"]),
    )
    return {"since": since, "until": until, **result}


@api_router.post("/fin/cron/moloni")
async def fin_cron_moloni(
    key: str = Query(...),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
):
    """Sincronização automática Moloni (cron). Protegido por CRON_KEY, sem JWT.
    Corre a conta configurada em MOLONI_*."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or not secrets.compare_digest(str(key), str(cron_key)):
        raise HTTPException(status_code=403, detail="Acesso negado.")

    since_s, until_s = _fin_vendus_default_range(since, until)
    cfg = _fin_moloni_config()
    if not cfg:
        return {
            "since": since_s,
            "until": until_s,
            "written": 0,
            "errors": ["integração Moloni não configurada (MOLONI_*)"],
        }

    logger.info("[fin-moloni] cron: %s..%s", since_s, until_s)
    try:
        result = await _fin_moloni_run(cfg, since_s, until_s)
    except Exception as exc:  # noqa: BLE001
        result = {"written": 0, "errors": [f"Moloni: {exc}"]}
    logger.info(
        "[fin-moloni] cron fim: written=%d erros=%d",
        result.get("written", 0), len(result.get("errors", [])),
    )
    return {"since": since_s, "until": until_s, **result}


@api_router.post("/fin/sales/sync")
async def fin_sales_sync(payload: FinSalesSyncRequest, current_user: dict = Depends(get_current_user)):
    """Despachante de sincronização de vendas: escolhe o motor de faturação
    pela empresa — Vendus se o NIF está em VENDUS_ACCOUNTS; senão Moloni se
    configurado com esse NIF. Acrescenta `engine` à resposta."""
    await fin_require_editor(payload.company_id, current_user)

    company = await db.fin_companies.find_one({"id": payload.company_id}, {"_id": 0, "nif": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    nif = _fin_only_digits(company.get("nif"))
    since, until = _fin_vendus_default_range(payload.since, payload.until)

    # 1) Vendus: a empresa tem conta em VENDUS_ACCOUNTS?
    acc = None
    if nif:
        for a in _fin_vendus_accounts():
            if isinstance(a, dict) and _fin_only_digits(a.get("company_nif")) == nif:
                acc = a
                break
    if acc:
        logger.info(
            "[fin-moloni] despacho -> vendus: empresa=%s %s..%s with_cost=%s",
            payload.company_id, since, until, bool(payload.with_cost),
        )
        result = await _fin_vendus_run_account(acc, since, until, bool(payload.with_cost))
        return {"engine": "vendus", "since": since, "until": until, **result}

    # 2) Moloni: configurado e com o NIF desta empresa?
    cfg = _fin_moloni_config()
    if cfg and nif and nif == cfg["company_nif"]:
        logger.info(
            "[fin-moloni] despacho -> moloni: empresa=%s %s..%s",
            payload.company_id, since, until,
        )
        result = await _fin_moloni_run(cfg, since, until)
        return {"engine": "moloni", "since": since, "until": until, **result}

    raise HTTPException(
        status_code=400, detail="Empresa sem integração de faturação configurada."
    )


# ===== FINANCEIRO · FASE 8 — SYNC MANUAL (botões do Painel Global) =====
# Um botão por sistema: Vendus (todas as contas, rápido), Moloni (fábrica)
# e ingestão de faturas por email. Todos com JWT; a permissão é verificada
# por empresa (só sincroniza o que o utilizador pode editar).

async def _fin_user_is_editor_somewhere(current_user: dict) -> bool:
    """True se o utilizador é owner/partner de pelo menos uma empresa fin."""
    m = await db.fin_company_members.find_one(
        {"user_id": current_user["user_id"], "role": {"$in": ["owner", "partner"]}},
        {"_id": 0, "company_id": 1},
    )
    return bool(m)

async def _fin_user_is_member_somewhere(current_user: dict) -> bool:
    """True se o utilizador é membro (qualquer papel) de pelo menos uma empresa fin.
    Usado para restringir recursos GLOBAIS (ex.: regras de fornecedor) a quem
    trabalha no Financeiro, bloqueando logins sem qualquer pertença."""
    m = await db.fin_company_members.find_one(
        {"user_id": current_user["user_id"]}, {"_id": 0, "company_id": 1},
    )
    return bool(m)

@api_router.post("/fin/sync/vendus")
async def fin_manual_sync_vendus(current_user: dict = Depends(get_current_user)):
    """Botão 'Atualizar Vendus': todas as contas, sync rápido (sem CMV),
    últimos 3 dias. Salta contas de empresas onde o utilizador não é editor."""
    accounts = _fin_vendus_accounts()
    if not accounts:
        raise HTTPException(status_code=400, detail="Integração Vendus não configurada (VENDUS_ACCOUNTS).")
    since_s, until_s = _fin_vendus_default_range(None, None)
    out = {"engine": "vendus", "since": since_s, "until": until_s,
           "written": 0, "stores": [], "errors": []}
    ran = 0
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        nif = _fin_only_digits(acc.get("company_nif"))
        comp = await db.fin_companies.find_one({"nif": nif}, {"_id": 0, "id": 1, "name": 1})
        if not comp:
            out["errors"].append(f"empresa NIF {nif} não encontrada")
            continue
        role = await fin_role_of(comp["id"], current_user["user_id"])
        if role not in ("owner", "partner"):
            out["errors"].append(f"{comp['name']}: sem permissão de edição — saltada")
            continue
        try:
            r = await _fin_vendus_run_account(acc, since_s, until_s, False)
            out["written"] += r["written"]
            out["stores"].extend(r["stores"])
            out["errors"].extend(r["errors"])
            ran += 1
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{comp['name']}: {exc}")
    if ran == 0 and out["errors"]:
        raise HTTPException(status_code=403, detail="Sem permissão para sincronizar nenhuma conta Vendus.")
    return out

@api_router.post("/fin/sync/moloni")
async def fin_manual_sync_moloni(current_user: dict = Depends(get_current_user)):
    """Botão 'Atualizar Moloni': a conta configurada (Purple House), últimos 3 dias."""
    cfg = _fin_moloni_config()
    if not all([cfg["client_id"], cfg["client_secret"], cfg["username"], cfg["password"], cfg["company_nif"]]):
        raise HTTPException(status_code=400, detail="Integração Moloni não configurada.")
    comp = await db.fin_companies.find_one({"nif": cfg["company_nif"]}, {"_id": 0, "id": 1})
    if not comp:
        raise HTTPException(status_code=404, detail="Empresa do Moloni não encontrada no Financeiro.")
    await fin_require_editor(comp["id"], current_user)
    since_s, until_s = _fin_vendus_default_range(None, None)
    result = await _fin_moloni_run(cfg, since_s, until_s)
    return {"engine": "moloni", "since": since_s, "until": until_s, **result}

@api_router.post("/fin/sync/ingest")
async def fin_manual_sync_ingest(current_user: dict = Depends(get_current_user)):
    """Botão 'Ler faturas do email agora': dispara a ingestão IMAP+IA.
    Incremental (anexos já vistos são saltados), por isso é rápido no dia-a-dia."""
    if not await _fin_user_is_editor_somewhere(current_user):
        raise HTTPException(status_code=403, detail="Sem permissão de edição no Financeiro.")
    cron_key = os.environ.get("CRON_KEY") or ""
    if not cron_key:
        raise HTTPException(status_code=400, detail="Ingestão não configurada (CRON_KEY).")
    # Reutiliza a lógica (testada) do endpoint de cron, passando a chave real.
    return await fin_cron_ingest(key=cron_key)


# ====================================================================
# FASE 17 — RELATÓRIOS
# Relatórios financeiros ADITIVOS (só leitura): Apuramento de IVA, DRE,
# Exportação para contabilista (CSV) e Mapa de tesouraria previsional.
# Nada altera a lógica existente. Autorização e âmbito idênticos ao
# resto de /fin/* (fin_require_member / fin_member_company_ids para "all").
# ====================================================================

def _fin_report_period(start: Optional[str], end: Optional[str]):
    """Período (start, end) inclusivo em ISO 'YYYY-MM-DD'. Por omissão, o mês
    corrente em hora de Lisboa (1º dia..último dia)."""
    s = (start or "").strip()
    e = (end or "").strip()
    if not s or not e:
        today = datetime.now(LISBON_TZ).date()
        first = today.replace(day=1)
        last = date(today.year, today.month, _calendar.monthrange(today.year, today.month)[1])
        if not s:
            s = first.isoformat()
        if not e:
            e = last.isoformat()
    return s, e


async def _fin_report_scope(company_id: str, current_user: dict):
    """Filtro de âmbito para os relatórios. company_id='all' -> {'$in': ids}
    (todas as empresas onde é membro); senão valida a pertença e devolve o id.
    O valor devolvido usa-se diretamente como {'company_id': <isto>} e também
    como {'id': <isto>} em fin_companies (o Mongo aceita string ou {'$in'})."""
    if company_id == "all":
        ids = await fin_member_company_ids(current_user["user_id"])
        return {"$in": ids}
    await fin_require_member(company_id, current_user)
    return company_id


def _fin_rate_key(rate):
    """Chave de taxa de IVA como string: 23.0 -> '23'; None -> 'sem_taxa'."""
    if rate is None:
        return "sem_taxa"
    try:
        f = float(rate)
    except (TypeError, ValueError):
        return "sem_taxa"
    return str(int(f)) if f == int(f) else str(f)


_FIN_MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
                 "jul", "ago", "set", "out", "nov", "dez"]


@api_router.get("/fin/reports/iva")
async def fin_report_iva(
    company_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Apuramento de IVA do período: liquidado (vendas) vs dedutível (compras)."""
    cid_q = await _fin_report_scope(company_id, current_user)
    start, end = _fin_report_period(start, end)

    # IVA liquidado (vendas): iva = amount - amount_net por venda.
    sales = await db.fin_sales.find(
        {"company_id": cid_q, "date": {"$gte": start, "$lte": end}},
        {"_id": 0, "amount": 1, "amount_net": 1, "vat_rate": 1},
    ).to_list(200000)
    liq_por_taxa: dict = {}
    liq_total = 0.0
    for s in sales:
        net = _fin_clean_num(s.get("amount_net"))
        amt = _fin_clean_num(s.get("amount"))
        iva = 0.0 if net is None else round((amt or 0.0) - net, 2)
        key = _fin_rate_key(s.get("vat_rate"))
        liq_por_taxa[key] = round(liq_por_taxa.get(key, 0.0) + iva, 2)
        liq_total += iva
    liq_total = round(liq_total, 2)

    # IVA dedutível (compras): usa vat_amount das faturas (invoice|payment).
    invoices = await db.fin_invoices.find(
        {"company_id": cid_q, "kind": {"$in": ["invoice", "payment"]},
         "issue_date": {"$gte": start, "$lte": end}},
        {"_id": 0, "vat_amount": 1, "vat_rate": 1, "approval_status": 1},
    ).to_list(200000)
    ded_por_taxa: dict = {}
    ded_total = 0.0
    for inv in invoices:
        if inv.get("approval_status") == "rejected":
            continue
        iva = _fin_clean_num(inv.get("vat_amount")) or 0.0
        key = _fin_rate_key(inv.get("vat_rate"))
        ded_por_taxa[key] = round(ded_por_taxa.get(key, 0.0) + iva, 2)
        ded_total += iva
    ded_total = round(ded_total, 2)

    saldo = round(liq_total - ded_total, 2)
    return {
        "periodo": {"start": start, "end": end},
        "liquidado": {"total": liq_total, "por_taxa": liq_por_taxa},
        "dedutivel": {"total": ded_total, "por_taxa": ded_por_taxa},
        "saldo": saldo,
        "a_pagar": round(max(0.0, saldo), 2),
        "a_recuperar": round(max(0.0, -saldo), 2),
    }


@api_router.get("/fin/reports/dre")
async def fin_report_dre(
    company_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Demonstração de resultados simplificada do período."""
    cid_q = await _fin_report_scope(company_id, current_user)
    start, end = _fin_report_period(start, end)

    sales = await db.fin_sales.find(
        {"company_id": cid_q, "date": {"$gte": start, "$lte": end}},
        {"_id": 0, "amount_net": 1, "amount_cost": 1},
    ).to_list(200000)
    vendas_liquidas = round(sum((_fin_clean_num(s.get("amount_net")) or 0.0) for s in sales), 2)
    cmv = round(sum((_fin_clean_num(s.get("amount_cost")) or 0.0) for s in sales), 2)
    margem_bruta = round(vendas_liquidas - cmv, 2)

    invoices = await db.fin_invoices.find(
        {"company_id": cid_q, "kind": {"$in": ["invoice", "payment"]},
         "issue_date": {"$gte": start, "$lte": end}},
        {"_id": 0, "amount_net": 1, "amount": 1, "category": 1, "approval_status": 1},
    ).to_list(200000)
    por_categoria: dict = {}
    despesas_total = 0.0
    for inv in invoices:
        if inv.get("approval_status") == "rejected":
            continue
        base = _fin_clean_num(inv.get("amount_net"))
        if base is None:
            base = _fin_clean_num(inv.get("amount")) or 0.0
        cat = inv.get("category") or "sem_categoria"
        por_categoria[cat] = round(por_categoria.get(cat, 0.0) + base, 2)
        despesas_total += base
    despesas_total = round(despesas_total, 2)
    resultado = round(margem_bruta - despesas_total, 2)

    return {
        "periodo": {"start": start, "end": end},
        "vendas_liquidas": vendas_liquidas,
        "cmv": cmv,
        "margem_bruta": margem_bruta,
        "despesas": {"por_categoria": por_categoria, "total": despesas_total},
        "resultado": resultado,
        "food_cost_pct": round(cmv / vendas_liquidas * 100, 1) if vendas_liquidas > 0 else 0,
    }


@api_router.get("/fin/reports/export")
async def fin_report_export(
    company_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    kind: str = "invoices",
    current_user: dict = Depends(get_current_user),
):
    """Exportação CSV (separador ';', decimais com vírgula, BOM p/ Excel PT).
    kind=invoices (por omissão) ou kind=sales."""
    from fastapi.responses import StreamingResponse

    cid_q = await _fin_report_scope(company_id, current_user)
    start, end = _fin_report_period(start, end)
    kind = "sales" if (kind or "").strip().lower() == "sales" else "invoices"

    # Nomes de empresas (o Mongo aceita string ou {'$in'} no campo 'id').
    companies = await db.fin_companies.find(
        {"id": cid_q}, {"_id": 0, "id": 1, "name": 1}
    ).to_list(2000)
    comp_name = {c["id"]: (c.get("name") or "") for c in companies}

    def _cell(v):
        s = "" if v is None else str(v)
        if any(c in s for c in (";", '"', "\n", "\r")):
            s = '"' + s.replace('"', '""') + '"'
        return s

    def _money(v):
        n = _fin_clean_num(v)
        return "" if n is None else f"{n:.2f}".replace(".", ",")

    def _rate(v):
        n = _fin_clean_num(v)
        if n is None:
            return ""
        txt = str(int(n)) if n == int(n) else f"{n:g}"
        return txt.replace(".", ",")

    lines = []
    if kind == "sales":
        header = ["Empresa", "Data", "Loja", "Base", "IVA", "Total", "CMV", "Origem"]
        lines.append(";".join(_cell(h) for h in header))
        units = await db.fin_units.find(
            {"company_id": cid_q}, {"_id": 0, "id": 1, "name": 1}
        ).to_list(5000)
        unit_name = {u["id"]: (u.get("name") or "") for u in units}
        rows = await db.fin_sales.find(
            {"company_id": cid_q, "date": {"$gte": start, "$lte": end}}, {"_id": 0}
        ).to_list(200000)
        rows.sort(key=lambda r: (r.get("date") or "", comp_name.get(r.get("company_id"), "")))
        for r in rows:
            net = _fin_clean_num(r.get("amount_net"))
            amt = _fin_clean_num(r.get("amount"))
            iva = "" if (net is None or amt is None) else _money(round(amt - net, 2))
            loja = unit_name.get(r.get("unit_id")) or "Comum"
            lines.append(";".join([
                _cell(comp_name.get(r.get("company_id"), "")),
                _cell(r.get("date")),
                _cell(loja),
                _money(r.get("amount_net")),
                iva,
                _money(r.get("amount")),
                _money(r.get("amount_cost")),
                _cell(r.get("source")),
            ]))
        fname = f"vendas_{start}_a_{end}.csv"
    else:
        header = ["Empresa", "Data Emissao", "Vencimento", "Tipo", "Fornecedor",
                  "NIF", "Nº Fatura", "Base", "IVA", "Taxa", "Total",
                  "Categoria", "Pago", "Data Pagamento"]
        lines.append(";".join(_cell(h) for h in header))
        rows = await db.fin_invoices.find(
            {"company_id": cid_q, "kind": {"$in": ["invoice", "payment"]},
             "issue_date": {"$gte": start, "$lte": end}}, {"_id": 0}
        ).to_list(200000)
        rows = [r for r in rows if r.get("approval_status") != "rejected"]
        rows.sort(key=lambda r: (r.get("issue_date") or "", comp_name.get(r.get("company_id"), "")))
        for r in rows:
            tipo = "Pagamento" if r.get("kind") == "payment" else "Fatura"
            pago = "Sim" if r.get("paid") is True else "Não"
            lines.append(";".join([
                _cell(comp_name.get(r.get("company_id"), "")),
                _cell(r.get("issue_date")),
                _cell(r.get("due_date")),
                _cell(tipo),
                _cell(r.get("supplier")),
                _cell(r.get("nif")),
                _cell(r.get("invoice_number")),
                _money(r.get("amount_net")),
                _money(r.get("vat_amount")),
                _rate(r.get("vat_rate")),
                _money(r.get("amount")),
                _cell(r.get("category")),
                pago,
                _cell(r.get("paid_date")),
            ]))
        fname = f"faturas_{start}_a_{end}.csv"

    body = "﻿" + "\r\n".join(lines) + "\r\n"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api_router.get("/fin/reports/tesouraria")
async def fin_report_tesouraria(
    company_id: str,
    weeks: int = 8,
    current_user: dict = Depends(get_current_user),
):
    """Mapa de tesouraria previsional: saldo atual + saídas previstas por semana
    (vencimento efetivo das faturas por pagar) e saldo previsto acumulado."""
    cid_q = await _fin_report_scope(company_id, current_user)
    try:
        weeks = int(weeks)
    except (TypeError, ValueError):
        weeks = 8
    weeks = max(1, min(26, weeks))

    # Saldo atual em banco (mesma lógica do dashboard global): último movimento
    # de cada conta, somado. Contas sem saldo contam 0.
    accounts = await db.fin_bank_accounts.find(
        {"company_id": cid_q}, {"_id": 0, "id": 1}
    ).to_list(2000)
    saldo_atual = 0.0
    for acc in accounts:
        last = await db.fin_movements.find_one(
            {"account_id": acc.get("id")},
            {"_id": 0, "balance": 1, "date_lancamento": 1},
            sort=[("date_lancamento", -1)],
        )
        if last and last.get("balance") is not None:
            saldo_atual += float(last.get("balance") or 0)
    saldo_atual = round(saldo_atual, 2)

    # Regras de fornecedor (para o vencimento efetivo).
    rules_map: dict = {}
    for r in await db.fin_supplier_rules.find({}, {"_id": 0}).to_list(5000):
        if r.get("supplier_key"):
            rules_map[r["supplier_key"]] = r

    invoices = await db.fin_invoices.find(
        {"company_id": cid_q, "paid": {"$ne": True}},
        {"_id": 0, "amount": 1, "paid": 1, "approval_status": 1,
         "due_date": 1, "issue_date": 1, "nif": 1, "supplier": 1},
    ).to_list(200000)

    today = datetime.now(LISBON_TZ).date()
    monday = today - timedelta(days=today.weekday())  # 2ª feira desta semana
    week_starts = [monday + timedelta(days=7 * i) for i in range(weeks)]
    horizon_end = week_starts[-1] + timedelta(days=6)  # domingo da última semana

    saidas_semana = [0.0] * weeks
    em_atraso = 0.0
    for inv in invoices:
        if inv.get("approval_status") == "rejected" or inv.get("paid") is True:
            continue
        amt = _fin_clean_num(inv.get("amount")) or 0.0
        rule = rules_map.get(fin_supplier_key_of(inv.get("nif"), inv.get("supplier")))
        eff = _fin_effective_due(inv, rule)
        if not eff:
            continue
        try:
            eff_d = date.fromisoformat(str(eff)[:10])
        except (ValueError, TypeError):
            continue
        if eff_d < today:
            em_atraso += amt
        elif eff_d <= horizon_end:
            idx = (eff_d - monday).days // 7
            if 0 <= idx < weeks:
                saidas_semana[idx] += amt
        # eff_d além do horizonte: fica de fora das semanas mostradas.

    semanas = []
    running = 0.0
    for i in range(weeks):
        ws = week_starts[i]
        we = ws + timedelta(days=6)
        saidas = round(saidas_semana[i], 2)
        running += saidas
        saldo_previsto = round(saldo_atual - running, 2)
        if ws.month == we.month:
            label = f"{ws.day}–{we.day} {_FIN_MESES_PT[we.month - 1]}"
        else:
            label = f"{ws.day} {_FIN_MESES_PT[ws.month - 1]}–{we.day} {_FIN_MESES_PT[we.month - 1]}"
        semanas.append({
            "inicio": ws.isoformat(),
            "fim": we.isoformat(),
            "label": label,
            "saidas": saidas,
            "saldo_previsto": saldo_previsto,
            "negativo": saldo_previsto < 0,
        })

    return {
        "saldo_atual": saldo_atual,
        "em_atraso": round(em_atraso, 2),
        "semanas": semanas,
    }


# ==================== HEALTH CHECK ====================

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

# Include the router in the main app
app.include_router(api_router)

# CORS: em produção definir CORS_ORIGINS com o(s) domínio(s) do frontend,
# separados por vírgula (ex.: https://rh.suaempresa.pt). Em dev fica '*'.
# Nota: com origens '*' não é permitido allow_credentials=True (o browser rejeita).
# Como a autenticação usa Bearer token no header (não cookies), isto é seguro.
cors_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '*').split(',') if o.strip()]
# Origens da app nativa (Capacitor, iOS/Android) — para a app poder chamar a API
# mesmo que um dia se restrinja o CORS a domínios específicos. Não afeta o '*'.
APP_NATIVE_ORIGINS = ["capacitor://localhost", "ionic://localhost", "http://localhost", "https://localhost"]
if '*' not in cors_origins:
    for _o in APP_NATIVE_ORIGINS:
        if _o not in cors_origins:
            cors_origins.append(_o)
app.add_middleware(
    CORSMiddleware,
    allow_credentials='*' not in cors_origins,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    await ensure_master_admin_exists()

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


if __name__ == "__main__":
    # Arranque direto para desenvolvimento: `python server.py`
    # Em produção (VPS) usar antes:
    #   uvicorn server:app --host 0.0.0.0 --port 8000 --workers 2
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
